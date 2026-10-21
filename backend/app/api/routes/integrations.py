"""Integration status, mock Slack receiver, and notification outbox endpoints."""

from __future__ import annotations

import json
from datetime import timedelta

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.registry import ADAPTERS
from app.api.deps import get_clock, get_session, get_settings
from app.clock import Clock
from app.config import Settings
from app.errors import ApiError
from app.models import Alert, Notification
from app.schemas import (
    IntegrationResponse,
    IntegrationSourceRead,
    NotificationCountsRead,
    NotificationListResponse,
)
from app.services.notifications import NotificationService
from app.services.presenters import present_notification

router = APIRouter(tags=["integrations"])


@router.get("/api/integrations", response_model=IntegrationResponse)
def integrations(
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    clock: Clock = Depends(get_clock),
) -> IntegrationResponse:
    since = clock.now() - timedelta(hours=24)
    counts = dict(
        session.execute(
            select(Alert.source, func.count(Alert.id))
            .where(Alert.received_at >= since)
            .group_by(Alert.source)
        ).all()
    )
    last_seen = dict(
        session.execute(
            select(Alert.source, func.max(Alert.received_at)).group_by(Alert.source)
        ).all()
    )
    sources = [
        IntegrationSourceRead(
            source=source,
            display_name=adapter.display_name,
            description=adapter.description,
            endpoint=f"/api/webhooks/alerts/{source}",
            alerts_24h=int(counts.get(source, 0)),
            last_received_at=last_seen.get(source),
        )
        for source, adapter in sorted(ADAPTERS.items())
    ]

    status_counts = dict(
        session.execute(
            select(Notification.status, func.count(Notification.id)).group_by(Notification.status)
        ).all()
    )
    recent = session.scalars(
        select(Notification)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(8)
    ).all()
    notification_counts = NotificationCountsRead(
        sent=int(status_counts.get("sent", 0)),
        pending=int(status_counts.get("pending", 0)),
        failed=int(status_counts.get("failed", 0)),
    )
    return IntegrationResponse(
        sources=sources,
        rate_limit={
            "requests_per_minute": settings.rate_limit_per_minute,
            "scope": "per source and client address, per API process (in-memory)",
            "note": ("A reverse proxy or API gateway should enforce shared limits in production."),
        },
        idempotency={
            "strategy": "SHA-256(source + '|' + deduplication_key)",
            "duplicate_behavior": (
                "Repeat deliveries update occurrence count and last-seen time; they do not "
                "create a second alert, incident, or notification."
            ),
            "delivery_header": "X-Bamboo11y-Delivery-Id (retained as metadata; optional)",
        },
        notifications={
            "channel": "webhook" if settings.notification_webhook_url else "mock-slack",
            "external_webhook_configured": bool(settings.notification_webhook_url),
            "counts": notification_counts.model_dump(),
            "recent": [present_notification(item).model_dump(mode="json") for item in recent],
            "local_sink_note": (
                "The default sink is the local outbox labelled mock-slack. Set "
                "BAMBOO11Y_NOTIFICATION_WEBHOOK_URL to exercise an HTTP receiver."
            ),
        },
        mock_slack_endpoint="/api/mock/slack",
    )


@router.get("/api/notifications", response_model=NotificationListResponse)
def list_notifications(
    session: Session = Depends(get_session),
    limit: int = Query(default=50, ge=1, le=200),
) -> NotificationListResponse:
    items = session.scalars(
        select(Notification)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit)
    ).all()
    status_counts = dict(
        session.execute(
            select(Notification.status, func.count(Notification.id)).group_by(Notification.status)
        ).all()
    )
    return NotificationListResponse(
        items=[present_notification(item) for item in items],
        counts=NotificationCountsRead(
            sent=int(status_counts.get("sent", 0)),
            pending=int(status_counts.get("pending", 0)),
            failed=int(status_counts.get("failed", 0)),
        ),
    )


@router.post("/api/notifications/dispatch")
def dispatch_notifications(
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    clock: Clock = Depends(get_clock),
    include_failed: bool = Query(default=True),
) -> dict[str, int]:
    return NotificationService(session, settings, clock).dispatch_pending(
        include_failed=include_failed
    )


@router.post("/api/mock/slack", include_in_schema=True)
async def mock_slack(request: Request) -> dict[str, object]:
    """A local, credential-free receiver for the optional HTTP notification path.

    It intentionally does not render or replay the payload. The outbox is the source of
    truth for deliveries; this endpoint proves the external webhook wiring works.
    """

    body = await request.body()
    if not body:
        raise ApiError(400, "empty_payload", "Mock Slack payload is empty.")
    if len(body) > 1_000_000:
        raise ApiError(413, "payload_too_large", "Mock Slack payload is too large.")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ApiError(400, "invalid_json", "Mock Slack payload is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise ApiError(400, "invalid_payload", "Mock Slack payload must be a JSON object.")
    text = payload.get("text", "")
    if text is not None and not isinstance(text, str):
        raise ApiError(422, "invalid_payload", "Mock Slack 'text' must be a string.")
    return {
        "ok": True,
        "channel": "#bamboo11y-demo",
        "accepted_characters": len(text or ""),
        "note": "Local mock receiver. No external Slack account was contacted.",
    }
