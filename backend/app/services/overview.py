"""Derived overview data for the command center."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.registry import ADAPTERS
from app.clock import Clock
from app.models import Alert, ChangeEvent, Incident
from app.schemas import (
    AlertVolumeBucketRead,
    OverviewMetricsRead,
    OverviewResponse,
    SourceHealthRead,
)
from app.services.catalog import Catalog
from app.services.presenters import present_change, present_incident_summary


class OverviewService:
    def __init__(self, session: Session, catalog: Catalog, clock: Clock) -> None:
        self.session = session
        self.catalog = catalog
        self.clock = clock

    def build(self) -> OverviewResponse:
        now = self.clock.now()
        since = now - timedelta(hours=24)
        alerts = self.session.scalars(select(Alert).where(Alert.received_at >= since)).all()
        active_incidents = self.session.scalars(
            select(Incident)
            .where(Incident.status != "resolved")
            .order_by(Incident.updated_at.desc(), Incident.id.desc())
        ).all()
        all_incidents = self.session.scalars(
            select(Incident).order_by(Incident.updated_at.desc())
        ).all()

        affected_services: set[str] = set()
        for incident in active_incidents:
            affected_services.update(alert.service for alert in incident.alerts)
        acknowledged = [
            (incident.acknowledged_at - incident.created_at).total_seconds()
            for incident in all_incidents
            if incident.acknowledged_at is not None
        ]
        mtta = round(mean(acknowledged), 1) if acknowledged else None

        severity_mix = dict.fromkeys(("critical", "high", "medium", "low", "info"), 0)
        for incident in active_incidents:
            if incident.severity in severity_mix:
                severity_mix[incident.severity] += 1

        source_counts = Counter(alert.source for alert in alerts)
        last_received: dict[str, datetime] = {}
        for alert in alerts:
            current = last_received.get(alert.source)
            if current is None or alert.received_at > current:
                last_received[alert.source] = alert.received_at

        source_health = []
        for source, adapter in sorted(ADAPTERS.items()):
            count = source_counts.get(source, 0)
            source_health.append(
                SourceHealthRead(
                    source=source,
                    display_name=adapter.display_name,
                    alerts_24h=count,
                    last_received_at=last_received.get(source),
                    status="receiving" if count else "quiet",
                )
            )

        recent_changes = self.session.scalars(
            select(ChangeEvent)
            .order_by(ChangeEvent.occurred_at.desc(), ChangeEvent.id.desc())
            .limit(5)
        ).all()

        return OverviewResponse(
            generated_at=now,
            metrics=OverviewMetricsRead(
                active_incidents=len(active_incidents),
                alerts_last_24h=len(alerts),
                affected_services=len(affected_services),
                mean_time_to_acknowledge_seconds=mtta,
                service_count=len(self.catalog.services),
            ),
            severity_mix=severity_mix,
            source_health=source_health,
            alert_volume=_alert_volume(alerts, now),
            recent_incidents=[
                present_incident_summary(incident, now=now) for incident in active_incidents[:6]
            ],
            recent_changes=[present_change(change) for change in recent_changes],
            demo_scenario="payments_degradation",
        )


def _alert_volume(alerts: list[Alert], now: datetime) -> list[AlertVolumeBucketRead]:
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    starts = [current_hour - timedelta(hours=offset) for offset in range(11, -1, -1)]
    counts = dict.fromkeys(starts, 0)
    for alert in alerts:
        bucket = alert.received_at.replace(minute=0, second=0, microsecond=0)
        if bucket in counts:
            counts[bucket] += 1
    return [AlertVolumeBucketRead(bucket_start=start, count=counts[start]) for start in starts]
