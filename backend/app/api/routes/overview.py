"""Overview dashboard endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_catalog, get_clock, get_session
from app.clock import Clock
from app.schemas import OverviewResponse
from app.services.catalog import Catalog
from app.services.overview import OverviewService

router = APIRouter(tags=["overview"])


@router.get("/api/overview", response_model=OverviewResponse)
def overview(
    session: Session = Depends(get_session),
    catalog: Catalog = Depends(get_catalog),
    clock: Clock = Depends(get_clock),
) -> OverviewResponse:
    return OverviewService(session, catalog, clock).build()
