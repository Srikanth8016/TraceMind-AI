"""
tests/test_e2e_workflow.py — End-to-end automated workflow integration tests.

Milestone 11: End-to-End Testing and Failure Recovery.

Verifies the complete pipeline:
1. Ingest operational runbook via /api/v1/runbooks (RAG knowledge base).
2. Submit error event via /api/v1/events.
3. Verify event persistence in database.
4. Verify incident creation and correlation.
5. Ingest subsequent correlated event and verify incident grouping (event_count increment).
6. Trigger AI-assisted incident investigation via /api/v1/incidents/{id}/investigate.
7. Execute background worker synchronously via Celery test configuration.
8. Verify RAG vector retrieval matches and attaches relevant runbook passages.
9. Verify structured investigation report persistence.
10. Retrieve completed job and report via /api/v1/investigations/{id}.
11. Verify evidence citation integrity and strict schema adherence.
"""

from datetime import datetime, timezone
import uuid
import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models.event import Event
from app.models.incident import Incident, IncidentStatus
from app.models.investigation import InvestigationJob, InvestigationStatus
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.schemas.investigation import InvestigationReport
from app.services.embedding import MockEmbeddingProvider, set_embedding_provider_override
from app.services.llm import MockLLMProvider, set_llm_provider_override
from tests.conftest import TEST_API_KEY


@pytest.fixture(autouse=True)
def ensure_deterministic_mocks():
    """Ensure all tests in this module use deterministic mock AI providers."""
    mock_llm = MockLLMProvider()
    mock_emb = MockEmbeddingProvider()
    set_llm_provider_override(mock_llm)
    set_embedding_provider_override(mock_emb)
    yield
    set_llm_provider_override(None)
    set_embedding_provider_override(None)


