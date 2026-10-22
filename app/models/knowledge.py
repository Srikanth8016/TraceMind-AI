"""
app/models/knowledge.py — SQLAlchemy ORM models for operational runbooks and vector chunks.

Milestone 9: Runbook ingestion, embeddings, vector retrieval, and RAG integration.

Design Decisions
----------------
1. **Document & Chunk Separation**:
   Documents hold source-level provenance, content hash (for idempotency and deduplication),
   and optional service/environment scoping. Chunks hold bounded passages and vector embeddings.
2. **Stable Identifiers**:
   Each chunk has a human- and machine-readable `stable_chunk_id` (e.g. ``doc:<uuid>:chunk:<idx>``)
   that the AI investigation engine cites in its diagnostic hypotheses.
3. **Deduplication by Content Hash**:
   The SHA-256 hash of the complete document content prevents duplicate storage and avoids
   redundant re-embedding API calls.
4. **Vector Storage**:
   Vector embeddings are stored using ``VectorType(dim=384)``, mapping to PostgreSQL ``vector(384)``
   or SQLite JSON.
"""

from datetime import datetime, timezone
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.vector_type import VectorType


class KnowledgeDocument(Base):
    """
    ORM model representing an ingested operational runbook, post-mortem, or SOP document.
    """
    __tablename__ = "knowledge_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
        default=uuid.uuid4,
    )

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    source: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )

    service_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )

    environment: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    chunk_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    chunks = relationship(
        "KnowledgeChunk",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="KnowledgeChunk.chunk_index",
    )

    def __repr__(self) -> str:
        return f"<KnowledgeDocument id={self.id!s} title={self.title!r} chunks={self.chunk_count}>"


class KnowledgeChunk(Base):
    """
    ORM model representing a bounded, overlapping passage from a KnowledgeDocument
    with its dense vector embedding.
    """
    __tablename__ = "knowledge_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
        default=uuid.uuid4,
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    chunk_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    stable_chunk_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )

    embedding_model: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    embedding: Mapped[list[float]] = mapped_column(
        VectorType(dim=384),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    document = relationship("KnowledgeDocument", back_populates="chunks")

    def __repr__(self) -> str:
        return f"<KnowledgeChunk id={self.id!s} stable_id={self.stable_chunk_id!r} doc_id={self.document_id!s}>"
