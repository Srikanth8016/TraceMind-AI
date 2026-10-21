"""
app/models/vector_type.py — Dialect-agnostic vector storage type for SQLAlchemy.

Milestone 9: Runbook ingestion, embeddings, vector retrieval, and RAG integration.

Design Decisions
----------------
1. **PostgreSQL Compatibility**:
   Maps to PostgreSQL's native `vector(dim)` extension type when pgvector is present.
   If pgvector is not available in the database, falls back seamlessly to JSON.
2. **SQLite Compatibility (Pytest)**:
   In SQLite (used in the unit test suite), maps to JSON, serializing/deserializing
   vectors as JSON arrays so tests run 100% offline in-memory without external DB engines.
"""

import json
import logging
from typing import Any, List, Optional
import sqlalchemy as sa
from sqlalchemy.types import JSON, TypeDecorator, UserDefinedType

logger = logging.getLogger(__name__)

try:
    from pgvector.sqlalchemy import Vector as PgVector
except ImportError:
    PgVector = None


class _RawPgVectorUDT(UserDefinedType):
    """Fallback UserDefinedType compiling to vector(dim) in PostgreSQL SQL DDL."""
    cache_ok = True

    def __init__(self, dim: int = 384):
        self.dim = dim

    def get_col_spec(self, **kw: Any) -> str:
        return f"vector({self.dim})"


class VectorType(TypeDecorator):
    """
    SQLAlchemy type decorator for vector embeddings.
    """
    impl = JSON
    cache_ok = True

    def __init__(self, dim: int = 384, use_pgvector: bool = True, **kwargs: Any):
        super().__init__(**kwargs)
        self.dim = dim
        self.use_pgvector = use_pgvector

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql" and self.use_pgvector:
            if PgVector is not None:
                return dialect.type_descriptor(PgVector(self.dim))
            return dialect.type_descriptor(_RawPgVectorUDT(self.dim))
        # SQLite, test dialects, or PostgreSQL without pgvector extension
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: Optional[Any], dialect: Any) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql" and self.use_pgvector:
            if PgVector is not None:
                return value
            if isinstance(value, (list, tuple)):
                return f"[{','.join(str(float(x)) for x in value)}]"
            return str(value)
        if isinstance(value, (list, tuple)):
            return [float(x) for x in value]
        return list(value)

    def process_result_value(self, value: Any, dialect: Any) -> Optional[List[float]]:
        if value is None:
            return None
        if isinstance(value, str):
            try:
                cleaned = value.strip("[] \t\r\n")
                if not cleaned:
                    return []
                return [float(x.strip()) for x in cleaned.split(",") if x.strip()]
            except Exception:
                try:
                    return json.loads(value)
                except Exception:
                    return []
        if isinstance(value, (list, tuple)):
            return [float(x) for x in value]
        if hasattr(value, "tolist"):
            return value.tolist()
        return list(value)
