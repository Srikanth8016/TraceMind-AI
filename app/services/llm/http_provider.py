"""
app/services/llm/http_provider.py — Generic OpenAI-compatible HTTP LLM provider using httpx.

Milestone 8: Asynchronous AI-assisted incident investigation engine.
"""

import logging
import os

import httpx

from app.services.llm.base import BaseLLMProvider, LLMProviderError

logger = logging.getLogger(__name__)


class HTTPLLMProvider(BaseLLMProvider):
    """
    Standard HTTP provider compatible with OpenAI, Azure OpenAI, vLLM, Ollama, and Gemini.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 30.0,
    ):
        self.api_key = api_key or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
        self.base_url = (
            base_url
            or os.getenv("LLM_BASE_URL")
            or "https://api.openai.com/v1"
        ).rstrip("/")
        self.model = model or os.getenv("LLM_MODEL") or "gpt-4o-mini"
        self.timeout = timeout

        if not self.api_key and "localhost" not in self.base_url and "127.0.0.1" not in self.base_url:
            logger.warning("HTTPLLMProvider initialized without an API key.")

    def generate_investigation(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,  # Low temperature for deterministic diagnostic reasoning
        }

        url = f"{self.base_url}/chat/completions"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                return content
        except httpx.TimeoutException as exc:
            logger.error("LLM provider timed out after %s seconds", self.timeout)
            raise LLMProviderError(f"LLM request timed out after {self.timeout}s") from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            logger.error("LLM upstream returned HTTP error %d", status)
            raise LLMProviderError(f"LLM upstream error (HTTP {status})") from exc
        except Exception as exc:
            logger.error("Unexpected LLM communication failure: %s", type(exc).__name__)
            raise LLMProviderError(f"LLM provider connection failed: {exc}") from exc