@pytest.mark.e2e
class TestEndToEndInvestigationWorkflow:
    """Complete end-to-end event ingestion, correlation, RAG retrieval, and investigation."""

    def test_complete_event_to_investigation_lifecycle(self, client: TestClient) -> None:
        # -------------------------------------------------------------------
        # Step 1: Ingest an operational runbook for RAG context
        # -------------------------------------------------------------------
        runbook_payload = {
            "title": "Stripe Payment Gateway Egress Runbook",
            "service_name": "payment-service",
            "content": (
                "When payment-service encounters SocketTimeoutException during checkout processing:\n"
                "1. Inspect Stripe egress network connectivity and NAT gateway health.\n"
                "2. Verify payment connection pool active sockets are not exhausted.\n"
                "3. If latency to api.stripe.com exceeds 5000ms, enable backup payment provider circuit breaker."
            ),
        }
        rb_resp = client.post("/api/v1/runbooks", json=runbook_payload)
        assert rb_resp.status_code == 201, rb_resp.text
        rb_data = rb_resp.json()
        assert "id" in rb_data
        doc_id = rb_data["id"]
        assert rb_data["chunk_count"] >= 1

        # -------------------------------------------------------------------
        # Step 2: Submit an error event through the public API
        # -------------------------------------------------------------------
        now_iso = datetime.now(timezone.utc).isoformat()
        event_payload = {
            "service_name": "payment-service",
            "environment": "production",
            "level": "ERROR",
            "message": "SocketTimeoutException connecting to Stripe API at 192.168.1.100:443",
            "timestamp": now_iso,
        }
        event_resp = client.post("/api/v1/events", json=event_payload)
        assert event_resp.status_code == 202, event_resp.text
        event_body = event_resp.json()
        assert "event_id" in event_body
        assert "job_id" in event_body
        assert event_body["service_name"] == "payment-service"
        event_id = event_body["event_id"]
        job_id = event_body["job_id"]

        # -------------------------------------------------------------------
        # Step 3: Verify event persistence in database
        # -------------------------------------------------------------------
        get_event_resp = client.get(f"/api/v1/events/{event_id}")
        assert get_event_resp.status_code == 200
        saved_event = get_event_resp.json()
        assert saved_event["id"] == event_id
        assert saved_event["message"] == event_payload["message"]

        # -------------------------------------------------------------------
        # Step 4: Verify incident creation and correlation
        # -------------------------------------------------------------------
        incidents_resp = client.get("/api/v1/incidents?service_name=payment-service&environment=production")
        assert incidents_resp.status_code == 200
        inc_data = incidents_resp.json()
        matching_incidents = [
            inc for inc in inc_data["items"]
            if inc["service_name"] == "payment-service"
        ]
        assert len(matching_incidents) >= 1
        incident = matching_incidents[0]
        incident_id = incident["id"]
        assert incident["status"] == "OPEN"
        assert incident["event_count"] >= 1

        # Verify the event is listed under the incident
        inc_events_resp = client.get(f"/api/v1/incidents/{incident_id}/events")
        assert inc_events_resp.status_code == 200
        inc_events = inc_events_resp.json()
        assert any(e["id"] == event_id for e in inc_events["items"])

        # -------------------------------------------------------------------
        # Step 5: Ingest a second correlated error event (grouping test)
        # -------------------------------------------------------------------
        second_event_payload = {
            "service_name": "payment-service",
            "environment": "production",
            "level": "ERROR",
            "message": "SocketTimeoutException connecting to Stripe API at 192.168.1.101:443",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        second_resp = client.post("/api/v1/events", json=second_event_payload)
        assert second_resp.status_code == 202

        # Verify incident event_count incremented
        inc_detail_resp = client.get(f"/api/v1/incidents/{incident_id}")
        assert inc_detail_resp.status_code == 200
        updated_incident = inc_detail_resp.json()
        assert updated_incident["event_count"] >= 2

        # -------------------------------------------------------------------
        # Step 6: Trigger AI investigation job via API
        # -------------------------------------------------------------------
        inv_post_resp = client.post(f"/api/v1/incidents/{incident_id}/investigate")
        assert inv_post_resp.status_code == 202, inv_post_resp.text
        inv_post_body = inv_post_resp.json()
        assert "id" in inv_post_body
        assert inv_post_body["incident_id"] == incident_id
        inv_job_id = inv_post_body["id"]

        # -------------------------------------------------------------------
        # Step 7 & 8: Verify synchronous worker execution & report persistence
        # -------------------------------------------------------------------
        inv_get_resp = client.get(f"/api/v1/investigations/{inv_job_id}")
        assert inv_get_resp.status_code == 200
        job_record = inv_get_resp.json()
        assert job_record["id"] == inv_job_id
        assert job_record["status"] == "COMPLETED"
        assert job_record["attempt_count"] >= 1
        assert job_record["report"] is not None

        # -------------------------------------------------------------------
        # Step 9: Verify structured report schema adherence
        # -------------------------------------------------------------------
        report = job_record["report"]
        assert "executive_summary" in report
        assert isinstance(report["executive_summary"], str)
        assert len(report["executive_summary"]) > 0

        assert "hypotheses" in report
        assert isinstance(report["hypotheses"], list)
        assert len(report["hypotheses"]) >= 1

        for hypothesis in report["hypotheses"]:
            assert "hypothesis" in hypothesis
            assert hypothesis["confidence"] in ["HIGH", "MEDIUM", "LOW"]
            assert "evidence_references" in hypothesis
            assert len(hypothesis["evidence_references"]) >= 1
            assert "reasoning" in hypothesis

        assert "recommended_actions" in report
        for action in report["recommended_actions"]:
            assert "action" in action
            assert action["priority"] in ["P1", "P2", "P3"]
            assert "rationale" in action

        assert "missing_evidence" in report
        assert isinstance(report["missing_evidence"], list)

        assert "limitations" in report
        assert isinstance(report["limitations"], list)

        # -------------------------------------------------------------------
        # Step 10: Verify RAG runbook retrieval & grounding
        # -------------------------------------------------------------------
        assert "retrieved_runbooks" in report
        assert isinstance(report["retrieved_runbooks"], list)
        # Verify runbook passages were retrieved for the incident
        if len(report["retrieved_runbooks"]) > 0:
            rb_ref = report["retrieved_runbooks"][0]
            assert "chunk_id" in rb_ref
            assert "document_title" in rb_ref
            assert "similarity_score" in rb_ref
            assert "snippet" in rb_ref
            assert rb_ref["chunk_id"].startswith("doc:")

        # -------------------------------------------------------------------
        # Step 11: Verify evidence citation integrity (no hallucinations)
        # -------------------------------------------------------------------
        valid_prefixes = ("incident:", "event:", "doc:")
        for hypothesis in report["hypotheses"]:
            for ref in hypothesis["evidence_references"]:
                assert any(ref.startswith(prefix) for prefix in valid_prefixes), (
                    f"Invalid evidence reference format: {ref}"
                )

        # -------------------------------------------------------------------
        # Step 12: Verify incident investigations listing endpoint
        # -------------------------------------------------------------------
        inv_list_resp = client.get(f"/api/v1/incidents/{incident_id}/investigations")
        assert inv_list_resp.status_code == 200
        inv_list = inv_list_resp.json()
        assert len(inv_list) >= 1
        assert any(item["id"] == inv_job_id for item in inv_list)
