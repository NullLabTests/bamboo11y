"""Change events and incident-relative temporal context."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import Clock
from app.config import Settings
from app.models import ChangeEvent, Incident
from app.services.catalog import Catalog

CONTEXT_DISCLAIMER = (
    "Temporal proximity is context for investigation, not proof of causation. "
    "Bamboo11y does not calculate a root cause."
)


@dataclass(frozen=True)
class NearbyChange:
    change: ChangeEvent
    minutes_from_first_alert: float
    relation: str


class ChangeService:
    def __init__(
        self, session: Session, settings: Settings, catalog: Catalog, clock: Clock
    ) -> None:
        self.session = session
        self.settings = settings
        self.catalog = catalog
        self.clock = clock

    def create(
        self,
        *,
        service: str,
        version: str,
        environment: str,
        kind: str,
        summary: str,
        occurred_at: datetime | None,
        region: str | None = None,
        external_id: str | None = None,
        source: str = "bamboo11y-api",
        is_demo: bool = False,
    ) -> tuple[ChangeEvent, bool]:
        if external_id:
            existing = self.session.scalar(
                select(ChangeEvent).where(ChangeEvent.external_id == external_id)
            )
            if existing is not None:
                return existing, False
        change = ChangeEvent(
            external_id=external_id,
            service=service,
            version=version,
            environment=environment,
            region=region,
            kind=kind,
            summary=summary,
            occurred_at=occurred_at or self.clock.now(),
            source=source,
            is_demo=is_demo,
        )
        self.session.add(change)
        self.session.flush()
        return change, True

    def nearby_for_incident(self, incident: Incident) -> list[NearbyChange]:
        alert_times = [alert.occurred_at for alert in incident.alerts]
        if not alert_times:
            return []
        first_alert = min(alert_times)
        last_alert = max(alert_times)
        window = timedelta(minutes=self.settings.change_context_window_minutes)
        lower = first_alert - window
        upper = last_alert + window

        affected = {alert.service for alert in incident.alerts}
        related_services = set(affected)
        for service_id in affected:
            related_services.update(self.catalog.neighbors(service_id, depth=1))

        changes = self.session.scalars(
            select(ChangeEvent)
            .where(
                ChangeEvent.service.in_(related_services),
                ChangeEvent.environment == incident.environment,
                ChangeEvent.is_demo.is_(incident.is_demo),
                ChangeEvent.occurred_at >= lower,
                ChangeEvent.occurred_at <= upper,
            )
            .order_by(ChangeEvent.occurred_at.desc(), ChangeEvent.id.desc())
        ).all()
        results: list[NearbyChange] = []
        for change in changes:
            delta_minutes = round((change.occurred_at - first_alert).total_seconds() / 60, 1)
            relation = "before_first_alert" if delta_minutes < 0 else "after_first_alert"
            results.append(
                NearbyChange(
                    change=change,
                    minutes_from_first_alert=delta_minutes,
                    relation=relation,
                )
            )
        return results


def serialize_change(change: ChangeEvent) -> dict[str, Any]:
    return {
        "id": change.id,
        "external_id": change.external_id,
        "service": change.service,
        "version": change.version,
        "environment": change.environment,
        "region": change.region,
        "kind": change.kind,
        "summary": change.summary,
        "occurred_at": change.occurred_at,
        "source": change.source,
        "is_demo": change.is_demo,
    }
