"""Deterministic, explainable alert-to-incident correlation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.base import NormalizedAlert
from app.config import Settings
from app.constants import IncidentStatus
from app.models import Alert, Incident
from app.services.catalog import Catalog


@dataclass(frozen=True)
class CorrelationMatch:
    incident: Incident
    reason: dict[str, object]


class CorrelationEngine:
    """Rule-based correlation with a deterministic evaluation order.

    Exact service/environment affinity wins over topology proximity. Candidates are always
    limited to the same environment and demo/live partition. Event time, not delivery time,
    drives the window so late-arriving alerts can still join a matching incident.
    """

    def __init__(self, settings: Settings, catalog: Catalog) -> None:
        self.settings = settings
        self.catalog = catalog

    def find_match(
        self, session: Session, alert: NormalizedAlert, *, is_demo: bool
    ) -> CorrelationMatch | None:
        candidates = session.scalars(
            select(Incident)
            .where(
                Incident.environment == alert.environment,
                Incident.is_demo.is_(is_demo),
                Incident.status != IncidentStatus.RESOLVED.value,
            )
            .order_by(Incident.updated_at.desc(), Incident.id.desc())
        ).all()
        if not candidates:
            return None

        # Aggregate event times directly so a newly-flushed alert in the same batch is
        # visible even if the relationship collection was already loaded.
        spans: dict[int, tuple[datetime, datetime]] = {}
        incident_ids = [candidate.id for candidate in candidates]
        for incident_id, first_at, last_at in session.execute(
            select(Alert.incident_id, func.min(Alert.occurred_at), func.max(Alert.occurred_at))
            .where(Alert.incident_id.in_(incident_ids))
            .group_by(Alert.incident_id)
        ):
            if incident_id is not None:
                spans[incident_id] = (first_at, last_at)

        exact_window = timedelta(minutes=self.settings.correlation_window_minutes)
        exact_matches: list[tuple[Incident, float]] = []
        topology_matches: list[tuple[Incident, float, str, str]] = []

        for incident in candidates:
            span = spans.get(incident.id)
            if span is None:
                continue
            nearest = _minutes_from_span(alert.occurred_at, span)
            if incident.primary_service == alert.service and _within_window(
                alert.occurred_at, span, exact_window
            ):
                exact_matches.append((incident, nearest))
                continue

            if (
                self.settings.topology_correlation_enabled
                and incident.primary_service != alert.service
                and _within_window(
                    alert.occurred_at,
                    span,
                    timedelta(minutes=self.settings.topology_window_minutes),
                )
            ):
                relation = self.catalog.relation_to(incident.primary_service, alert.service)
                if relation is not None:
                    topology_matches.append((incident, nearest, relation[0], relation[1]))

        if exact_matches:
            incident, nearest = exact_matches[0]
            return CorrelationMatch(
                incident=incident,
                reason={
                    "rule": "service_environment_window",
                    "summary": (
                        f"Joined the active {incident.primary_service} incident in "
                        f"{incident.environment}; the alert is within the configured "
                        f"{self.settings.correlation_window_minutes}-minute window."
                    ),
                    "matched_on": ["service", "environment", "event_time_window"],
                    "window_minutes": self.settings.correlation_window_minutes,
                    "minutes_from_nearest_alert": nearest,
                    "note": (
                        "Correlation groups signals for triage. It does not prove that the "
                        "alerts share a root cause."
                    ),
                },
            )

        if topology_matches:
            incident, nearest, relation, direction = topology_matches[0]
            relation_text = (
                "direct downstream dependency"
                if direction == "downstream"
                else "direct upstream caller"
            )
            arrow = (
                f"{incident.primary_service} → {alert.service}"
                if direction == "downstream"
                else f"{alert.service} → {incident.primary_service}"
            )
            return CorrelationMatch(
                incident=incident,
                reason={
                    "rule": "topology_proximity",
                    "summary": (
                        f"{alert.service} is a {relation_text} of "
                        f"{incident.primary_service} ({arrow}); the alert is within the "
                        f"{self.settings.topology_window_minutes}-minute topology window."
                    ),
                    "matched_on": ["service_topology", "environment", "event_time_window"],
                    "window_minutes": self.settings.topology_window_minutes,
                    "minutes_from_nearest_alert": nearest,
                    "topology": {
                        "relation": relation,
                        "direction": direction,
                        "edge": {"source": incident.primary_service, "target": alert.service}
                        if direction == "downstream"
                        else {"source": alert.service, "target": incident.primary_service},
                        "hops": 1,
                    },
                    "note": (
                        "Topology proximity is triage context, not proof of causation. The "
                        "services are connected in the catalog and the alert arrived inside "
                        "the topology window."
                    ),
                },
            )

        return None

    @staticmethod
    def new_incident_reason(alert: NormalizedAlert, window_minutes: int) -> dict[str, object]:
        return {
            "rule": "new_incident",
            "summary": (
                f"No open {alert.service} incident in {alert.environment} was inside the "
                f"{window_minutes}-minute correlation window; a new incident was opened."
            ),
            "matched_on": ["service", "environment", "event_time_window"],
            "window_minutes": window_minutes,
            "note": (
                "This is the first grouped signal. Later alerts may join if they match a "
                "documented rule and time window."
            ),
        }


def _within_window(candidate: datetime, span: tuple[datetime, datetime], window: timedelta) -> bool:
    start, end = span
    return start - window <= candidate <= end + window


def _minutes_from_span(candidate: datetime, span: tuple[datetime, datetime]) -> float:
    start, end = span
    if candidate < start:
        delta = start - candidate
    elif candidate > end:
        delta = candidate - end
    else:
        delta = timedelta(0)
    return round(delta.total_seconds() / 60, 1)


def candidate_alert_exists(session: Session, fingerprint: str) -> Alert | None:
    return session.scalar(select(Alert).where(Alert.fingerprint == fingerprint))
