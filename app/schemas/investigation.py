"""
app/schemas/investigation.py — Pydantic schemas for AI-assisted incident investigation.

Milestone 8: Asynchronous AI-assisted incident investigation engine.

Design Decisions
----------------
1. **Strictly Grounded Hypotheses**:
   Every hypothesis must declare a confidence level (HIGH, MEDIUM, LOW) and cite
   specific evidence identifiers (e.g., ``event:<uuid>`` or ``incident:<uuid>``).
2. **Untrusted Evidence Isolation**:
   The schemas represent structured analysis generated from untrusted inputs without
   permitting arbitrary executable commands.
3. **Graceful Uncertainty**:
   Missing telemetry, deployment data, or metrics are explicitly represented via
   ``missing_evidence`` and ``limitations``.
"""

from datetime import datetime
from enum import Enum
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models.investigation import InvestigationStatus


class ConfidenceLevel(str, Enum):
    """Confidence level of an inferred root cause."""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class RootCauseHypothesis(BaseModel):
    """
    A single evidence-grounded hypothesis explaining the root cause.
    """
    model_config = ConfigDict(extra="ignore")

    hypothesis: str = Field(
        ...,
        min_length=5,
        description="Clear, specific technical explanation of what caused the incident.",
    )
    confidence: ConfidenceLevel = Field(
        ...,
        description="Assessed confidence level based solely on available evidence.",
    )
    evidence_references: list[str] = Field(
        ...,
        min_length=1,
        description="List of exact evidence IDs (e.g. 'event:<uuid>') grounding this hypothesis.",
    )
    reasoning: str = Field(
        ...,
        min_length=5,
        description="Step-by-step diagnostic reasoning connecting the cited evidence to this hypothesis.",
    )


# Backward-compatible alias
Hypothesis = RootCauseHypothesis


class RecommendedAction(BaseModel):
    """
    Recommended diagnostic or verification step for on-call engineers.
    """
    model_config = ConfigDict(extra="ignore")

    action: str = Field(
        ...,
        min_length=5,
        description="Specific verification, query, or debugging step to execute.",
    )
    priority: str = Field(
        default="P1",
        pattern="^(P1|P2|P3)$",
        description="Priority level: P1 (immediate), P2 (secondary), P3 (post-mortem).",
    )
    rationale: str = Field(
        ...,
        min_length=5,
        description="Why this diagnostic step should be executed.",
    )


class RetrievedRunbookRef(BaseModel):
    """
    Retrieved operational runbook passage supplied to the LLM as background reference.
    """
    model_config = ConfigDict(extra="ignore")

    chunk_id: str = Field(..., description="Stable chunk identifier (e.g. 'doc:<uuid>:chunk:<idx>').")
    document_title: str = Field(..., description="Title of the source runbook.")
    similarity_score: float = Field(..., description="Cosine similarity score against incident query.")
    snippet: str = Field(..., description="Bounded text excerpt from the runbook passage.")


class InvestigationReport(BaseModel):
    """
    Complete structured investigation report produced by the AI investigation engine.
    """
    model_config = ConfigDict(extra="ignore")

    executive_summary: str = Field(
        ...,
        min_length=10,
        description="High-level overview of the incident, blast radius, and observed pattern.",
    )
    hypotheses: list[RootCauseHypothesis] = Field(
        default_factory=list,
        description="Grounded root-cause hypotheses ranked by confidence.",
    )
    recommended_actions: list[RecommendedAction] = Field(
        default_factory=list,
        description="Prioritized debugging steps for engineers.",
    )
    retrieved_runbooks: list[RetrievedRunbookRef] = Field(
        default_factory=list,
        description="Retrieved runbook passages provided as passive background reference (not active incident telemetry).",
    )
    missing_evidence: list[str] = Field(
        default_factory=list,
        description="Telemetry, logs, or metrics that were unavailable during analysis.",
    )
    limitations: list[str] = Field(
        default_factory=list,
        description="Known bounds and caveats of this automated investigation.",
    )


class InvestigationJobResponse(BaseModel):
    """
    API response schema for GET /api/v1/investigations/{job_id}.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="UUID primary key of the investigation job.")
    incident_id: uuid.UUID = Field(..., description="UUID of the incident being investigated.")
    status: InvestigationStatus = Field(..., description="Lifecycle status: PENDING, PROCESSING, COMPLETED, FAILED.")
    attempt_count: int = Field(..., description="Number of execution attempts.")
    error_message: str | None = Field(default=None, description="Sanitized failure description if any.")
    report: InvestigationReport | None = Field(default=None, description="Structured investigation report if completed.")
    created_at: datetime = Field(..., description="Timestamp when the job was enqueued.")
    updated_at: datetime = Field(..., description="Timestamp when the job status was last updated.")
    completed_at: datetime | None = Field(default=None, description="Timestamp when analysis completed.")


class InvestigationCreateResponse(BaseModel):
    """
    HTTP 202 Accepted response returned by POST /api/v1/incidents/{incident_id}/investigations.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="UUID of the queued investigation job.")
    incident_id: uuid.UUID = Field(..., description="UUID of the target incident.")
    status: InvestigationStatus = Field(default=InvestigationStatus.PENDING, description="Initial status.")
    message: str = Field(
        default="Incident investigation job enqueued for background processing.",
        description="Human-readable confirmation message.",
    )
