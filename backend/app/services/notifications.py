"""Local-first notification outbox and mock Slack delivery."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import Clock
from app.config import Settings
from app.models import Incident, IncidentEvent, Notification


def build_slack_payload(incident: Incident, event: IncidentEvent) -> dict[str, Any]:
    """Build a Slack-style message without claiming a Slack connection."""

    status_line = f"*Status:* {incident.status}"
    severity_line = f"*Severity:* {incident.severity.upper()}"
    service_line = f"*Service:* {incident.primary_service}"
    environment_line = f"*Environment:* {incident.environment}"
    event_label = event.event_type.replace("_", " ").capitalize()
    return {
        "channel": "#bamboo11y-demo",
        "username": "Bamboo11y",
        "text": f"[{incident.severity.upper()}] {event_label}: {incident.title}",
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"{event_label} · {incident.title}"},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": status_line},
                    {"type": "mrkdwn", "text": severity_line},
                    {"type": "mrkdwn", "text": service_line},
                    {"type": "mrkdwn", "text": environment_line},
                ],
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": event.message},
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            "Bamboo11y local demo channel · no external Slack workspace "
                            "or credentials are required."
                        ),
                    }
                ],
            },
        ],
        "metadata": {
            "event": "incident_lifecycle",
            "event_type": event.event_type,
            "incident_id": str(incident.id),
        },
    }


class NotificationService:
    def __init__(self, session: Session, settings: Settings, clock: Clock) -> None:
        self.session = session
        self.settings = settings
        self.clock = clock

    @property
    def channel(self) -> str:
        return "webhook" if self.settings.notification_webhook_url else "mock-slack"

    def enqueue_for_event(
        self, incident: Incident, event: IncidentEvent, *, is_demo: bool
    ) -> Notification | None:
        """Create one outbox row per incident event.

        The event ID is part of the unique key. Idempotent repeat actions do not create a new
        event, and webhook retries do not create a new incident; both therefore cannot fan
        out duplicate notifications.
        """

        dedupe_key = f"incident:{incident.id}:event:{event.id}"
        existing = self.session.scalar(
            select(Notification).where(Notification.dedupe_key == dedupe_key)
        )
        if existing is not None:
            return None
        notification = Notification(
            incident_id=incident.id,
            event_type=event.event_type,
            channel=self.channel,
            dedupe_key=dedupe_key,
            payload=build_slack_payload(incident, event),
            status="pending",
            attempts=0,
            created_at=self.clock.now(),
            is_demo=is_demo,
        )
        self.session.add(notification)
        self.session.flush()
        return notification

    def dispatch_pending(self, *, include_failed: bool = False) -> dict[str, int]:
        statuses = ["pending", "failed"] if include_failed else ["pending"]
        pending = self.session.scalars(
            select(Notification)
            .where(Notification.status.in_(statuses))
            .order_by(Notification.created_at.asc(), Notification.id.asc())
        ).all()
        sent = 0
        failed = 0
        for notification in pending:
            notification.attempts += 1
            if not self.settings.notification_webhook_url:
                notification.status = "sent"
                notification.sent_at = self.clock.now()
                notification.last_error = None
                sent += 1
                continue
            try:
                response = httpx.post(
                    self.settings.notification_webhook_url,
                    json=notification.payload,
                    timeout=self.settings.notification_timeout_seconds,
                )
                if 200 <= response.status_code < 300:
                    notification.status = "sent"
                    notification.sent_at = self.clock.now()
                    notification.last_error = None
                    sent += 1
                else:
                    notification.status = "failed"
                    notification.last_error = (
                        f"Notification endpoint returned HTTP {response.status_code}."
                    )
                    failed += 1
            except httpx.HTTPError:
                # Do not persist exception text: URLs can contain secrets and upstream
                # libraries may echo them. The operator gets actionable status without it.
                notification.status = "failed"
                notification.last_error = "Notification endpoint was unreachable."
                failed += 1
        self.session.commit()
        return {"attempted": len(pending), "sent": sent, "failed": failed}
