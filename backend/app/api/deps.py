"""FastAPI dependencies backed by application state."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from app.clock import Clock
from app.config import Settings
from app.services.catalog import Catalog


def get_session(request: Request) -> Iterator[Session]:
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_clock(request: Request) -> Clock:
    return request.app.state.clock


def get_catalog(request: Request) -> Catalog:
    return request.app.state.catalog
