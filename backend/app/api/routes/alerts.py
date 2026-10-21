"""Webhook ingestion and normalized alert read endpoints."""

from __future__ import annotations

import json
from dataclasses import asdict

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters import AdapterValidationError, get_adapter, supported_sources
from app.adapters.base import clean_text
from app.api.deps import get_catalog, get_clock, get_session, get_settings
from app.clock import Clock
from app.config import Settings
from app.constants import AlertStatus, Severity, Source
from app.errors import ApiError
from app.models import Alert
from app.schemas import (
    AlertListResponse,
    AlertOutcomeRead,
    AlertRead,
    WebhookIngestResponse,
)
from app.services.catalog import Catalog
from app.services.ingestion import AlertIngestionService
from app.services.presenters import present_alert

router = APIRouter(tags=["alerts"])


@router.post(
    "/api/webhooks/alerts/{source}",
    response_model=WebhookIngestResponse,
    status_code=201,
    responses={
        200: {"description": "Duplicate delivery; no new alert was created."},
        400: {"description": "Malformed JSON or oversized payload."},
        404: {"description": "Unsupported source."},
        422: {"description": "Payload validation failed."},
        429: {"description": "Webhook rate limit exceeded."},
    },
)
async def ingest_webhook(
    source: str,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    catalog: Catalog = Depends(get_catalog),
    clock: Clock = Depends(get_clock),
) -> WebhookIngestResponse:
    adapter = get_adapter(source)
    if adapter is None:
        request.app.state.metrics.observe_webhook(source, "unsupported_source")
        raise ApiError(
            404,
            "unsupported_source",
            f"Unsupported alert source '{source}'.",
            errors=[
                {
                    "field": "source",
                    "message": f"Supported sources: {', '.join(supported_sources())}.",
                }
            ],
            hints=[
                "Use /api/webhooks/alerts/prometheus for Alertmanager.",
                "Use /api/webhooks/alerts/cloudwatch for CloudWatch/SNS alarm state changes.",
                "Use /api/webhooks/alerts/open-integration for vendor-neutral app/check events.",
            ],
            context={"supported_sources": supported_sources()},
        )

    body = await request.body()
    if not body:
        request.app.state.metrics.observe_webhook(source, "rejected")
        raise ApiError(400, "empty_body", "Request body is empty.", hints=["Send a JSON payload."])
    if len(body) > settings.max_payload_bytes:
        request.app.state.metrics.observe_webhook(source, "rejected")
        raise ApiError(
            413,
            "payload_too_large",
            f"Request body exceeds the {settings.max_payload_bytes:,}-byte limit.",
        )
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        request.app.state.metrics.observe_webhook(source, "rejected")
        raise ApiError(
            400,
            "invalid_json",
            "Request body is not valid JSON.",
            errors=[{"field": "body", "message": f"JSON parse error at line {exc.lineno}."}],
            hints=["Check quoting, commas, and the Content-Type of your webhook receiver."],
        ) from exc
    if not isinstance(payload, dict):
        request.app.state.metrics.observe_webhook(source, "rejected")
        raise ApiError(
            400,
            "invalid_payload",
            "Webhook body must be a JSON object.",
            errors=[{"field": "body", "message": "Expected a top-level object."}],
        )

    delivery_id = _delivery_id(request)
    received_at = clock.now()
    try:
        normalized = adapter.normalize(payload, received_at=received_at, delivery_id=delivery_id)
    except AdapterValidationError as exc:
        request.app.state.metrics.observe_webhook(source, "rejected")
        raise ApiError(
            422,
            "invalid_payload",
            exc.message,
            errors=exc.errors,
            hints=["Compare the payload with the documented examples in README.md."],
        ) from exc

    if len(normalized) > settings.max_alerts_per_request:
        request.app.state.metrics.observe_webhook(source, "rejected")
        raise ApiError(
            422,
            "too_many_alerts",
            (
                f"Payload contains {len(normalized)} alerts; this deployment accepts at most "
                f"{settings.max_alerts_per_request} per request."
            ),
        )

    service = AlertIngestionService(session, settings, catalog, clock)
    try:
        result = service.ingest(
            adapter.source,
            normalized,
            received_at=received_at,
            delivery_id=delivery_id,
            is_demo=False,
        )
        session.commit()
        dispatch = service.notifications.dispatch_pending()
        if dispatch.get("sent"):
            request.app.state.metrics.observe_notification_result("sent", dispatch["sent"])
        if dispatch.get("failed"):
            request.app.state.metrics.observe_notification_result("failed", dispatch["failed"])
    except Exception:
        session.rollback()
        request.app.state.metrics.observe_webhook(source, "error")
        raise

    request.app.state.metrics.observe_webhook(source, "accepted")
    for outcome in result.outcomes:
        request.app.state.metrics.observe_alert(source, outcome.outcome)
    request.app.state.metrics.observe_incident_created(result.incidents_created)

    response.status_code = 201 if result.created_alerts else 200
    joined = sum(1 for outcome in result.outcomes if outcome.outcome == "joined")
    updated = sum(1 for outcome in result.outcomes if outcome.outcome == "updated")
    resolved_alone = sum(
        1 for outcome in result.outcomes if outcome.outcome == "resolved_without_incident"
    )
    return WebhookIngestResponse(
        source=source,
        received=result.received,
        created_alerts=result.created_alerts,
        joined_alerts=joined,
        updated_alerts=updated,
        resolved_without_incident=resolved_alone,
        duplicates=result.duplicates,
        incidents_created=result.incidents_created,
        notifications_created=len(result.notification_ids),
        outcomes=[AlertOutcomeRead(**asdict(outcome)) for outcome in result.outcomes],
    )


@router.get("/api/alerts", response_model=AlertListResponse)
def list_alerts(
    session: Session = Depends(get_session),
    source: Source | None = None,
    status: AlertStatus | None = None,
    severity: Severity | None = None,
    service: str | None = Query(default=None, max_length=128),
    environment: str | None = Query(default=None, max_length=64),
    incident_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> AlertListResponse:
    conditions = []
    if source:
        conditions.append(Alert.source == source.value)
    if status:
        conditions.append(Alert.status == status.value)
    if severity:
        conditions.append(Alert.severity == severity.value)
    if service:
        conditions.append(Alert.service == service)
    if environment:
        conditions.append(Alert.environment == environment)
    if incident_id is not None:
        conditions.append(Alert.incident_id == incident_id)

    total = int(session.scalar(select(func.count(Alert.id)).where(*conditions)) or 0)
    items = session.scalars(
        select(Alert)
        .where(*conditions)
        .order_by(Alert.received_at.desc(), Alert.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return AlertListResponse(
        items=[present_alert(alert) for alert in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/api/alerts/{alert_id}", response_model=AlertRead)
def get_alert(alert_id: int, session: Session = Depends(get_session)) -> AlertRead:
    alert = session.get(Alert, alert_id)
    if alert is None:
        raise ApiError(404, "alert_not_found", f"Alert {alert_id} was not found.")
    return present_alert(alert)


def _delivery_id(request: Request) -> str | None:
    raw = request.headers.get("x-bamboo11y-delivery-id") or request.headers.get("idempotency-key")
    if not raw:
        return None
    cleaned = clean_text(raw, max_length=128)
    return cleaned or None
