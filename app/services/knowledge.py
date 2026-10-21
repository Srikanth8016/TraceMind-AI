"""
app/services/knowledge.py — Runbook ingestion, text chunking, and deduplication service.

Milestone 9: Runbook ingestion, embeddings, vector retrieval, and RAG integration.

Design Decisions
----------------
1. **Sentence & Paragraph Preserving Chunking**:
   Splits text cleanly along paragraph (`\\n\\n`) and line (`\\n`) boundaries with bounded
   character windows and configurable overlap to maintain semantic continuity across chunk edges.
2. **Stable Chunk Identifiers**:
   Assigns stable identifiers (``doc:<doc_id>:chunk:<idx>``) to chunks so they can be cited
   verifiably by the investigation orchestrator.
3. **Idempotent Ingestion & Content-Hash Deduplication**:
   Computes SHA-256 hashes of complete document content. If an identical document already
   exists, the existing document is returned and re-embedding is skipped.
4. **Zero Sensitive Content Logging**:
   Only logs document IDs, titles, chunk counts, and content hashes. Never logs raw runbook text.
"""

import hashlib
import logging
import re
from typing import List, Tuple
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.services.embedding.factory import get_embedding_provider

logger = logging.getLogger(__name__)

DEFAULT_TARGET_CHUNK_SIZE = 700
DEFAULT_CHUNK_OVERLAP = 150
MAX_DOCUMENT_BYTES = 1_048_576  # 1 MB


def compute_content_hash(text: str) -> str:
    """
    Calculate the hex-encoded SHA-256 content hash of normalized text.
    """
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def chunk_text(
    text: str,
    target_chunk_size: int = DEFAULT_TARGET_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> List[str]:
    """
    Split a document into bounded, overlapping chunks preserving paragraph boundaries.

    Parameters
    ----------
    text : str
        Raw document text.
    target_chunk_size : int
        Target character length per chunk (default: 700).
    chunk_overlap : int
        Number of characters to overlap between sequential chunks (default: 150).

    Returns
    -------
    List[str]
        List of non-empty text chunks.
    """
    cleaned = text.strip()
    if not cleaned:
        return []

    if len(cleaned) <= target_chunk_size:
        return [cleaned]

    # Split into logical sections by double newline
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", cleaned) if p.strip()]
    if not paragraphs:
        paragraphs = [cleaned]

    chunks: List[str] = []
    current_chunk: List[str] = []
    current_length = 0

    for para in paragraphs:
        # If single paragraph is massive, break into sentence segments
        if len(para) > target_chunk_size:
            sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", para) if s.strip()]
            for sent in sentences:
                sent_len = len(sent)
                if current_length + sent_len + 1 > target_chunk_size and current_chunk:
                    chunk_str = "\n\n".join(current_chunk).strip()
                    if chunk_str:
                        chunks.append(chunk_str)
                    # Compute overlap tail
                    overlap_seed = chunk_str[-chunk_overlap:] if chunk_overlap < len(chunk_str) else chunk_str
                    current_chunk = [overlap_seed, sent]
                    current_length = len(overlap_seed) + sent_len + 1
                else:
                    current_chunk.append(sent)
                    current_length += sent_len + 1
        else:
            para_len = len(para)
            if current_length + para_len + 1 > target_chunk_size and current_chunk:
                chunk_str = "\n\n".join(current_chunk).strip()
                if chunk_str:
                    chunks.append(chunk_str)
                # Compute overlap tail
                overlap_seed = chunk_str[-chunk_overlap:] if chunk_overlap < len(chunk_str) else chunk_str
                current_chunk = [overlap_seed, para]
                current_length = len(overlap_seed) + para_len + 1
            else:
                current_chunk.append(para)
                current_length += para_len + 1

    if current_chunk:
        chunk_str = "\n\n".join(current_chunk).strip()
        if chunk_str:
            chunks.append(chunk_str)

    # Ensure no empty chunks
    return [c for c in chunks if c.strip()]


def ingest_document(
    session: Session,
    title: str,
    content: str,
    source: str = "manual",
    service_name: str | None = None,
    environment: str | None = None,
    target_chunk_size: int = DEFAULT_TARGET_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> Tuple[KnowledgeDocument, bool]:
    """
    Ingest, chunk, embed, and persist an operational runbook document.

    If a document with the identical content hash already exists, returns the
    existing record without creating duplicate embeddings.

    Parameters
    ----------
    session : Session
        Active database session.
    title : str
        Document title.
    content : str
        Document text.
    source : str
        Provenance label.
    service_name : str | None
        Optional service scoping.
    environment : str | None
        Optional environment scoping.

    Returns
    -------
    Tuple[KnowledgeDocument, bool]
        (document, is_duplicate)
    """
    content_bytes = len(content.encode("utf-8"))
    if content_bytes > MAX_DOCUMENT_BYTES:
        raise ValueError(f"Document size ({content_bytes} bytes) exceeds limit of {MAX_DOCUMENT_BYTES} bytes.")

    content_hash = compute_content_hash(content)

    # Check for existing document with identical content hash
    stmt = (
        select(KnowledgeDocument)
        .where(KnowledgeDocument.content_hash == content_hash)
        .order_by(KnowledgeDocument.created_at.asc())
        .limit(1)
    )
    existing_doc = session.execute(stmt).scalars().first()
    if existing_doc is not None:
        logger.info(
            "Document with content_hash=%s already exists (id=%s). Skipping duplicate ingestion.",
            content_hash[:12],
            existing_doc.id,
        )
        return existing_doc, True

    # Split into bounded chunks
    chunks = chunk_text(content, target_chunk_size=target_chunk_size, chunk_overlap=chunk_overlap)
    if not chunks:
        chunks = [content.strip()]

    # Generate dense vector embeddings in batch
    embed_provider = get_embedding_provider()
    embeddings = embed_provider.embed_batch(chunks)

    doc_id = uuid.uuid4()
    doc = KnowledgeDocument(
        id=doc_id,
        title=title.strip(),
        source=source.strip(),
        content_hash=content_hash,
        service_name=service_name.strip() if service_name else None,
        environment=environment.strip() if environment else None,
        chunk_count=len(chunks),
    )
    session.add(doc)

    for idx, (chunk_content, vector) in enumerate(zip(chunks, embeddings)):
        chunk_hash = compute_content_hash(chunk_content)
        stable_id = f"doc:{doc_id}:chunk:{idx}"
        chunk = KnowledgeChunk(
            id=uuid.uuid4(),
            document_id=doc_id,
            chunk_index=idx,
            stable_chunk_id=stable_id,
            content=chunk_content,
            content_hash=chunk_hash,
            embedding_model=embed_provider.model_name,
            embedding=vector,
        )
        session.add(chunk)

    session.commit()
    session.refresh(doc)

    logger.info(
        "Successfully ingested document id=%s title=%s with %d chunks (model=%s)",
        doc.id,
        doc.title,
        doc.chunk_count,
        embed_provider.model_name,
    )
    return doc, False
