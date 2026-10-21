"""ORM-to-API presenters. Routes stay thin and the dashboard gets one shape per entity."""

from __future__ import annotations

from datetime import datetime

from app.models import Alert, ChangeEvent, Incident, IncidentEvent, Notification
from app.schemas import (
    AlertRead,
    ChangeRead,
    EdgeRead,
    IncidentSummary,
    NearbyChangeRead,
    NotificationRead,
    RelatedServiceRead,
    ServiceRead,
    TimelineEntryRead,
    TopologyContextRead,
)
from app.services.catalog import Catalog
from app.services.changes import CONTEXT_DISCLAIMER, NearbyChange


def present_alert(alert: Alert) -> AlertRead:
    return AlertRead.model_validate(alert)


def present_incident_summary(incident: Incident, *, now: datetime) -> IncidentSummary:
    alert_times = [alert.occurred_at for alert in incident.alerts]
    sources = sorted({alert.source for alert in incident.alerts})
    services = sorted({alert.service for alert in incident.alerts})
    age_seconds = max(0.0, (now - incident.created_at).total_seconds())
    return IncidentSummary(
        id=incident.id,
        title=incident.title,
        status=incident.status,
        severity=incident.severity,
        primary_service=incident.primary_service,
        environment=incident.environment,
        region=incident.region,
        created_at=incident.created_at,
        updated_at=incident.updated_at,
        acknowledged_at=incident.acknowledged_at,
        acknowledged_by=incident.acknowledged_by,
        resolved_at=incident.resolved_at,
        resolved_by=incident.resolved_by,
        resolution_note=incident.resolution_note,
        alert_count=len(incident.alerts),
        sources=sources,
        affected_services=services,
        age_seconds=round(age_seconds, 1),
        first_alert_at=min(alert_times) if alert_times else None,
        last_alert_at=max(alert_times) if alert_times else None,
        is_demo=incident.is_demo,
    )


def present_timeline(events: list[IncidentEvent]) -> list[TimelineEntryRead]:
    return [TimelineEntryRead.model_validate(event) for event in events]


def present_change(change: ChangeEvent) -> ChangeRead:
    return ChangeRead.model_validate(change)


def present_nearby_change(change: NearbyChange) -> NearbyChangeRead:
    base = present_change(change.change)
    return NearbyChangeRead(
        **base.model_dump(),
        minutes_from_first_alert=change.minutes_from_first_alert,
        relation=change.relation,
        relationship="temporal_context_only",
        disclaimer=CONTEXT_DISCLAIMER,
    )


def present_notification(notification: Notification) -> NotificationRead:
    return NotificationRead.model_validate(notification)


def present_service(service_id: str, catalog: Catalog) -> ServiceRead | None:
    service = catalog.get(service_id)
    if service is None:
        return None
    return ServiceRead(
        id=service.id,
        name=service.name,
        description=service.description,
        owner=service.owner,
        team=service.team,
        tier=service.tier,
        environments=service.environments,
        depends_on=service.depends_on,
        dependents=[item.id for item in catalog.direct_dependents(service.id)],
        repository=service.repository,
        runbook=service.runbook,
    )


def present_related(
    service_id: str, depth: int, path: list[str], catalog: Catalog
) -> RelatedServiceRead:
    service = present_service(service_id, catalog)
    assert service is not None
    return RelatedServiceRead(service=service, depth=depth, path=path)


def present_topology(incident: Incident, catalog: Catalog) -> TopologyContextRead:
    affected = sorted({alert.service for alert in incident.alerts})
    focus = present_service(incident.primary_service, catalog)
    if focus is None:
        return TopologyContextRead(
            focus_service=None,
            service_found=False,
            owner="Unmapped",
            team="unmapped",
            tier="unknown",
            affected_services=affected,
            upstream=[],
            downstream=[],
            transitive_upstream=[],
            transitive_downstream=[],
            edges=[],
            catalog_version=catalog.version,
            disclaimer=(
                "The primary service is not in config/services.yaml. Topology context is "
                "limited to alert labels until the catalog is updated."
            ),
        )

    upstream = [present_service(item.id, catalog) for item in catalog.direct_dependents(focus.id)]
    downstream = [
        present_service(item.id, catalog) for item in catalog.direct_dependencies(focus.id)
    ]
    edges: list[EdgeRead] = []
    for item in upstream:
        if item:
            edges.append(EdgeRead(source=item.id, target=focus.id))
    for item in downstream:
        if item:
            edges.append(EdgeRead(source=focus.id, target=item.id))
    transitive_up = [
        present_related(item.service_id, item.depth, item.path, catalog)
        for item in catalog.upstream(focus.id, depth=3)
    ]
    transitive_down = [
        present_related(item.service_id, item.depth, item.path, catalog)
        for item in catalog.downstream(focus.id, depth=3)
    ]
    return TopologyContextRead(
        focus_service=focus,
        service_found=True,
        owner=focus.owner,
        team=focus.team,
        tier=focus.tier,
        affected_services=affected,
        upstream=[item for item in upstream if item is not None],
        downstream=[item for item in downstream if item is not None],
        transitive_upstream=transitive_up,
        transitive_downstream=transitive_down,
        edges=edges,
        catalog_version=catalog.version,
        disclaimer=(
            "Topology comes from the checked-in service catalog. It is ownership and "
            "dependency context, not evidence that one symptom caused another."
        ),
    )
