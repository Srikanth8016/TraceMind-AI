"""
app/services/integrations/pagerduty.py — Inbound PagerDuty webhook adapter.

Milestone 19: External Alert Integrations & Notifications.

Security & Features:
- HMAC-SHA256 signature verification over raw request body using X-PagerDuty-Signature (v1=<hash>).
- Constant-time signature comparison with hmac.compare_digest.
- Replay attack mitigation: validates event occurred_at timestamp within PAGERDUTY_WEBHOOK_MAX_AGE_SECONDS.
- Redaction of signatures and secrets in logging.
- Strict Pydantic payload validation supporting both PagerDuty Webhooks v3 and legacy v2 formats.
- Normalized severity mapping (high -> CRITICAL, low -> WARNING/INFO).
- Deduplication via provider event/incident ID.
"""

from datetime import datetime, timezone
import hashlib
import hmac
import logging
import re
from typing import Any, Optional
import uuid

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field

from app.config import get_settings
from app.schemas.event import EventCreate, SeverityLevel
from app.services.integrations.exceptions import (
    WebhookAuthenticationError,
    WebhookDisabledError,
    WebhookPayloadValidationError,
    WebhookReplayError,
)

logger = logging.getLogger(__name__)

SERVICE_NAME_CLEAN_REGEX = re.compile(r"[^a-zA-Z0-9_\-\.]")


