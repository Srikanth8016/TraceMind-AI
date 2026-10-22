"""
app/services/integrations/datadog.py — Inbound Datadog alert webhook adapter.

Milestone 19: External Alert Integrations & Notifications.

Security & Features:
- Constant-time secret/token verification (DD-WEBHOOK-TOKEN, X-Datadog-Token, Authorization, or ?token=).
- Redaction of authentication tokens in all logging.
- Strict Pydantic payload validation.
- Tag extraction for service_name, environment, and workspace_id.
- Normalized severity mapping (error/warning/info) with priority escalation.
- Idempotency key extraction from Datadog alert identifier.
"""

from datetime import datetime, timezone
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
)

logger = logging.getLogger(__name__)

SERVICE_NAME_CLEAN_REGEX = re.compile(r"[^a-zA-Z0-9_\-\.]")


class DatadogAlertPayload(BaseModel):
    """
    Pydantic schema representing incoming Datadog monitor / event alert payload.
    Tolerates varied Datadog webhook template schemas while extracting required fields.
    """
    model_config = ConfigDict(extra="ignore")

    id: Optional[str | int] = Field(default=None, description="Datadog alert or event ID")
    event_id: Optional[str | int] = Field(default=None, description="Alternative event ID field")
    title: Optional[str] = Field(default=None, description="Monitor alert title")
    event_title: Optional[str] = Field(default=None, description="Alternative title field")
    body: Optional[str] = Field(default=None, description="Alert body text or message markdown")
    message: Optional[str] = Field(default=None, description="Alternative message field")
    alert_type: Optional[str] = Field(default=None, description="error, warning, info, or success")
    transition: Optional[str] = Field(default=None, description="Triggered, Warn, Recovered, etc.")
    date: Optional[int | float] = Field(default=None, description="Epoch timestamp (seconds or milliseconds)")
    tags: Optional[list[str] | dict[str, Any] | str] = Field(default=None, description="Monitor tags list or string")
    hostname: Optional[str] = Field(default=None, description="Reporting host or instance")
    priority: Optional[str] = Field(default=None, description="Datadog priority: P1, P2, P3, P4, P5")


def verify_datadog_webhook(request: Request) -> None:
    """
    Verify Datadog webhook authenticity via constant-time token comparison.

    Checks headers:
    1. DD-WEBHOOK-TOKEN
    2. X-Datadog-Token
    3. Authorization (Bearer <token>)
    4. Query parameter ?token=<token>

    If DATADOG_WEBHOOK_SECRET is not configured (e.g. in local dev), verification is skipped.
    If configured and token is missing or incorrect, raises WebhookAuthenticationError.
    """
    settings = get_settings()

    if not settings.DATADOG_WEBHOOK_ENABLED:
        raise WebhookDisabledError("Datadog webhook integration is disabled.")

    expected_secret = settings.DATADOG_WEBHOOK_SECRET
    if not expected_secret:
        # No secret configured: allow (e.g. test / unauthenticated dev environment)
        return

    # Extract incoming token from allowed headers or query param
    incoming_token = (
        request.headers.get("DD-WEBHOOK-TOKEN")
        or request.headers.get("X-Datadog-Token")
        or request.headers.get("dd-webhook-token")
        or request.headers.get("x-datadog-token")
    )

    if not incoming_token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.lower().startswith("bearer "):
            incoming_token = auth_header[7:].strip()
        elif auth_header:
            incoming_token = auth_header.strip()

    if not incoming_token:
        incoming_token = request.query_params.get("token")

    if not incoming_token:
        raise WebhookAuthenticationError("Missing Datadog webhook authentication token.")

    # Constant-time comparison prevents timing attacks
    if not hmac.compare_digest(incoming_token.encode("utf-8"), expected_secret.encode("utf-8")):
        raise WebhookAuthenticationError("Invalid Datadog webhook authentication token.")


