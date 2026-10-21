"""
app/services/embedding/base.py — Abstract interface for text embedding providers.

Milestone 9: Runbook ingestion, embeddings, vector retrieval, and RAG integration.
"""

from abc import ABC, abstractmethod


class EmbeddingProviderError(Exception):
    """Raised when an embedding provider fails to generate vectors."""
    pass


class BaseEmbeddingProvider(ABC):
    """
    Abstract base class for dense vector embedding models.
    """

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Vector dimensionality produced by this model (e.g. 384)."""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Human-readable identifier of the embedding model."""
        pass

    @abstractmethod
    def embed_text(self, text: str) -> list[float]:
        """Generate a normalized dense vector embedding for a single text passage."""
        pass

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate normalized dense vector embeddings for a batch of text passages."""
        pass
