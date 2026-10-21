"""
app/services/llm/factory.py — LLM provider factory and registry.

Milestone 8: Asynchronous AI-assisted incident investigation engine.
"""

import os
from typing import Optional

from app.services.llm.base import BaseLLMProvider
from app.services.llm.http_provider import HTTPLLMProvider
from app.services.llm.mock_provider import MockLLMProvider

_global_override_provider: Optional[BaseLLMProvider] = None


def set_llm_provider_override(provider: Optional[BaseLLMProvider]) -> None:
    """Allow test suites to inject custom mock or spy LLM providers."""
    global _global_override_provider
    _global_override_provider = provider


def get_llm_provider() -> BaseLLMProvider:
    """
    Instantiate the configured LLM provider according to environment settings.
    """
    if _global_override_provider is not None:
        return _global_override_provider

    provider_name = os.getenv("LLM_PROVIDER", "mock").lower().strip()
    if provider_name in ("groq", "http", "openai", "azure", "vllm"):
        return HTTPLLMProvider()

    # Default to mock provider for local development and tests without API keys
    return MockLLMProvider()
