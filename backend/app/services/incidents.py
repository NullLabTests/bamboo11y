"""Incident lifecycle, audit events, and safe state transitions."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.adapters.base import NormalizedAlert, clean_text, truncate
from app.clock import Clock
from app.constants import AlertStatus, IncidentStatus, max_severity
from app.models import Alert, Incident, IncidentEvent


class TransitionError(ValueError):
    def __init__(self, message: str, *, code: str = "invalid_transition") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


VALID_TRANSITIONS: dict[str, set[str]] = {
    IncidentStatus.OPEN.value: {
        IncidentStatus.ACKNOWLEDGED.value,
        IncidentStatus.RESOLVED.value,
    },
    IncidentStatus.ACKNOWLEDGED.value: {IncidentStatus.RESOLVED.value},
    IncidentStatus.RESOLVED.value: set(),
}


class IncidentService:
    def __init__(self, session: Session, clock: Clock) -> None:
        self.session = session
        self.clock = clock

    def create_incident(
        self,
        alert: NormalizedAlert,
        *,
        received_at: datetime,
        is_demo: bool,
        correlation_reason: dict[str, object],
        first_alert_id: int | None = None,
    ) -> tuple[Incident, IncidentEvent]:
        incident = Incident(
            title=truncate(f"{alert.service}: {alert.title}", 300),
            status=IncidentStatus.OPEN.value,
            severity=alert.severity.value,
            primary_service=alert.service,
            environment=alert.environment,
            region=alert.region,
            correlation_key=f"{alert.service}:{alert.environment}",
            created_at=received_at,
            updated_at=received_at,
            is_demo=is_demo,
        )
        self.session.add(incident)
        self.session.flush()
        event = self.record_event(
            incident,
            event_type="opened",
            message=(
                f"Incident opened for {alert.service} in {alert.environment} by the "
                f"rule-based correlation engine."
            ),
            occurred_at=received_at,
            actor="Bamboo11y correlation",
            automated=True,
            details={
                "rule": correlation_reason.get("rule"),
                "reason": correlation_reason,
                "first_alert_id": first_alert_id,
                "first_alert_title": alert.title,
            },
        )
        return incident, event

    def link_alert(
        self,
        incident: Incident,
        alert: Alert,
        *,
        reason: dict[str, object],
        received_at: datetime,
        is_new: bool = True,
    ) -> IncidentEvent | None:
        alert.incident = incident
        alert.correlation = reason
        incident.updated_at = received_at
        incident.severity = max_severity(incident.severity, alert.severity)
        if incident.region is None and alert.region:
            incident.region = alert.region
        event: IncidentEvent | None = None
        if is_new:
            event = self.record_event(
                incident,
                event_type="alert_linked",
                message=f"Alert linked: {alert.title}",
                occurred_at=received_at,
                actor="Bamboo11y correlation",
                automated=True,
                details={
                    "alert_id": alert.id,
                    "fingerprint": alert.fingerprint,
                    "rule": reason.get("rule"),
                    "reason": reason,
                },
            )
        return event

    def transition(
        self,
        incident: Incident,
        desired: IncidentStatus,
        *,
        actor: str,
        note: str | None,
        now: datetime,
    ) -> tuple[Incident, IncidentEvent | None]:
        current = IncidentStatus(incident.status)
        if current is desired:
            return incident, None
        if desired is IncidentStatus.OPEN:
            raise TransitionError(
                "Resolved incidents cannot be manually reopened. A re-fired alert with the "
                "same fingerprint may reopen an incident automatically."
            )
        if desired.value not in VALID_TRANSITIONS.get(current.value, set()):
            raise TransitionError(
                f"Cannot move incident from {current.value} to {desired.value}.",
                code="invalid_transition",
            )

        safe_actor = clean_text(actor, max_length=128, default="local-operator")
        safe_note = clean_text(note, max_length=2000) or None
        if desired is IncidentStatus.ACKNOWLEDGED:
            incident.status = IncidentStatus.ACKNOWLEDGED.value
            incident.acknowledged_at = now
            incident.acknowledged_by = safe_actor
            incident.updated_at = now
            event = self.record_event(
                incident,
                event_type="acknowledged",
                message=f"Incident acknowledged by {safe_actor}.",
                occurred_at=now,
                actor=safe_actor,
                automated=False,
                details={"note": safe_note},
            )
            return incident, event

        incident.status = IncidentStatus.RESOLVED.value
        incident.resolved_at = now
        incident.resolved_by = safe_actor
        incident.resolution_note = safe_note
        incident.updated_at = now
        event = self.record_event(
            incident,
            event_type="resolved",
            message=f"Incident resolved by {safe_actor}.",
            occurred_at=now,
            actor=safe_actor,
            automated=False,
            details={"note": safe_note},
        )
        return incident, event

    def reopen_from_source(
        self,
        incident: Incident,
        *,
        alert: Alert,
        now: datetime,
        reason: dict[str, object],
    ) -> IncidentEvent:
        incident.status = IncidentStatus.OPEN.value
        incident.acknowledged_at = None
        incident.acknowledged_by = None
        incident.resolved_at = None
        incident.resolved_by = None
        incident.resolution_note = None
        incident.updated_at = now
        incident.severity = max_severity(incident.severity, alert.severity)
        alert.incident = incident
        alert.correlation = reason
        return self.record_event(
            incident,
            event_type="reopened",
            message=(
                f"Incident reopened automatically after {alert.service} re-fired with the "
                f"same alert fingerprint."
            ),
            occurred_at=now,
            actor="Bamboo11y correlation",
            automated=True,
            details={
                "alert_id": alert.id,
                "fingerprint": alert.fingerprint,
                "rule": "fingerprint_replay",
                "reason": reason,
            },
        )

    def record_event(
        self,
        incident: Incident,
        *,
        event_type: str,
        message: str,
        occurred_at: datetime,
        actor: str | None,
        automated: bool,
        details: dict[str, object],
    ) -> IncidentEvent:
        event = IncidentEvent(
            incident_id=incident.id,
            event_type=event_type,
            message=truncate(clean_text(message, max_length=3000), 3000),
            actor=actor,
            automated=automated,
            occurred_at=occurred_at,
            details=details,
        )
        self.session.add(event)
        self.session.flush()
        return event

    @staticmethod
    def apply_source_resolution(alert: Alert, *, now: datetime) -> bool:
        """Mark the source condition resolved without auto-resolving the incident."""

        if alert.status == AlertStatus.RESOLVED.value:
            return False
        alert.status = AlertStatus.RESOLVED.value
        alert.last_seen_at = now
        return True
