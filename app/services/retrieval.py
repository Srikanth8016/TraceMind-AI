"""
app/services/retrieval.py — Vector retrieval and similarity search service.

Milestone 9: Runbook ingestion, embeddings, vector retrieval, and RAG integration.

Design Decisions
----------------
1. **Hybrid Execution (PostgreSQL pgvector & SQLite Fallback)**:
   - On PostgreSQL with pgvector, executes SQL cosine distance `<=>` queries.
   - On SQLite (in-process test database), queries candidate chunks and evaluates
     exact dot-product cosine similarity in Python over normalized vectors.
2. **Deterministic Scoping**:
   If a service_name is specified, retrieves runbooks scoped to that service as well
   as global runbooks (service_name is NULL).
3. **Similarity Threshold Filtering**:
   Chunks with similarity scores below `min_similarity` are discarded to prevent
   irrelevant noise from polluting the LLM context.
"""

from dataclasses import dataclass
import logging
from typing import List, Optional
import uuid

from sqlalchemy import desc, select, text
from sqlalchemy.orm import Session

from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.services.embedding.factory import get_embedding_provider

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    """
    Structured passage retrieved via vector similarity search.
    """
    chunk_id: str
    document_id: uuid.UUID
    document_title: str
    source: str
    service_name: Optional[str]
    similarity_score: float
    content: str


def _python_cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """
    Compute cosine similarity for unit-normalized vectors via dot product.
    """
    if len(v1) != len(v2) or not v1:
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    return max(0.0, min(1.0, dot))


def search_relevant_chunks(
    session: Session,
    query: str,
    top_k: int = 3,
    min_similarity: float = 0.4,
    service_name: Optional[str] = None,
) -> List[RetrievedChunk]:
    """
    Perform vector similarity search against ingested runbooks and SOP passages.

    Parameters
    ----------
    session : Session
        Active database session.
    query : str
        Technical incident description or search query.
    top_k : int
        Maximum number of passages to return (1 to 20).
    min_similarity : float
        Minimum similarity score threshold (0.0 to 1.0).
    service_name : Optional[str]
        Optional service name to filter by.

    Returns
    -------
    List[RetrievedChunk]
        Ranked list of relevant passages.
    """
    top_k = max(1, min(20, top_k))
    min_similarity = max(0.0, min(1.0, min_similarity))

    embed_provider = get_embedding_provider()
    query_vector = embed_provider.embed_text(query)

    bind = session.get_bind()
    dialect_name = bind.dialect.name if bind else "sqlite"

    results: List[RetrievedChunk] = []

    if dialect_name == "postgresql":
        # Check if pgvector is enabled and execute native vector cosine distance
        try:
            vector_str = f"[{','.join(str(float(x)) for x in query_vector)}]"
            query_sql = """
                SELECT
                    kc.stable_chunk_id,
                    kc.document_id,
                    kd.title AS document_title,
                    kd.source AS source,
                    kd.service_name AS service_name,
                    1.0 - (kc.embedding <=> :query_vector::vector) AS similarity,
                    kc.content
                FROM knowledge_chunks kc
                JOIN knowledge_documents kd ON kc.document_id = kd.id
                WHERE (kd.service_name IS NULL OR :service_name IS NULL OR kd.service_name = :service_name)
                  AND (1.0 - (kc.embedding <=> :query_vector::vector)) >= :min_similarity
                ORDER BY similarity DESC
                LIMIT :top_k;
            """
            rows = session.execute(
                text(query_sql),
                {
                    "query_vector": vector_str,
                    "service_name": service_name,
                    "min_similarity": min_similarity,
                    "top_k": top_k,
                },
            ).fetchall()

            for row in rows:
                results.append(
                    RetrievedChunk(
                        chunk_id=str(row[0]),
                        document_id=uuid.UUID(str(row[1])),
                        document_title=str(row[2]),
                        source=str(row[3]),
                        service_name=str(row[4]) if row[4] else None,
                        similarity_score=round(float(row[5]), 4),
                        content=str(row[6]),
                    )
                )
            return results
        except Exception as exc:
            logger.warning(
                "PostgreSQL pgvector query failed (%s); falling back to in-memory evaluation.",
                exc,
            )

    # In-memory evaluation fallback (standard for SQLite in test suites)
    stmt = (
        select(KnowledgeChunk, KnowledgeDocument)
        .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
    )
    if service_name:
        stmt = stmt.where(
            (KnowledgeDocument.service_name.is_(None)) | (KnowledgeDocument.service_name == service_name)
        )

    rows = session.execute(stmt).all()
    scored: List[tuple[float, KnowledgeChunk, KnowledgeDocument]] = []

    for chunk, doc in rows:
        sim = _python_cosine_similarity(query_vector, chunk.embedding)
        if sim >= min_similarity:
            scored.append((sim, chunk, doc))

    # Sort descending by similarity score
    scored.sort(key=lambda x: x[0], reverse=True)

    for sim, chunk, doc in scored[:top_k]:
        results.append(
            RetrievedChunk(
                chunk_id=chunk.stable_chunk_id,
                document_id=doc.id,
                document_title=doc.title,
                source=doc.source,
                service_name=doc.service_name,
                similarity_score=round(sim, 4),
                content=chunk.content,
            )
        )

    return results
