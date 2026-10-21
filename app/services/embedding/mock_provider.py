"""
app/services/embedding/mock_provider.py — Deterministic, offline embedding provider for tests.

Milestone 9: Runbook ingestion, embeddings, vector retrieval, and RAG integration.

Design Decisions
----------------
1. **Zero External Dependencies**:
   Uses standard library `hashlib`, `math`, and `re`. Requires no PyTorch, sentence-transformers,
   or network calls.
2. **Deterministic & Unit-Normalized**:
   The resulting vector is strictly L2-normalized (length = 1.0). Identical strings produce
   identical float vectors.
3. **Pseudo-Semantic Alignment**:
   Tokens are hashed into 384 dimensions with positive/negative signed weights. Passages
   sharing terminology exhibit high cosine similarity (>0.6), while unrelated passages exhibit
   near-zero or low similarity (<0.3).
"""

import hashlib
import math
import re
from typing import List

from app.services.embedding.base import BaseEmbeddingProvider


class MockEmbeddingProvider(BaseEmbeddingProvider):
    """
    Deterministic pseudo-semantic embedding provider producing unit-normalized 384-d vectors.
    """

    def __init__(self, dimension: int = 384):
        self._dim = dimension
        self._model_name = f"mock-embed-{dimension}"

    @property
    def dimension(self) -> int:
        return self._dim

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed_text(self, text: str) -> List[float]:
        """
        Generate a unit-normalized deterministic embedding vector.
        """
        vector = [0.0] * self._dim
        tokens = re.findall(r"\w+", text.lower())

        if not tokens:
            # Return baseline unit vector along first dimension
            vector[0] = 1.0
            return vector

        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            # Generate 4 feature projections per token
            for i in range(4):
                idx = int.from_bytes(digest[i * 4 : i * 4 + 2], "big") % self._dim
                sign = 1.0 if digest[i * 4 + 2] % 2 == 0 else -1.0
                weight = 1.0 + (digest[i * 4 + 3] / 255.0)
                vector[idx] += sign * weight

        # L2-normalize the vector
        norm = math.sqrt(sum(x * x for x in vector))
        if norm > 1e-12:
            vector = [x / norm for x in vector]
        else:
            vector[0] = 1.0

        return vector

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Embed a list of text passages.
        """
        return [self.embed_text(t) for t in texts]
