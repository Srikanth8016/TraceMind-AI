"""
app/routers/webhooks.py — Inbound webhook endpoints for Datadog and PagerDuty alerts.

Milestone 19: External Alert Integrations & Notifications.

Endpoints:
- POST /api/v1/webhooks/datadog: Accepts Datadog monitor & synthetic test alert webhooks.
- POST /api/v1/webhooks/pagerduty: Accepts PagerDuty v3 / v2 alert notifications with HMAC-SHA256 verification.
"""

import json
import logging
from typing import Optional
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.integrations.datadog import (
    parse_and_normalize_datadog_alert,
    verify_datadog_webhook,
)
from app.services.integrations.exceptions import (
    WebhookAuthenticationError,
    WebhookDisabledError,
    WebhookPayloadValidationError,
    WebhookReplayError,
)
from app.services.integrations.pagerduty import (
    parse_and_normalize_pagerduty_webhook,
    verify_pagerduty_webhook,
)
from app.services.integrations.pipeline import InboundAlertResult, process_inbound_alert

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class WebhookResponse(BaseModel):
    """Standardized response for inbound alert webhooks."""
    status: str
    event_id: Optional[uuid.UUID] = None
    job_id: Optional[uuid.UUID] = None
    provider: str
    message: str


@router.post(
    "/datadog",
    response_model=WebhookResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Inbound Datadog alert webhook",
    description=(
        "Receives alert webhooks from Datadog monitors and synthetic tests. "
        "Verifies secret token via DD-WEBHOOK-TOKEN or Authorization header when configured. "
        "Normalizes tags, severity, and host into the internal event pipeline. "
        "Supports optional ?workspace_id= UUID parameter for team workspace scoping."
    ),
)
async def datadog_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    workspace_id: Optional[uuid.UUID] = Query(default=None, description="Optional team workspace UUID"),
    db: Session = Depends(get_db),
) -> WebhookResponse:
    """
    Ingest, verify, and correlate inbound Datadog alert webhook.
    """
    # 1. Signature / Token verification
    try:
        verify_datadog_webhook(request)
    except WebhookDisabledError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except WebhookAuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    # 2. Parse JSON body
    try:
        raw_payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid JSON body") from exc

    # 3. Normalize to EventCreate
    try:
        event_create, provider_id, target_ws = parse_and_normalize_datadog_alert(
            raw_payload,
            default_workspace_id=workspace_id,
        )
    except WebhookPayloadValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    # 4. Ingest and deduplicate
    result: InboundAlertResult = process_inbound_alert(
        db=db,
        background_tasks=background_tasks,
        provider="datadog",
        event_create=event_create,
        provider_event_id=provider_id,
        workspace_id=target_ws,
    )

    return WebhookResponse(
        status=result.status,
        event_id=result.event_id,
        job_id=result.job_id,
        provider="datadog",
        message=result.message,
    )


@router.post(
    "/pagerduty",
    response_model=WebhookResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Inbound PagerDuty alert webhook",
    description=(
        "Receives v3 / v2 alert notifications from PagerDuty. "
        "Verifies HMAC-SHA256 signature in X-PagerDuty-Signature against raw payload body. "
        "Guards against replay attacks by checking event occurred_at timestamp. "
        "Normalizes incident, service, and urgency into the internal event pipeline. "
        "Supports optional ?workspace_id= UUID parameter for team workspace scoping."
    ),
)
async def pagerduty_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    workspace_id: Optional[uuid.UUID] = Query(default=None, description="Optional team workspace UUID"),
    db: Session = Depends(get_db),
) -> WebhookResponse:
    """
    Ingest, verify signature, and correlate inbound PagerDuty webhook.
    """
    # 1. Read raw body bytes for HMAC computation
    raw_body_bytes = await request.body()

    # 2. Signature verification
    sig_header = request.headers.get("X-PagerDuty-Signature") or request.headers.get("x-pagerduty-signature")
    try:
        verify_pagerduty_webhook(raw_body_bytes, sig_header)
    except WebhookDisabledError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except WebhookAuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    # 3. Parse JSON body
    try:
        raw_payload = json.loads(raw_body_bytes)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid JSON body") from exc

    # 4. Normalize to EventCreate with replay timestamp check
    try:
        event_create, provider_id, target_ws = parse_and_normalize_pagerduty_webhook(
            raw_payload,
            default_workspace_id=workspace_id,
        )
    except WebhookReplayError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except WebhookPayloadValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    # 5. Ingest and deduplicate
    result: InboundAlertResult = process_inbound_alert(
        db=db,
        background_tasks=background_tasks,
        provider="pagerduty",
        event_create=event_create,
        provider_event_id=provider_id,
        workspace_id=target_ws,
    )

    return WebhookResponse(
        status=result.status,
        event_id=result.event_id,
        job_id=result.job_id,
        provider="pagerduty",
        message=result.message,
    )
