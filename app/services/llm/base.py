"""
app/services/llm/base.py — Abstract base class for LLM providers.

Milestone 8: Asynchronous AI-assisted incident investigation engine.
"""

from abc import ABC, abstractmethod


class LLMProviderError(Exception):
    """Base exception for LLM provider failures (timeouts, network, rate limits)."""
    pass


class BaseLLMProvider(ABC):
    """
    Abstract interface for LLM completion providers.
    """

    @abstractmethod
    def generate_investigation(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """
        Send investigation prompts to the LLM and return raw completion string.

        Parameters
        ----------
        system_prompt : str
            Security guidelines, role, and output JSON schema specifications.
        user_prompt : str
            Structured evidence bundle and query.

        Returns
        -------
        str
            Raw model completion output (expected to be JSON).

        Raises
        ------
        LLMProviderError
            If provider times out, returns HTTP error, or is unreachable.
        """
        pass
