"""
tests/test_unit_suite.py — Fast, isolated in-memory unit tests.

Milestone 11: End-to-End Testing and Failure Recovery.

Verifies:
1. Event validation, timezone checks, and schema normalization.
2. Fingerprint stability and dynamic token masking (UUIDs, IPs, memory addresses).
3. Incident title extraction and sanitization.
4. Investigation report Pydantic schema validation.
5. Strict evidence citation verification (hallucination rejection).
6. LLM JSON output cleaning and markdown fence stripping.
7. RAG text chunking, overlap windows, and content hashing.
8. Secret and credential redaction filters.
"""

from datetime import datetime, timezone
import pytest

from app.logging_config import redact_sensitive_text
from app.schemas.event import EventCreate, SeverityLevel
from app.schemas.investigation import (
    ConfidenceLevel,
    InvestigationReport,
    RecommendedAction,
    RootCauseHypothesis,
)
from app.services.fingerprint import (
    extract_incident_title,
    generate_fingerprint,
    normalize_error_message,
)
from app.services.investigation import (
    clean_llm_json_output,
    validate_evidence_citations,
)
from app.services.knowledge import chunk_text, compute_content_hash


@pytest.mark.unit
class TestEventValidationUnit:
    """Verifies event schema validation, timezone enforcement, and normalization."""

    def test_utc_timezone_validation_success(self) -> None:
        payload = EventCreate(
            service_name="auth-service",
            environment="production",
            level=SeverityLevel.ERROR,
            message="Token verification failed",
            timestamp=datetime.now(timezone.utc),
        )
        payload.validate_timezone()
        assert payload.service_name == "auth-service"

    def test_naive_datetime_rejected(self) -> None:
        naive_dt = datetime.now()  # naive datetime without tzinfo
        payload = EventCreate(
            service_name="auth-service",
            environment="production",
            level=SeverityLevel.ERROR,
            message="Token verification failed",
            timestamp=naive_dt,
        )
        with pytest.raises(ValueError, match="timezone-aware"):
            payload.validate_timezone()


@pytest.mark.unit
class TestFingerprintAndNormalizationUnit:
    """Verifies normalization of dynamic tokens and stability of fingerprints."""

    def test_masks_dynamic_tokens_in_error_message(self) -> None:
        raw_msg = (
            "NullPointerException at 0x7fff5fbff8a0 in PaymentProcessor "
            "connecting to 192.168.1.42 for transaction 550e8400-e29b-41d4-a716-446655440000"
        )
        normalized = normalize_error_message(raw_msg)
        assert "<HEX>" in normalized
        assert "<IP>" in normalized
        assert "<UUID>" in normalized
        assert "550e8400" not in normalized
        assert "192.168.1.42" not in normalized

    def test_fingerprint_stability_across_variable_instances(self) -> None:
        msg1 = "Connection failed to 10.0.0.1:5432 for session 11111111-1111-1111-1111-111111111111"
        msg2 = "Connection failed to 10.0.0.2:5432 for session 22222222-2222-2222-2222-222222222222"

        fp1 = generate_fingerprint("db-service", "production", msg1)
        fp2 = generate_fingerprint("db-service", "production", msg2)

        assert fp1 == fp2, "Fingerprints must match across dynamic IPs and UUIDs"

    def test_title_extraction_truncation(self) -> None:
        long_msg = "Critical database failure: " + "a" * 200
        title = extract_incident_title(long_msg, max_length=120)
        assert len(title) <= 123
        assert title.endswith("...")


@pytest.mark.unit
class TestInvestigationReportValidationUnit:
    """Verifies report schema constraints, citation verification, and JSON cleaning."""

    def test_clean_llm_json_output_strips_markdown_code_fences(self) -> None:
        wrapped_json = (
            "```json\n"
            '{\n  "executive_summary": "System degraded",\n  "hypotheses": []\n}\n'
            "```"
        )
        cleaned = clean_llm_json_output(wrapped_json)
        assert cleaned.startswith("{")
        assert cleaned.endswith("}")
        assert "```" not in cleaned

    def test_validate_evidence_citations_accepts_valid_references(self) -> None:
        report = InvestigationReport(
            executive_summary="Detailed executive summary of the production incident",
            hypotheses=[
                RootCauseHypothesis(
                    hypothesis="Root cause is database pool exhaustion",
                    confidence=ConfidenceLevel.HIGH,
                    evidence_references=["incident:abc-123", "event:evt-456"],
                    reasoning="Logs confirm timeout",
                )
            ],
            recommended_actions=[
                RecommendedAction(
                    action="Increase pool size",
                    priority="P1",
                    rationale="Mitigates connection exhaustion",
                )
            ],
            missing_evidence=[],
            limitations=[],
        )
        valid_ids = {"incident:abc-123", "event:evt-456", "doc:doc-1:chunk:0"}
        # Must pass without raising
        validate_evidence_citations(report, valid_ids)

    def test_validate_evidence_citations_rejects_hallucinated_reference(self) -> None:
        report = InvestigationReport(
            executive_summary="Detailed executive summary of the production incident",
            hypotheses=[
                RootCauseHypothesis(
                    hypothesis="Root cause is network glitch",
                    confidence=ConfidenceLevel.LOW,
                    evidence_references=["event:non-existent-uuid"],
                    reasoning="Unfounded guess",
                )
            ],
            recommended_actions=[],
            missing_evidence=[],
            limitations=[],
        )
        valid_ids = {"incident:abc-123", "event:evt-456"}
        with pytest.raises(ValueError, match="unsupported/hallucinated"):
            validate_evidence_citations(report, valid_ids)

    def test_validate_evidence_citations_rejects_empty_references(self) -> None:
        report = InvestigationReport.model_construct(
            executive_summary="Detailed executive summary of the production incident",
            hypotheses=[
                RootCauseHypothesis.model_construct(
                    hypothesis="Hypothesis without citations",
                    confidence=ConfidenceLevel.LOW,
                    evidence_references=[],
                    reasoning="No evidence cited",
                )
            ],
            recommended_actions=[],
            missing_evidence=[],
            limitations=[],
        )
        with pytest.raises(ValueError, match="empty evidence_references"):
            validate_evidence_citations(report, {"incident:abc-123"})


@pytest.mark.unit
class TestKnowledgeChunkingUnit:
    """Verifies chunking boundary splitting, overlap, and content hashing."""

    def test_chunking_preserves_short_content(self) -> None:
        text = "Operational guide for redis eviction."
        chunks = chunk_text(text, target_chunk_size=500, chunk_overlap=100)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_chunk_text_empty_input(self) -> None:
        assert chunk_text("") == []
        assert chunk_text("   \n\t  ") == []

    def test_content_hash_deterministic(self) -> None:
        text = "Standard Operating Procedure: Restarting Worker Nodes"
        h1 = compute_content_hash(text)
        h2 = compute_content_hash(text)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex string


@pytest.mark.unit
class TestSecretRedactionUnit:
    """Verifies sanitization of credentials and API keys."""

    def test_redacts_groq_and_openai_keys(self) -> None:
        text = "Key: gsk_123456789012345678901234567890abcdef and token sk-123456789012345678901234"
        redacted = redact_sensitive_text(text)
        assert "[REDACTED_GROQ_KEY]" in redacted
        assert "[REDACTED_API_KEY]" in redacted
        assert "gsk_12345" not in redacted
        assert "sk-12345" not in redacted