def parse_and_normalize_datadog_alert(
    raw_payload: dict[str, Any],
    default_workspace_id: Optional[uuid.UUID] = None,
) -> tuple[EventCreate, str, Optional[uuid.UUID]]:
    """
    Validate incoming Datadog payload and normalize into internal EventCreate schema.

    Returns
    -------
    tuple[EventCreate, str, Optional[uuid.UUID]]
        - event_create: Validated internal EventCreate schema.
        - provider_event_id: Unique alert ID for deduplication.
        - workspace_id: Target workspace UUID if specified via tags or query.
    """
    try:
        payload = DatadogAlertPayload.model_validate(raw_payload)
    except Exception as exc:
        raise WebhookPayloadValidationError(f"Invalid Datadog alert payload: {exc}") from exc

    # 1. Extract Tags (service, env, workspace)
    tag_list: list[str] = []
    if isinstance(payload.tags, list):
        tag_list = [str(t) for t in payload.tags]
    elif isinstance(payload.tags, str):
        tag_list = [t.strip() for t in payload.tags.split(",") if t.strip()]
    elif isinstance(payload.tags, dict):
        tag_list = [f"{k}:{v}" for k, v in payload.tags.items()]

    parsed_tags: dict[str, str] = {}
    for tag in tag_list:
        if ":" in tag:
            k, v = tag.split(":", 1)
            parsed_tags[k.strip().lower()] = v.strip()

    # Service name resolution
    raw_service = parsed_tags.get("service") or payload.hostname or "datadog-monitor"
    clean_service = SERVICE_NAME_CLEAN_REGEX.sub("-", raw_service)[:100]
    if not clean_service or clean_service == "-":
        clean_service = "datadog-monitor"

    # Environment resolution
    clean_env = parsed_tags.get("env") or parsed_tags.get("environment") or "production"
    clean_env = clean_env[:50]

    # Workspace ID resolution (from tags if present, else default)
    target_workspace_id = default_workspace_id
    if "workspace" in parsed_tags:
        try:
            target_workspace_id = uuid.UUID(parsed_tags["workspace"])
        except ValueError:
            pass

    # 2. Severity Level Mapping
    alert_type = (payload.alert_type or payload.transition or "").lower()
    priority = (payload.priority or "").upper()

    if priority == "P1" or "critical" in alert_type:
        level = SeverityLevel.CRITICAL
    elif alert_type in ("error", "triggered"):
        level = SeverityLevel.ERROR
    elif alert_type in ("warning", "warn"):
        level = SeverityLevel.WARNING
    elif alert_type in ("info", "success", "recovered", "ok"):
        level = SeverityLevel.INFO
    else:
        level = SeverityLevel.ERROR

    # 3. Message Extraction
    title = payload.title or payload.event_title or "Datadog Monitor Alert"
    body = payload.body or payload.message or ""
    if body and body != title:
        full_message = f"{title}\n{body}"
    else:
        full_message = title
    clean_message = full_message.strip()[:5000]
    if not clean_message:
        clean_message = "Datadog Monitor Alert (no description provided)"

    # 4. Timestamp Normalization
    if payload.date:
        try:
            val = float(payload.date)
            # If timestamp is in milliseconds (greater than year 3000 in seconds)
            if val > 30000000000:
                val = val / 1000.0
            event_timestamp = datetime.fromtimestamp(val, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            event_timestamp = datetime.now(timezone.utc)
    else:
        event_timestamp = datetime.now(timezone.utc)

    # 5. Provider Event ID / Deduplication Key
    raw_id = payload.id or payload.event_id
    if raw_id is not None:
        provider_event_id = str(raw_id)
    else:
        # Fallback to deterministic hash of title and timestamp
        provider_event_id = f"dd-{abs(hash((clean_service, clean_message[:100], int(event_timestamp.timestamp()))))}"

    event_create = EventCreate(
        service_name=clean_service,
        environment=clean_env,
        level=level,
        message=clean_message,
        timestamp=event_timestamp,
    )

    return event_create, provider_event_id, target_workspace_id
