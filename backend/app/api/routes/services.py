"""Service catalog and topology read endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_catalog, get_session
from app.errors import ApiError
from app.models import ChangeEvent
from app.schemas import (
    EdgeRead,
    ServiceCatalogResponse,
    ServiceDetailResponse,
)
from app.services.catalog import Catalog
from app.services.presenters import (
    present_change,
    present_related,
    present_service,
)

router = APIRouter(tags=["services"])


@router.get("/api/services", response_model=ServiceCatalogResponse)
def list_services(catalog: Catalog = Depends(get_catalog)) -> ServiceCatalogResponse:
    services = [present_service(service.id, catalog) for service in catalog.services]
    services = [service for service in services if service is not None]
    return ServiceCatalogResponse(
        services=services,
        edges=[EdgeRead(source=source, target=target) for source, target in catalog.edges()],
        environments=catalog.environments(),
        catalog_version=catalog.version,
    )


@router.get("/api/services/{service_id}", response_model=ServiceDetailResponse)
def get_service(
    service_id: str,
    session: Session = Depends(get_session),
    catalog: Catalog = Depends(get_catalog),
    environment: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=10, ge=1, le=50),
) -> ServiceDetailResponse:
    service = present_service(service_id, catalog)
    if service is None:
        raise ApiError(
            404,
            "service_not_found",
            f"Service '{service_id}' is not in the catalog.",
            hints=["Check config/services.yaml for the canonical service id."],
        )
    upstream = [present_service(item.id, catalog) for item in catalog.direct_dependents(service_id)]
    downstream = [
        present_service(item.id, catalog) for item in catalog.direct_dependencies(service_id)
    ]
    conditions = [ChangeEvent.service == service_id]
    if environment:
        conditions.append(ChangeEvent.environment == environment)
    changes = session.scalars(
        select(ChangeEvent)
        .where(*conditions)
        .order_by(ChangeEvent.occurred_at.desc(), ChangeEvent.id.desc())
        .limit(limit)
    ).all()
    focus_edges = [
        EdgeRead(source=item.id, target=service_id) for item in upstream if item is not None
    ] + [EdgeRead(source=service_id, target=item.id) for item in downstream if item is not None]
    return ServiceDetailResponse(
        service=service,
        upstream=[item for item in upstream if item is not None],
        downstream=[item for item in downstream if item is not None],
        transitive_upstream=[
            present_related(item.service_id, item.depth, item.path, catalog)
            for item in catalog.upstream(service_id, depth=3)
        ],
        transitive_downstream=[
            present_related(item.service_id, item.depth, item.path, catalog)
            for item in catalog.downstream(service_id, depth=3)
        ],
        edges=focus_edges,
        recent_changes=[present_change(change) for change in changes],
    )
