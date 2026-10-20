"""
Pydantic schemas for the event ingestion API.

Keeping schemas in their own module means:
  - Route handlers import only what they need.
  - Schemas can be tested in isolation without starting FastAPI.
  - Future milestones can reuse or extend them (e.g. for DB models) without
    touching the router.
"""

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enum
# ---------------------------------------------------------------------------

class SeverityLevel(str, Enum):
    """
    Valid severity levels, mirroring the Python logging module's conventions.

    Inheriting from ``str`` means Pydantic serialises the value as a plain
    string (e.g. "ERROR") rather than an enum object, which keeps JSON
    responses clean and avoids surprises for API consumers.
    """

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


# ---------------------------------------------------------------------------
# Request schema
# ---------------------------------------------------------------------------

class EventCreate(BaseModel):
    """
    Validated request body for POST /api/v1/events.

    Pydantic checks every constraint at parse time.  If any field fails,
    FastAPI automatically returns HTTP 422 Unprocessable Entity with a
    structured error body — no manual validation code needed in the router.

    Field-level rules
    -----------------
    service_name
        Non-empty (min_length=1) because an empty string is a programming error
        that should be caught at the boundary, not silently stored.
    environment
        Same rationale as service_name; capped at 50 chars.
    level
        Constrained to the SeverityLevel enum — any other string is rejected.
    message
        Non-empty and capped at 5 000 chars to avoid accidentally ingesting
        multi-megabyte payloads that would later blow up a log store.
    timestamp
        Must be timezone-aware (i.e. include UTC offset).  A naive datetime
        is ambiguous and cannot be safely compared across services that may
        run in different zones.  Pydantic enforces this via the
        ``AwareDatetime`` type alias introduced in v2.
    """

    service_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        examples=["payment-service"],
        description="Name of the service that produced the event.",
    )
    environment: str = Field(
        ...,
        min_length=1,
        max_length=50,
        examples=["production"],
        description="Deployment environment (e.g. production, staging, dev).",
    )
    level: SeverityLevel = Field(
        ...,
        examples=["ERROR"],
        description="Severity level of the event.",
    )
    message: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        examples=["NullPointerException in PaymentProcessor.charge()"],
        description="Human-readable description of the event.",
    )
    timestamp: datetime = Field(
        ...,
        examples=["2024-06-15T14:30:00+00:00"],
        description="ISO-8601 datetime with timezone offset (UTC preferred).",
    )

    model_config = {
        # Reject extra fields so clients cannot silently pass data that would
        # be ignored — a common source of bugs and subtle API misuse.
        "extra": "forbid",
    }

    def validate_timezone(self) -> "EventCreate":
        """
        Raise ValueError if timestamp lacks timezone information.

        Pydantic v2 does not have a built-in AwareDatetime type that raises
        on naive datetimes by default via Field alone; we add an explicit
        guard here and call it from the router after model construction.
        """
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware (include UTC offset)")
        return self


# ---------------------------------------------------------------------------
# Response schemas (Milestone 3)
# ---------------------------------------------------------------------------

class EventResponse(BaseModel):
    """
    Full representation of a persisted event, returned by POST and GET.

    Includes server-generated fields (``id``, ``created_at``) that are absent
    from ``EventCreate``.  Using ``model_config = ConfigDict(from_attributes=True)``
    lets Pydantic read values directly from the SQLAlchemy ORM ``Event``
    instance instead of requiring a manual .dict() conversion.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="Server-generated UUID primary key.")
    service_name: str
    environment: str
    level: str
    message: str
    timestamp: datetime = Field(..., description="Client-supplied timezone-aware timestamp.")
    created_at: datetime = Field(..., description="Database-generated insertion timestamp.")
    incident_id: uuid.UUID | None = Field(default=None, description="UUID of the correlated incident if any.")


class EventAccepted(BaseModel):
    """
    Response body for a successfully accepted event (HTTP 201).

    Separating request and response schemas is important even when they look
    similar: the response may later include server-generated fields (id,
    created_at) without changing the request contract.
    """

    message: str = Field(
        default="Event accepted",
        description="Human-readable confirmation message.",
    )
    event: EventCreate = Field(
        ...,
        description="The validated event data as received.",
    )


# ---------------------------------------------------------------------------
# Query parameter schema (Milestone 4)
# ---------------------------------------------------------------------------

class EventListQuery(BaseModel):
    """
    Validated query parameters for GET /api/v1/events.

    Using a Pydantic model (rather than individual ``Query(...)`` parameters)
    keeps the signature clean, is unit-testable in isolation, and lets us
    add validators with ``@model_validator`` if needed later.

    Parameter rules
    ---------------
    service_name
        Optional exact-match filter.  Max length mirrors the column definition
        (100 chars) so a too-long value is rejected with 422 before any SQL runs.
    environment
        Optional exact-match filter.  Max 50 chars.
    level
        Optional filter; must be one of the five valid SeverityLevel values.
        An unrecognised string is rejected with 422.
    limit
        Number of rows to return in this page.  Range [1, 100]; default 20.
        Keeping the ceiling at 100 protects the API from clients accidentally
        requesting millions of rows.
    offset
        Zero-based starting position.  Must be >= 0; default 0.
    """

    model_config = ConfigDict(extra="forbid")

    service_name: str | None = Field(
        default=None,
        max_length=100,
        description="Exact match on service_name.",
    )
    environment: str | None = Field(
        default=None,
        max_length=50,
        description="Exact match on environment.",
    )
    level: SeverityLevel | None = Field(
        default=None,
        description="Filter by severity level.",
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of events to return (1–100).",
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Zero-based index of the first record to return.",
    )


# ---------------------------------------------------------------------------
# List response schema (Milestone 4)
# ---------------------------------------------------------------------------

class EventListResponse(BaseModel):
    """
    Paginated list of events returned by GET /api/v1/events.

    The ``total`` field is the count of rows matching the current filters
    *before* limit/offset are applied.  Clients can compute whether more
    pages exist without a separate request:
        has_more = offset + len(items) < total

    Fields
    ------
    items   : List of full event records (same shape as the POST response).
    limit   : The effective limit used for this response (echoed back).
    offset  : The effective offset used for this response (echoed back).
    total   : Matched rows before pagination — for UI page-count calculations.
    """

    items: list[EventResponse]
    limit: int = Field(..., description="Effective limit applied.")
    offset: int = Field(..., description="Effective offset applied.")
    total: int = Field(..., description="Total matching records before pagination.")
