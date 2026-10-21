"""
app/schemas/knowledge.py — Pydantic schemas for runbook ingestion and vector retrieval.

Milestone 9: Runbook ingestion, embeddings, vector retrieval, and RAG integration.
"""

from datetime import datetime
import uuid
from pydantic import BaseModel, ConfigDict, Field


class KnowledgeIngestRequest(BaseModel):
    """
    Request schema for ingesting an operational runbook, SOP, or post-mortem.
    """
    model_config = ConfigDict(extra="forbid")

    title: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Descriptive title of the runbook or documentation (e.g. 'Postgres Connection Saturation').",
    )
    content: str = Field(
        ...,
        min_length=10,
        max_length=1_048_576,  # 1 MB maximum document size
        description="Complete text content of the runbook in Markdown or plain text.",
    )
    source: str = Field(
        default="manual",
        max_length=255,
        description="Provenance of the document (e.g. 'wiki:payments', 'file:runbook.md').",
    )
    service_name: str | None = Field(
        default=None,
        max_length=100,
        description="Optional service scoping (e.g. 'payment-service'). If null, globally applicable.",
    )
    environment: str | None = Field(
        default=None,
        max_length=50,
        description="Optional environment scoping (e.g. 'production').",
    )


class KnowledgeChunkResponse(BaseModel):
    """
    Response schema for a single embedded knowledge chunk.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    chunk_index: int
    stable_chunk_id: str
    content: str
    embedding_model: str
    created_at: datetime


class KnowledgeDocumentResponse(BaseModel):
    """
    Response schema for an ingested knowledge document.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    source: str
    content_hash: str
    service_name: str | None
    environment: str | None
    chunk_count: int
    created_at: datetime
    updated_at: datetime
    is_duplicate: bool = False


class KnowledgeSearchRequest(BaseModel):
    """
    Request schema for querying relevant runbook passages via vector similarity.
    """
    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        description="Technical incident description or error query to match against runbooks.",
    )
    top_k: int = Field(
        default=3,
        ge=1,
        le=20,
        description="Maximum number of relevant chunks to retrieve.",
    )
    min_similarity: float = Field(
        default=0.4,
        ge=0.0,
        le=1.0,
        description="Minimum cosine similarity threshold (0.0 to 1.0).",
    )
    service_name: str | None = Field(
        default=None,
        max_length=100,
        description="Optional filter to restrict retrieval to chunks for this service or global runbooks.",
    )


class RetrievedChunkResponse(BaseModel):
    """
    Response schema for a retrieved runbook passage with similarity score.
    """
    model_config = ConfigDict(from_attributes=True)

    chunk_id: str = Field(..., description="Stable chunk identifier (e.g. 'doc:<uuid>:chunk:<idx>').")
    document_id: uuid.UUID = Field(..., description="UUID of the parent document.")
    document_title: str = Field(..., description="Title of the source runbook.")
    source: str = Field(..., description="Source location or origin.")
    service_name: str | None = Field(default=None, description="Associated service if scoped.")
    similarity_score: float = Field(..., description="Cosine similarity score (0.0 to 1.0).")
    content: str = Field(..., description="Passage content text.")