class PagerDutyServiceRef(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: Optional[str] = None
    name: Optional[str] = None
    type: Optional[str] = None


class PagerDutyIncidentData(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    urgency: Optional[str] = None  # "high", "low"
    status: Optional[str] = None   # "triggered", "acknowledged", "resolved"
    service: Optional[PagerDutyServiceRef] = None
    custom_details: Optional[dict[str, Any]] = None


class PagerDutyEventV3(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: Optional[str] = None
    event_type: Optional[str] = None  # "incident.triggered", "incident.acknowledged", etc.
    resource_type: Optional[str] = None
    occurred_at: Optional[datetime] = None
    data: Optional[PagerDutyIncidentData] = None


class PagerDutyV3Payload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    event: Optional[PagerDutyEventV3] = None


class PagerDutyV2Message(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: Optional[str] = None
    event: Optional[str] = None
    created_on: Optional[datetime] = None
    incident: Optional[PagerDutyIncidentData] = None


class PagerDutyV2Payload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    messages: Optional[list[PagerDutyV2Message]] = None


def verify_pagerduty_webhook(
    raw_body_bytes: bytes,
    signature_header: Optional[str],
) -> None:
    """
    Verify PagerDuty v3 webhook signature using HMAC-SHA256.

    PagerDuty sends X-PagerDuty-Signature in format:
    'v1=<sig1>,v1=<sig2>'

    Expected HMAC:
    HMAC-SHA256(key=PAGERDUTY_WEBHOOK_SECRET, message=raw_body_bytes)
    """
    settings = get_settings()

    if not settings.PAGERDUTY_WEBHOOK_ENABLED:
        raise WebhookDisabledError("PagerDuty webhook integration is disabled.")

    secret = settings.PAGERDUTY_WEBHOOK_SECRET
    if not secret:
        # No secret configured: allow (e.g. local dev / test)
        return

    if not signature_header:
        raise WebhookAuthenticationError("Missing X-PagerDuty-Signature header.")

    computed_hmac = hmac.new(
        secret.encode("utf-8"),
        raw_body_bytes,
        hashlib.sha256,
    ).hexdigest()

    # PagerDuty may send comma-separated signatures (e.g. during secret rotation)
    signatures = [
        part.strip().replace("v1=", "")
        for part in signature_header.split(",")
        if part.strip().startswith("v1=")
    ]

    if not signatures:
        raise WebhookAuthenticationError("No v1 signature found in X-PagerDuty-Signature header.")

    # Match computed signature against any provided v1 signature in constant time
    valid = any(
        hmac.compare_digest(sig.encode("utf-8"), computed_hmac.encode("utf-8"))
        for sig in signatures
    )

    if not valid:
        raise WebhookAuthenticationError("Invalid PagerDuty signature.")


def validate_replay_timestamp(
    event_time: Optional[datetime],
    max_age_seconds: int = 300,
) -> None:
    """
    Validate that incoming webhook timestamp is within acceptable replay drift window.
    """
    if event_time is None:
        return

    now = datetime.now(timezone.utc)
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=timezone.utc)

    drift_seconds = abs((now - event_time).total_seconds())
    if drift_seconds > max_age_seconds:
        raise WebhookReplayError(
            f"Webhook event timestamp ({event_time.isoformat()}) drifted {drift_seconds:.1f}s "
            f"exceeding maximum allowed age of {max_age_seconds}s."
        )


def parse_and_normalize_pagerduty_webhook(
    raw_payload: dict[str, Any],
    default_workspace_id: Optional[uuid.UUID] = None,
) -> tuple[EventCreate, str, Optional[uuid.UUID]]:
    """
    Validate incoming PagerDuty payload (v3 or v2) and normalize into EventCreate schema.

    Returns
    -------
    tuple[EventCreate, str, Optional[uuid.UUID]]
        - event_create: Validated internal EventCreate schema.
        - provider_event_id: Unique PagerDuty event ID for deduplication.
        - workspace_id: Target workspace UUID if specified in payload or query.
    """
    settings = get_settings()

    # Determine if v3 or v2 format
    is_v3 = "event" in raw_payload
    is_v2 = "messages" in raw_payload

    if not (is_v3 or is_v2):
        raise WebhookPayloadValidationError("Payload must contain 'event' (v3) or 'messages' (v2).")

    event_time: Optional[datetime] = None
    service_name = "pagerduty-service"
    environment = "production"
    urgency = "high"
    title = "PagerDuty Incident"
    provider_event_id = ""
    target_workspace_id = default_workspace_id

    if is_v3:
        try:
            v3 = PagerDutyV3Payload.model_validate(raw_payload)
        except Exception as exc:
            raise WebhookPayloadValidationError(f"Invalid PagerDuty v3 payload: {exc}") from exc

        ev = v3.event
        if not ev:
            raise WebhookPayloadValidationError("Empty event object in PagerDuty payload.")

        event_time = ev.occurred_at
        provider_event_id = ev.id or (ev.data.id if ev.data else None) or str(uuid.uuid4())

        if ev.data:
            title = ev.data.title or ev.data.summary or f"PagerDuty Alert: {ev.event_type}"
            urgency = (ev.data.urgency or "high").lower()
            if ev.data.service and ev.data.service.name:
                service_name = ev.data.service.name
            if ev.data.custom_details:
                if "environment" in ev.data.custom_details:
                    environment = str(ev.data.custom_details["environment"])
                elif "env" in ev.data.custom_details:
                    environment = str(ev.data.custom_details["env"])
                if "workspace_id" in ev.data.custom_details:
                    try:
                        target_workspace_id = uuid.UUID(str(ev.data.custom_details["workspace_id"]))
                    except ValueError:
                        pass
        else:
            title = f"PagerDuty Event: {ev.event_type}"

    else:
        # PagerDuty v2 format
        try:
            v2 = PagerDutyV2Payload.model_validate(raw_payload)
        except Exception as exc:
            raise WebhookPayloadValidationError(f"Invalid PagerDuty v2 payload: {exc}") from exc

        msgs = v2.messages or []
        if not msgs:
            raise WebhookPayloadValidationError("No messages found in PagerDuty v2 payload.")

        msg = msgs[0]
        event_time = msg.created_on
        provider_event_id = msg.id or (msg.incident.id if msg.incident else None) or str(uuid.uuid4())

        if msg.incident:
            title = msg.incident.title or msg.incident.summary or "PagerDuty Incident"
            urgency = (msg.incident.urgency or "high").lower()
            if msg.incident.service and msg.incident.service.name:
                service_name = msg.incident.service.name
        else:
            title = f"PagerDuty Event: {msg.event}"

    # Replay protection check
    validate_replay_timestamp(event_time, max_age_seconds=settings.PAGERDUTY_WEBHOOK_MAX_AGE_SECONDS)

    # Clean service name
    clean_service = SERVICE_NAME_CLEAN_REGEX.sub("-", service_name)[:100]
    if not clean_service or clean_service == "-":
        clean_service = "pagerduty-service"

    # Map urgency to severity level
    if urgency == "high":
        level = SeverityLevel.CRITICAL
    else:
        level = SeverityLevel.WARNING

    # Final timestamp
    if event_time is None:
        event_time = datetime.now(timezone.utc)
    elif event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=timezone.utc)

    event_create = EventCreate(
        service_name=clean_service,
        environment=environment[:50],
        level=level,
        message=title.strip()[:5000],
        timestamp=event_time,
    )

    return event_create, str(provider_event_id), target_workspace_id
