"""
app/services/embedding/http_provider.py — OpenAI-compatible HTTP embedding provider using httpx.

Milestone 9: Runbook ingestion, embeddings, vector retrieval, and RAG integration.
"""

import logging
import math
import os
from typing import List

import httpx

from app.services.embedding.base import BaseEmbeddingProvider, EmbeddingProviderError

logger = logging.getLogger(__name__)


class HTTPEmbeddingProvider(BaseEmbeddingProvider):
    """
    HTTP provider for generating dense vector embeddings via any OpenAI-compatible API
    (OpenAI, Ollama, Azure, TEI, vLLM).
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        dimension: int = 384,
        timeout: float = 30.0,
    ):
        self.api_key = (
            api_key
            or os.getenv("EMBEDDING_API_KEY")
            or os.getenv("LLM_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or ""
        )
        self.base_url = (
            base_url
            or os.getenv("EMBEDDING_BASE_URL")
            or os.getenv("LLM_BASE_URL")
            or "https://api.openai.com/v1"
        ).rstrip("/")
        self.model = (
            model
            or os.getenv("EMBEDDING_MODEL")
            or "text-embedding-3-small"
        )
        self._dim = dimension
        self.timeout = timeout

    @property
    def dimension(self) -> int:
        return self._dim

    @property
    def model_name(self) -> str:
        return self.model

    def _normalize(self, vector: List[float]) -> List[float]:
        norm = math.sqrt(sum(x * x for x in vector))
        if norm > 1e-12:
            return [x / norm for x in vector]
        return vector

    def embed_text(self, text: str) -> List[float]:
        results = self.embed_batch([text])
        if not results:
            raise EmbeddingProviderError("Embedding provider returned empty response.")
        return results[0]

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "input": texts,
        }
        # If model supports dimensions parameter (e.g. text-embedding-3-small)
        if "text-embedding-3" in self.model:
            payload["dimensions"] = self._dim

        url = f"{self.base_url}/embeddings"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                items = data.get("data", [])
                # Ensure ordered by index
                items.sort(key=lambda x: x.get("index", 0))
                return [self._normalize(item["embedding"][: self._dim]) for item in items]
        except httpx.TimeoutException as exc:
            logger.error("Embedding provider timed out after %s seconds", self.timeout)
            raise EmbeddingProviderError(f"Embedding request timed out after {self.timeout}s") from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            logger.error("Embedding upstream returned HTTP error %d", status)
            raise EmbeddingProviderError(f"Embedding upstream error (HTTP {status})") from exc
        except Exception as exc:
            logger.error("Embedding provider communication failure: %s", type(exc).__name__)
            raise EmbeddingProviderError(f"Embedding provider communication failed: {exc}") from exc
