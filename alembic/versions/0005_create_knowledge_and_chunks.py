"""create knowledge_documents and knowledge_chunks tables with pgvector

Revision ID: 0005_create_knowledge_and_chunks
Revises: 0004_create_investigation_jobs
Create Date: 2026-10-20 19:50:00

Milestone 9: Runbook ingestion, embeddings, vector retrieval, and RAG integration.
"""

import logging
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.models.vector_type import VectorType

# revision identifiers, used by Alembic.
revision: str = "0005_create_knowledge_and_chunks"
down_revision: str | None = "0004_create_investigation_jobs"
branch_labels = None
depends_on = None

logger = logging.getLogger(__name__)


def upgrade() -> None:
    """Create pgvector extension, knowledge_documents, and knowledge_chunks tables."""
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    has_vector_ext = False

    if is_postgres:
        try:
            # Safely check if pgvector is available in this PostgreSQL instance
            check_sql = sa.text("SELECT count(*) FROM pg_available_extensions WHERE name = 'vector';")
            count = bind.execute(check_sql).scalar()
            if count and count > 0:
                op.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                has_vector_ext = True
            else:
                logger.warning(
                    "pgvector extension is not installed in the target PostgreSQL instance. "
                    "Falling back to JSON vector storage. To enable native vector indexes, "
                    "use docker-compose with pgvector/pgvector:pg16."
                )
        except Exception as exc:
            logger.warning("Error checking or creating pgvector extension: %s", exc)
            has_vector_ext = False

    # 1. Create knowledge_documents table
    op.create_table(
        "knowledge_documents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "title",
            sa.String(255),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.String(255),
            nullable=False,
        ),
        sa.Column(
            "content_hash",
            sa.String(64),
            nullable=False,
        ),
        sa.Column(
            "service_name",
            sa.String(100),
            nullable=True,
        ),
        sa.Column(
            "environment",
            sa.String(50),
            nullable=True,
        ),
        sa.Column(
            "chunk_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_knowledge_documents_content_hash",
        "knowledge_documents",
        ["content_hash"],
    )
    op.create_index(
        "ix_knowledge_documents_service_name",
        "knowledge_documents",
        ["service_name"],
    )

    # 2. Create knowledge_chunks table
    embedding_col_type = (
        VectorType(dim=384, use_pgvector=True)
        if has_vector_ext
        else VectorType(dim=384, use_pgvector=False)
    )

    op.create_table(
        "knowledge_chunks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "chunk_index",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "stable_chunk_id",
            sa.String(100),
            nullable=False,
        ),
        sa.Column(
            "content",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "content_hash",
            sa.String(64),
            nullable=False,
        ),
        sa.Column(
            "embedding_model",
            sa.String(100),
            nullable=False,
        ),
        sa.Column(
            "embedding",
            embedding_col_type,
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["knowledge_documents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_knowledge_chunks_document_id",
        "knowledge_chunks",
        ["document_id"],
    )
    op.create_index(
        "ix_knowledge_chunks_content_hash",
        "knowledge_chunks",
        ["content_hash"],
    )
    op.create_index(
        "ix_knowledge_chunks_stable_chunk_id",
        "knowledge_chunks",
        ["stable_chunk_id"],
    )

    # 3. Create HNSW vector index on PostgreSQL only if native pgvector extension is present
    if is_postgres and has_vector_ext:
        try:
            op.execute(
                "CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_embedding_hnsw "
                "ON knowledge_chunks USING hnsw (embedding vector_cosine_ops);"
            )
        except Exception as exc:
            logger.warning("Could not create HNSW index: %s", exc)


def downgrade() -> None:
    """Drop knowledge_chunks and knowledge_documents tables."""
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        try:
            op.execute("DROP INDEX IF EXISTS ix_knowledge_chunks_embedding_hnsw;")
        except Exception:
            pass

    op.drop_index("ix_knowledge_chunks_stable_chunk_id", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_content_hash", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_document_id", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")

    op.drop_index("ix_knowledge_documents_service_name", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_content_hash", table_name="knowledge_documents")
    op.drop_table("knowledge_documents")
