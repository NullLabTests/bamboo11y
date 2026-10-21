"""Idempotent alert ingestion, enrichment, correlation, and notification enqueueing."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.base import NormalizedAlert, clamp_future_timestamp
from app.clock import Clock
from app.config import Settings
from app.constants import AlertStatus, IncidentStatus, Source, max_severity
from app.models import Alert, Incident
from app.services.catalog import Catalog
from app.services.correlation import CorrelationEngine
from app.services.enrichment import enrich_alert
from app.services.incidents import IncidentService
from app.services.notifications import NotificationService

Outcome = Literal[
    "created",
    "joined",
    "deduplicated",
    "updated",
    "resolved_without_incident",
    "reopened",
]


@dataclass
class AlertOutcome:
    alert_id: int
    fingerprint: str
    source_alert_id: str
    title: str
    service: str
    environment: str
    severity: str
    status: str
    outcome: Outcome
    incident_id: int | None
    created_incident: bool
    duplicate_delivery: bool
    correlation: dict[str, object]


@dataclass
class IngestionResult:
    source: str
    received: int
    outcomes: list[AlertOutcome] = field(default_factory=list)
    notification_ids: list[int] = field(default_factory=list)

    @property
    def created_alerts(self) -> int:
        return sum(
            outcome.outcome in {"created", "joined", "resolved_without_incident"}
            for outcome in self.outcomes
        )

    @property
    def incidents_created(self) -> int:
        return sum(outcome.created_incident for outcome in self.outcomes)

    @property
    def duplicates(self) -> int:
        return sum(outcome.duplicate_delivery for outcome in self.outcomes)


class AlertIngestionService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        catalog: Catalog,
        clock: Clock,
    ) -> None:
        self.session = session
        self.settings = settings
        self.catalog = catalog
        self.clock = clock
        self.correlation = CorrelationEngine(settings, catalog)
        self.incidents = IncidentService(session, clock)
        self.notifications = NotificationService(session, settings, clock)

    def ingest(
        self,
        source: Source,
        alerts: list[NormalizedAlert],
        *,
        received_at: datetime,
        delivery_id: str | None,
        is_demo: bool = False,
    ) -> IngestionResult:
        """Process one validated webhook request without committing the session.

        The route/service caller owns the transaction boundary so a batch is all-or-nothing
        and notifications can be dispatched only after the data is durable.
        """

        result = IngestionResult(source=source.value, received=len(alerts))
        for item in alerts:
            outcome, notification = self._ingest_one(
                item,
                received_at=received_at,
                delivery_id=delivery_id,
                is_demo=is_demo,
            )
            result.outcomes.append(outcome)
            if notification is not None:
                result.notification_ids.append(notification.id)
        return result

    def _ingest_one(
        self,
        alert: NormalizedAlert,
        *,
        received_at: datetime,
        delivery_id: str | None,
        is_demo: bool,
    ) -> tuple[AlertOutcome, object | None]:
        clamped_at = clamp_future_timestamp(
            alert.occurred_at,
            now=received_at,
            tolerance_seconds=self.settings.future_skew_tolerance_seconds,
        )
        if clamped_at != alert.occurred_at:
            alert = alert.model_copy(
                update={
                    "occurred_at": clamped_at,
                    "source_metadata": {
                        **alert.source_metadata,
                        "future_timestamp_clamped_from": alert.occurred_at.isoformat(),
                    },
                }
            )

        existing = self.session.scalar(
            select(Alert).where(
                Alert.fingerprint == alert.fingerprint,
                Alert.is_demo.is_(is_demo),
            )
        )
        if existing is not None:
            return self._handle_duplicate(
                existing,
                alert,
                received_at=received_at,
                delivery_id=delivery_id,
                is_demo=is_demo,
            )
        return self._handle_new(
            alert,
            received_at=received_at,
            delivery_id=delivery_id,
            is_demo=is_demo,
        )

    def _handle_new(
        self,
        alert: NormalizedAlert,
        *,
        received_at: datetime,
        delivery_id: str | None,
        is_demo: bool,
    ) -> tuple[AlertOutcome, object | None]:
        model = self._build_alert(
            alert,
            received_at=received_at,
            delivery_id=delivery_id,
            is_demo=is_demo,
        )

        if alert.status is AlertStatus.RESOLVED:
            self.session.add(model)
            self.session.flush()
            return (
                self._outcome(
                    model,
                    outcome="resolved_without_incident",
                    created_incident=False,
                    duplicate_delivery=False,
                    correlation={
                        "rule": "resolved_without_incident",
                        "summary": (
                            "The source reported a resolved condition with no known active "
                            "alert; it was recorded for audit without opening an incident."
                        ),
                        "matched_on": ["status"],
                        "note": "No incident was created for a resolved-only delivery.",
                    },
                ),
                None,
            )

        match = self.correlation.find_match(self.session, alert, is_demo=is_demo)
        if match is not None:
            model.correlation = match.reason
            self.session.add(model)
            self.session.flush()
            event = self.incidents.link_alert(
                match.incident,
                model,
                reason=match.reason,
                received_at=received_at,
            )
            assert event is not None  # new link always records an event
            self.session.flush()
            return (
                self._outcome(
                    model,
                    outcome="joined",
                    created_incident=False,
                    duplicate_delivery=False,
                    correlation=match.reason,
                ),
                None,
            )

        reason = self.correlation.new_incident_reason(
            alert, self.settings.correlation_window_minutes
        )
        self.session.add(model)
        self.session.flush()
        incident, event = self.incidents.create_incident(
            alert,
            received_at=received_at,
            is_demo=is_demo,
            correlation_reason=reason,
            first_alert_id=model.id,
        )
        model.correlation = reason
        model.incident = incident
        self.session.flush()
        notification = self.notifications.enqueue_for_event(incident, event, is_demo=is_demo)
        return (
            self._outcome(
                model,
                outcome="created",
                created_incident=True,
                duplicate_delivery=False,
                correlation=reason,
            ),
            notification,
        )

    def _handle_duplicate(
        self,
        existing: Alert,
        alert: NormalizedAlert,
        *,
        received_at: datetime,
        delivery_id: str | None,
        is_demo: bool,
    ) -> tuple[AlertOutcome, object | None]:
        existing.occurrences += 1
        existing.last_seen_at = received_at
        if delivery_id:
            existing.delivery_id = delivery_id
        existing.severity = max_severity(existing.severity, alert.severity.value)
        state_changed = False
        correlated = existing.incident is not None
        if correlated:
            existing.incident.severity = max_severity(existing.incident.severity, existing.severity)

        if alert.status is AlertStatus.RESOLVED:
            if self.incidents.apply_source_resolution(existing, now=received_at):
                state_changed = True
                if existing.incident is not None:
                    self.incidents.record_event(
                        existing.incident,
                        event_type="alert_resolved",
                        message=f"Source resolved alert: {existing.title}",
                        occurred_at=received_at,
                        actor="Source monitoring",
                        automated=True,
                        details={"alert_id": existing.id, "fingerprint": existing.fingerprint},
                    )
            return (
                self._outcome(
                    existing,
                    outcome="updated" if state_changed else "deduplicated",
                    created_incident=False,
                    duplicate_delivery=True,
                    correlation=existing.correlation
                    or {
                        "rule": "fingerprint_replay",
                        "summary": "Repeat delivery matched the existing alert fingerprint.",
                        "matched_on": ["fingerprint"],
                    },
                ),
                None,
            )

        # Firing delivery.
        if existing.status == AlertStatus.RESOLVED.value:
            existing.status = AlertStatus.FIRING.value
            state_changed = True

        if existing.incident is None:
            match = self.correlation.find_match(self.session, alert, is_demo=is_demo)
            if match is None:
                reason = self.correlation.new_incident_reason(
                    alert, self.settings.correlation_window_minutes
                )
                incident, event = self.incidents.create_incident(
                    alert,
                    received_at=received_at,
                    is_demo=is_demo,
                    correlation_reason=reason,
                    first_alert_id=existing.id,
                )
                existing.incident = incident
                existing.correlation = reason
                self.session.flush()
                notification = self.notifications.enqueue_for_event(
                    incident, event, is_demo=is_demo
                )
                return (
                    self._outcome(
                        existing,
                        outcome="created",
                        created_incident=True,
                        duplicate_delivery=True,
                        correlation=reason,
                    ),
                    notification,
                )
            existing.correlation = match.reason
            self.incidents.link_alert(
                match.incident,
                existing,
                reason=match.reason,
                received_at=received_at,
                is_new=False,
            )
            self.incidents.record_event(
                match.incident,
                event_type="alert_refired",
                message=f"Previously resolved alert re-fired: {existing.title}",
                occurred_at=received_at,
                actor="Bamboo11y correlation",
                automated=True,
                details={"alert_id": existing.id, "reason": match.reason},
            )
            return (
                self._outcome(
                    existing,
                    outcome="joined",
                    created_incident=False,
                    duplicate_delivery=True,
                    correlation=match.reason,
                ),
                None,
            )

        incident = existing.incident
        if (
            incident.status == IncidentStatus.RESOLVED.value
            and existing.status == AlertStatus.FIRING.value
        ):
            reason = {
                "rule": "fingerprint_replay",
                "summary": (
                    "The same alert fingerprint fired again after its incident was resolved; "
                    "the incident was reopened and the prior resolution remains in the audit "
                    "timeline."
                ),
                "matched_on": ["fingerprint"],
                "note": "Source re-fires are the only automatic reopen path in the demo.",
            }
            event = self.incidents.reopen_from_source(
                incident, alert=existing, now=received_at, reason=reason
            )
            self.session.flush()
            notification = self.notifications.enqueue_for_event(incident, event, is_demo=is_demo)
            return (
                self._outcome(
                    existing,
                    outcome="reopened",
                    created_incident=False,
                    duplicate_delivery=True,
                    correlation=reason,
                ),
                notification,
            )

        if state_changed:
            self.incidents.record_event(
                incident,
                event_type="alert_refired",
                message=f"Alert returned to firing state: {existing.title}",
                occurred_at=received_at,
                actor="Source monitoring",
                automated=True,
                details={"alert_id": existing.id, "fingerprint": existing.fingerprint},
            )
        return (
            self._outcome(
                existing,
                outcome="updated" if state_changed else "deduplicated",
                created_incident=False,
                duplicate_delivery=True,
                correlation=existing.correlation
                or {
                    "rule": "fingerprint_replay",
                    "summary": "Repeat delivery matched the existing alert fingerprint.",
                    "matched_on": ["fingerprint"],
                },
            ),
            None,
        )

    def _build_alert(
        self,
        alert: NormalizedAlert,
        *,
        received_at: datetime,
        delivery_id: str | None,
        is_demo: bool,
    ) -> Alert:
        return Alert(
            fingerprint=alert.fingerprint,
            source=alert.source.value,
            source_alert_id=alert.source_alert_id,
            title=alert.title,
            description=alert.description,
            severity=alert.severity.value,
            status=alert.status.value,
            service=alert.service,
            environment=alert.environment,
            region=alert.region,
            labels=alert.labels,
            source_metadata=alert.source_metadata,
            enrichment=enrich_alert(alert, self.catalog),
            dedupe_key=alert.dedupe_key,
            occurred_at=alert.occurred_at,
            received_at=received_at,
            last_seen_at=received_at,
            occurrences=1,
            is_demo=is_demo,
            delivery_id=delivery_id,
        )

    @staticmethod
    def _outcome(
        alert: Alert,
        *,
        outcome: Outcome,
        created_incident: bool,
        duplicate_delivery: bool,
        correlation: dict[str, object],
    ) -> AlertOutcome:
        return AlertOutcome(
            alert_id=alert.id,
            fingerprint=alert.fingerprint,
            source_alert_id=alert.source_alert_id,
            title=alert.title,
            service=alert.service,
            environment=alert.environment,
            severity=alert.severity,
            status=alert.status,
            outcome=outcome,
            incident_id=alert.incident_id,
            created_incident=created_incident,
            duplicate_delivery=duplicate_delivery,
            correlation=correlation,
        )


def find_incident_for_alert(session: Session, alert_id: int) -> Incident | None:
    alert = session.get(Alert, alert_id)
    return alert.incident if alert else None
