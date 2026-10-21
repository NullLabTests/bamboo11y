"""Application factory and local SPA serving."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.routes import (
    alerts,
    changes,
    demo,
    health,
    incidents,
    integrations,
    overview,
    services,
)
from app.clock import Clock, SystemClock
from app.config import Settings, get_settings
from app.core.logging_config import configure_logging
from app.core.metrics import Metrics
from app.core.middleware import (
    PayloadLimitMiddleware,
    RateLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from app.core.rate_limit import SlidingWindowRateLimiter
from app.db import create_db_engine, create_session_factory, init_db
from app.errors import register_exception_handlers
from app.services.catalog import load_catalog


def create_app(
    settings: Settings | None = None,
    *,
    clock: Clock | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_logs=settings.log_json)
    catalog = load_catalog(settings.service_catalog_path)
    engine = create_db_engine(settings.database_url, echo=settings.database_echo)
    init_db(engine)
    session_factory = create_session_factory(engine)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        engine.dispose()

    app = FastAPI(
        title="Bamboo11y API",
        version=__version__,
        description=(
            "Independent, local-first AIOps incident-management demonstration. "
            "Rule-based correlation, transparent explanations, no external services required."
        ),
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.catalog = catalog
    app.state.clock = clock or SystemClock()
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.metrics = Metrics(catalog_services=len(catalog.services))
    app.state.rate_limiter = SlidingWindowRateLimiter(
        requests_per_minute=settings.rate_limit_per_minute
    )

    register_exception_handlers(app)

    # Middleware is added inner-to-outer; security headers wrap the full stack.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type", "Idempotency-Key", "X-Bamboo11y-Delivery-Id"],
        expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
    )
    app.add_middleware(PayloadLimitMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    for router in (
        overview.router,
        incidents.router,
        alerts.router,
        services.router,
        changes.router,
        integrations.router,
        demo.router,
        health.router,
    ):
        app.include_router(router)

    _configure_spa(app, settings.static_dir)
    return app


def _configure_spa(app: FastAPI, static_dir: Path) -> None:
    index = static_dir / "index.html"
    if not index.exists():
        return
    resolved_static = static_dir.resolve()

    assets = static_dir / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path.startswith(
            ("api/", "docs", "redoc", "openapi.json", "healthz", "readyz", "metrics")
        ) or full_path in {"api", "docs", "redoc"}:
            raise HTTPException(status_code=404, detail="Not found")
        if full_path:
            candidate = (resolved_static / full_path).resolve()
            if candidate.is_file() and resolved_static in candidate.parents:
                return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
