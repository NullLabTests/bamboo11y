"""Change event ingestion/read endpoints."""

from __future__ import annotations

from datetime import UTC

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_catalog, get_clock, get_session, get_settings
from app.clock import Clock
from app.config import Settings
from app.errors import ApiError
from app.models import ChangeEvent
from app.schemas import (
    ChangeCreate,
    ChangeCreateResponse,
    ChangeListResponse,
)
from app.services.catalog import Catalog
from app.services.changes import ChangeService
from app.services.presenters import present_change

router = APIRouter(tags=["changes"])


@router.get("/api/changes", response_model=ChangeListResponse)
def list_changes(
    session: Session = Depends(get_session),
    service: str | None = Query(default=None, max_length=128),
    environment: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=200),
) -> ChangeListResponse:
    conditions = []
    if service:
        conditions.append(ChangeEvent.service == service)
    if environment:
        conditions.append(ChangeEvent.environment == environment)
    items = session.scalars(
        select(ChangeEvent)
        .where(*conditions)
        .order_by(ChangeEvent.occurred_at.desc(), ChangeEvent.id.desc())
        .limit(limit)
    ).all()
    return ChangeListResponse(items=[present_change(change) for change in items], total=len(items))


@router.post("/api/changes", response_model=ChangeCreateResponse, status_code=201)
def create_change(
    payload: ChangeCreate,
    response: Response,
    session: Session = Depends(get_session),
    catalog: Catalog = Depends(get_catalog),
    settings: Settings = Depends(get_settings),
    clock: Clock = Depends(get_clock),
) -> ChangeCreateResponse:
    service_id = payload.service.strip().lower()
    environment = payload.environment.strip().lower()
    service = catalog.get(service_id)
    if service is None:
        raise ApiError(
            422,
            "unknown_service",
            f"Service '{payload.service}' is not in the catalog.",
            errors=[{"field": "service", "message": "Use a service id from /api/services."}],
        )
    if environment not in service.environments:
        raise ApiError(
            422,
            "unknown_environment",
            f"Environment '{payload.environment}' is not configured for {service_id}.",
            errors=[
                {
                    "field": "environment",
                    "message": f"Allowed environments: {', '.join(service.environments)}.",
                }
            ],
        )

    occurred_at = payload.occurred_at
    if occurred_at is not None and occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=UTC)

    if payload.external_id:
        existing = session.scalar(
            select(ChangeEvent).where(ChangeEvent.external_id == payload.external_id)
        )
        if existing is not None:
            if existing.service != service_id or existing.environment != environment:
                raise ApiError(
                    409,
                    "change_external_id_conflict",
                    (
                        "A change with this external_id already exists for another "
                        "service/environment."
                    ),
                )
            response.status_code = 200
            return ChangeCreateResponse(item=present_change(existing), created=False)

    service_layer = ChangeService(session, settings, catalog, clock)
    change, created = service_layer.create(
        service=service_id,
        version=payload.version.strip(),
        environment=environment,
        region=payload.region,
        kind=payload.kind.value,
        summary=payload.summary.strip(),
        occurred_at=occurred_at,
        external_id=payload.external_id,
        source="bamboo11y-api",
        is_demo=False,
    )
    session.commit()
    if not created:
        response.status_code = 200
    return ChangeCreateResponse(item=present_change(change), created=created)
