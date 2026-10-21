"""Incident queue, detail context, and lifecycle actions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_catalog, get_clock, get_session, get_settings
from app.clock import Clock
from app.config import Settings
from app.constants import IncidentStatus, Severity
from app.errors import ApiError
from app.models import Alert, Incident
from app.schemas import (
    ChangeContextRead,
    IncidentActionResponse,
    IncidentDetailResponse,
    IncidentListResponse,
    IncidentStatusUpdate,
)
from app.services.catalog import Catalog
from app.services.changes import CONTEXT_DISCLAIMER, ChangeService
from app.services.incidents import IncidentService, TransitionError
from app.services.notifications import NotificationService
from app.services.presenters import (
    present_alert,
    present_incident_summary,
    present_nearby_change,
    present_notification,
    present_timeline,
    present_topology,
)

router = APIRouter(tags=["incidents"])


@router.get("/api/incidents", response_model=IncidentListResponse)
def list_incidents(
    session: Session = Depends(get_session),
    clock: Clock = Depends(get_clock),
    status: IncidentStatus | None = None,
    severity: Severity | None = None,
    service: str | None = Query(default=None, max_length=128),
    environment: str | None = Query(default=None, max_length=64),
    source: str | None = Query(default=None, max_length=32),
    active: bool | None = None,
    q: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> IncidentListResponse:
    conditions = []
    if status:
        conditions.append(Incident.status == status.value)
    if severity:
        conditions.append(Incident.severity == severity.value)
    if environment:
        conditions.append(Incident.environment == environment)
    if service:
        conditions.append(
            Incident.id.in_(select(Alert.incident_id).where(Alert.service == service))
        )
    if source:
        conditions.append(Incident.id.in_(select(Alert.incident_id).where(Alert.source == source)))
    if active is True:
        conditions.append(Incident.status != IncidentStatus.RESOLVED.value)
    elif active is False:
        conditions.append(Incident.status == IncidentStatus.RESOLVED.value)
    if q:
        needle = f"%{q.strip()}%"
        conditions.append(or_(Incident.title.ilike(needle), Incident.primary_service.ilike(needle)))

    total = int(session.scalar(select(func.count(Incident.id)).where(*conditions)) or 0)
    active_count = int(
        session.scalar(
            select(func.count(Incident.id)).where(Incident.status != IncidentStatus.RESOLVED.value)
        )
        or 0
    )
    items = session.scalars(
        select(Incident)
        .where(*conditions)
        .order_by(Incident.updated_at.desc(), Incident.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    now = clock.now()
    return IncidentListResponse(
        items=[present_incident_summary(incident, now=now) for incident in items],
        total=total,
        active_count=active_count,
    )


@router.get("/api/incidents/{incident_id}", response_model=IncidentDetailResponse)
def get_incident(
    incident_id: int,
    session: Session = Depends(get_session),
    catalog: Catalog = Depends(get_catalog),
    settings: Settings = Depends(get_settings),
    clock: Clock = Depends(get_clock),
) -> IncidentDetailResponse:
    incident = session.get(Incident, incident_id)
    if incident is None:
        raise ApiError(404, "incident_not_found", f"Incident {incident_id} was not found.")
    now = clock.now()
    changes = ChangeService(session, settings, catalog, clock).nearby_for_incident(incident)
    alert_times = [alert.occurred_at for alert in incident.alerts]
    first_alert = min(alert_times) if alert_times else None
    notifications = sorted(incident.notifications, key=lambda item: (item.created_at, item.id))
    timeline = sorted(incident.events, key=lambda item: (item.occurred_at, item.id))
    return IncidentDetailResponse(
        incident=present_incident_summary(incident, now=now),
        alerts=[present_alert(alert) for alert in incident.alerts],
        timeline=present_timeline(timeline),
        topology=present_topology(incident, catalog),
        nearby_changes=[present_nearby_change(change) for change in changes],
        change_context=ChangeContextRead(
            window_minutes=settings.change_context_window_minutes,
            first_alert_at=first_alert,
            disclaimer=CONTEXT_DISCLAIMER,
        ),
        notifications=[present_notification(item) for item in notifications],
    )


@router.patch(
    "/api/incidents/{incident_id}/status",
    response_model=IncidentActionResponse,
)
def update_incident_status(
    incident_id: int,
    payload: IncidentStatusUpdate,
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    clock: Clock = Depends(get_clock),
) -> IncidentActionResponse:
    incident = session.get(Incident, incident_id)
    if incident is None:
        raise ApiError(404, "incident_not_found", f"Incident {incident_id} was not found.")
    now = clock.now()
    incidents = IncidentService(session, clock)
    try:
        incident, event = incidents.transition(
            incident,
            IncidentStatus(payload.status),
            actor=payload.actor,
            note=payload.note,
            now=now,
        )
    except TransitionError as exc:
        session.rollback()
        raise ApiError(409, exc.code, exc.message) from exc

    notification_sent = False
    if event is not None:
        notifications = NotificationService(session, settings, clock)
        notifications.enqueue_for_event(incident, event, is_demo=incident.is_demo)
        session.commit()
        dispatch = notifications.dispatch_pending()
        notification_sent = dispatch.get("sent", 0) > 0
        metrics = request.app.state.metrics
        if dispatch.get("sent"):
            metrics.observe_notification_result("sent", dispatch["sent"])
        if dispatch.get("failed"):
            metrics.observe_notification_result("failed", dispatch["failed"])
    else:
        session.commit()

    return IncidentActionResponse(
        incident=present_incident_summary(incident, now=now),
        changed=event is not None,
        notification_dispatched=notification_sent,
    )
