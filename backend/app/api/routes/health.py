"""Health, readiness, and Prometheus endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app import __version__
from app.api.deps import get_session, get_settings
from app.config import Settings
from app.core.middleware import metrics_response
from app.models import Alert, Incident
from app.schemas import HealthResponse

router = APIRouter(tags=["operations"])


@router.get("/api/health", response_model=HealthResponse)
def api_health(
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> HealthResponse:
    session.execute(text("SELECT 1"))
    catalog = request.app.state.catalog
    return HealthResponse(
        status="ok",
        version=__version__,
        environment=settings.environment,
        database="ok",
        catalog_services=len(catalog.services),
        catalog_version=catalog.version,
        time=datetime.now(UTC),
    )


@router.get("/healthz", include_in_schema=False)
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
def readiness(
    request: Request,
    session: Session = Depends(get_session),
) -> JSONResponse:
    checks: dict[str, str] = {}
    ready = True
    try:
        session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "error"
        ready = False
    try:
        services = request.app.state.catalog.services
        checks["catalog"] = f"ok ({len(services)} services)"
    except Exception:
        checks["catalog"] = "error"
        ready = False
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not_ready", "checks": checks},
    )


@router.get("/api/stats", include_in_schema=False)
def stats(session: Session = Depends(get_session)) -> dict[str, int]:
    """Small operational counters, useful for smoke tests and support."""

    return {
        "alerts": int(session.scalar(select(func.count(Alert.id))) or 0),
        "incidents": int(session.scalar(select(func.count(Incident.id))) or 0),
        "active_incidents": int(
            session.scalar(
                select(func.count(Incident.id)).where(Incident.status.in_(("open", "acknowledged")))
            )
            or 0
        ),
    }


@router.get("/metrics", include_in_schema=False)
def prometheus_metrics(request: Request) -> Response:
    return metrics_response(request)
