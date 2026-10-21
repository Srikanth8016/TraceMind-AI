"""
app/services/embedding — Embedding provider abstraction module.

Milestone 9: Runbook ingestion, embeddings, vector retrieval, and RAG integration.
"""

from app.services.embedding.base import BaseEmbeddingProvider, EmbeddingProviderError
from app.services.embedding.factory import get_embedding_provider, set_embedding_provider_override
from app.services.embedding.http_provider import HTTPEmbeddingProvider
from app.services.embedding.mock_provider import MockEmbeddingProvider

__all__ = [
    "BaseEmbeddingProvider",
    "EmbeddingProviderError",
    "HTTPEmbeddingProvider",
    "MockEmbeddingProvider",
    "get_embedding_provider",
    "set_embedding_provider_override",
]
