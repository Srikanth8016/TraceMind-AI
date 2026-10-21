"""
app/services/llm/mock_provider.py — Deterministic mock LLM provider for hermetic testing.

Milestone 8: Asynchronous AI-assisted incident investigation engine.
"""

import json
import re

from app.services.llm.base import BaseLLMProvider, LLMProviderError


class MockLLMProvider(BaseLLMProvider):
    """
    Deterministic mock provider that extracts supplied evidence IDs from the prompt
    and synthesizes a well-formed, grounded investigation report.
    """

    def __init__(self, mode: str = "normal"):
        """
        Parameters
        ----------
        mode : str
            One of:
            - 'normal': produces valid JSON citing actual evidence IDs.
            - 'malformed_json': returns corrupted non-JSON text.
            - 'unsupported_evidence': cites non-existent/hallucinated evidence IDs.
            - 'timeout': simulates network/provider timeout.
            - 'error': simulates provider 500 error.
        """
        self.mode = mode

    def generate_investigation(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        if self.mode == "timeout":
            raise LLMProviderError("LLM provider request timed out after 30.0s")
        if self.mode == "error":
            raise LLMProviderError("LLM provider upstream HTTP 500 Internal Server Error")
        if self.mode == "malformed_json":
            return "This is clearly not a JSON response {{{ broken syntax ..."

        # Extract available evidence IDs from the prompt
        found_ids = re.findall(
            r'id="(incident:[a-f0-9\-]+|event:[a-f0-9\-]+|doc:[a-f0-9\-]+:chunk:\d+)"',
            user_prompt,
        )
        if not found_ids:
            found_ids = ["incident:default-id"]

        if self.mode == "unsupported_evidence":
            # Intentionally inject hallucinated citations
            cited_ids = ["event:non-existent-hallucinated-uuid-999"]
        else:
            cited_ids = found_ids[:2]

        report_data = {
            "executive_summary": (
                "Automated investigation observed correlated failure events indicating "
                "downstream gateway connectivity timeouts or resource exhaustion."
            ),
            "hypotheses": [
                {
                    "hypothesis": "Downstream payment gateway or dependency timeout during transaction processing.",
                    "confidence": "HIGH" if len(found_ids) > 1 else "MEDIUM",
                    "evidence_references": cited_ids,
                    "reasoning": (
                        f"Cited evidence {cited_ids} indicates repeated timeout exceptions "
                        "occurring within a narrow operational time window."
                    ),
                }
            ],
            "recommended_actions": [
                {
                    "action": "Inspect gateway health and network latency metrics to downstream endpoints.",
                    "priority": "P1",
                    "rationale": "Verify whether the third-party gateway experienced downtime or rate limiting.",
                },
                {
                    "action": "Check connection pool saturation and timeout thresholds in application configuration.",
                    "priority": "P2",
                    "rationale": "Prevent connection backlog cascading into thread exhaustion.",
                },
            ],
            "missing_evidence": [
                "Deployment history was unavailable; cannot confirm if recent release introduced the regression.",
                "Container memory and CPU telemetry were unavailable.",
            ],
            "limitations": [
                "Analysis is restricted strictly to ingested event log messages.",
                "Distributed trace spans and APM flame graphs were not provided.",
            ],
        }

        return json.dumps(report_data, indent=2)
