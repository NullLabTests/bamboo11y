"""Shared deterministic test fixtures."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.clock import FrozenClock
from app.config import Settings
from app.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXED_NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


@pytest.fixture
def frozen_clock() -> FrozenClock:
    return FrozenClock(FIXED_NOW)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'bamboo11y-test.db'}",
        service_catalog_path=REPO_ROOT / "config" / "services.yaml",
        static_dir=tmp_path / "static",
        correlation_window_minutes=15,
        topology_correlation_enabled=True,
        topology_window_minutes=10,
        change_context_window_minutes=120,
        rate_limit_per_minute=500,
        max_payload_bytes=1_000_000,
        log_level="CRITICAL",
        log_json=True,
    )


@pytest.fixture
def app(settings: Settings, frozen_clock: FrozenClock):
    application = create_app(settings, clock=frozen_clock)
    yield application
    application.state.engine.dispose()


@pytest.fixture
def client(app) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def session(app) -> Iterator[Session]:
    session = app.state.session_factory()
    try:
        yield session
    finally:
        session.close()
