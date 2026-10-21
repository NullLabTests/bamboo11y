"""Deterministic demo scenario endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_catalog, get_clock, get_session, get_settings
from app.clock import Clock
from app.config import Settings
from app.errors import ApiError
from app.schemas import DemoResetResponse, DemoResponse, DemoRunRequest
from app.services.catalog import Catalog
from app.services.demo import DemoService, ScenarioError

router = APIRouter(tags=["demo"])


@router.post("/api/demo/run", response_model=DemoResponse, status_code=201)
def run_demo(
    payload: DemoRunRequest,
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    catalog: Catalog = Depends(get_catalog),
    clock: Clock = Depends(get_clock),
) -> DemoResponse:
    service = DemoService(session, settings, catalog, clock)
    try:
        result = service.run(scenario=payload.scenario, fresh=payload.fresh)
    except ScenarioError as exc:
        session.rollback()
        raise ApiError(422, "unknown_scenario", str(exc)) from exc
    except Exception:
        session.rollback()
        raise
    metrics = request.app.state.metrics
    metrics.observe_incident_created(result.incidents_created)
    if result.notifications_delivered:
        metrics.observe_notification_result("sent", result.notifications_delivered)
    return DemoResponse(
        run_id=result.run_id,
        scenario=result.scenario,
        primary_incident_id=result.primary_incident_id,
        primary_alert_fingerprint=result.primary_alert_fingerprint,
        incidents=result.incidents,
        alerts_received=result.alerts_received,
        unique_alerts=result.unique_alerts,
        duplicate_deliveries=result.duplicate_deliveries,
        notifications_delivered=result.notifications_delivered,
        changes=result.changes,
        summary=result.summary,
    )


@router.post("/api/demo/reset", response_model=DemoResetResponse)
def reset_demo(
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    catalog: Catalog = Depends(get_catalog),
    clock: Clock = Depends(get_clock),
) -> DemoResetResponse:
    service = DemoService(session, settings, catalog, clock)
    deleted = service.reset_demo_data()
    session.commit()
    return DemoResetResponse(deleted=deleted)
