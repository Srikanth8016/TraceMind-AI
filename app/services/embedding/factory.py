"""
app/services/embedding/factory.py — Factory registry for embedding providers.

Milestone 9: Runbook ingestion, embeddings, vector retrieval, and RAG integration.
"""

import os
from typing import Optional

from app.services.embedding.base import BaseEmbeddingProvider
from app.services.embedding.http_provider import HTTPEmbeddingProvider
from app.services.embedding.mock_provider import MockEmbeddingProvider

_global_override_embedding_provider: Optional[BaseEmbeddingProvider] = None


def set_embedding_provider_override(provider: Optional[BaseEmbeddingProvider]) -> None:
    """Allow test suites to inject custom or spy embedding providers."""
    global _global_override_embedding_provider
    _global_override_embedding_provider = provider


def get_embedding_provider() -> BaseEmbeddingProvider:
    """
    Instantiate the configured embedding provider according to environment settings.
    """
    if _global_override_embedding_provider is not None:
        return _global_override_embedding_provider

    provider_name = os.getenv("EMBEDDING_PROVIDER", "mock").lower().strip()
    if provider_name in ("http", "openai", "azure", "vllm", "ollama"):
        return HTTPEmbeddingProvider()

    # Default to mock provider for local development, CI, and tests
    return MockEmbeddingProvider()
