"""Cross-cutting HTTP middleware: request IDs, logs, metrics, limits, security headers."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.context import request_id_var
from app.errors import error_body

logger = logging.getLogger("bamboo11y.request")
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        if request.url.path in {"/docs", "/redoc", "/openapi.json"}:
            # Swagger/ReDoc load their UI from jsDelivr. This relaxation is limited to the
            # local API documentation; the dashboard keeps a self-only policy.
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "img-src 'self' data: https://fastapi.tiangolo.com; "
                "frame-ancestors 'none'; base-uri 'self'",
            )
        else:
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
                "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
            )
        return response


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        supplied = request.headers.get("x-request-id")
        request_id = (
            supplied if supplied and _REQUEST_ID_PATTERN.fullmatch(supplied) else uuid.uuid4().hex
        )
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            duration = time.perf_counter() - started
            metrics = getattr(request.app.state, "metrics", None)
            if metrics is not None:
                metrics.observe_http(request.method, status, duration)
            logger.info(
                "request completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": status,
                    "duration_ms": round(duration * 1000, 2),
                },
            )
            request_id_var.reset(token)


class PayloadLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method in {"POST", "PUT", "PATCH"}:
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    declared = int(content_length)
                except ValueError:
                    declared = 0
                maximum = request.app.state.settings.max_payload_bytes
                if declared > maximum:
                    return _json_error(
                        request,
                        413,
                        detail=f"Request body exceeds the {maximum:,}-byte limit.",
                        code="payload_too_large",
                        hints=["Reduce the alert batch size or payload size."],
                        headers={"Connection": "close"},
                    )
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        if path.startswith("/api/webhooks/alerts/"):
            source = path.rstrip("/").rsplit("/", 1)[-1]
            client = request.client.host if request.client else "unknown"
            allowed, remaining, retry_after = request.app.state.rate_limiter.check(
                f"{client}:{source}"
            )
            if not allowed:
                request.app.state.metrics.observe_webhook(source, "rate_limited")
                return _json_error(
                    request,
                    429,
                    detail="Too many webhook requests for this source. Retry after the window.",
                    code="rate_limited",
                    hints=[
                        "The default limit is per client and source per API process.",
                        f"Retry after {retry_after} seconds or coalesce alerts into one delivery.",
                    ],
                    headers={
                        "Retry-After": str(retry_after),
                        "X-RateLimit-Limit": str(request.app.state.settings.rate_limit_per_minute),
                        "X-RateLimit-Remaining": "0",
                    },
                )
            response = await call_next(request)
            response.headers["X-RateLimit-Limit"] = str(
                request.app.state.settings.rate_limit_per_minute
            )
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            return response
        return await call_next(request)


def _json_error(
    request: Request,
    status: int,
    *,
    detail: str,
    code: str,
    hints: list[str] | None = None,
    headers: dict[str, str] | None = None,
) -> Response:
    from fastapi.responses import JSONResponse

    body = error_body(detail=detail, code=code, hints=hints)
    response = JSONResponse(status_code=status, content=body, headers=headers)
    response.headers["X-Request-ID"] = request_id_var.get() or ""
    return response


def metrics_response(request: Request) -> Response:
    session = request.app.state.session_factory()
    try:
        request.app.state.metrics.refresh_database_gauges(session)
    finally:
        session.close()
    return Response(
        content=generate_latest(request.app.state.metrics.registry),
        media_type=CONTENT_TYPE_LATEST,
    )


def json_loads_object(body: bytes) -> dict[str, object]:
    """Strict JSON object parser used by webhook routes."""

    value = json.loads(body)
    if not isinstance(value, dict):
        raise ValueError("JSON body must be an object")
    return value
