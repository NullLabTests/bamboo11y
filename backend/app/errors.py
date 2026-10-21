"""Consistent API errors with safe, actionable detail."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.context import request_id_var

logger = logging.getLogger("bamboo11y.errors")


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        errors: list[dict[str, str]] | None = None,
        hints: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.errors = errors or []
        self.hints = hints or []
        self.context = context or {}


def error_body(
    *,
    detail: str,
    code: str,
    errors: list[dict[str, str]] | None = None,
    hints: list[str] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "detail": detail,
        "code": code,
        "request_id": request_id_var.get(),
        "errors": errors or [],
        "hints": hints or [],
    }
    if context:
        body.update(context)
    return body


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(
                detail=exc.message,
                code=exc.code,
                errors=exc.errors,
                hints=exc.hints,
                context=exc.context,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = [
            {
                "field": ".".join(str(part) for part in item.get("loc", ())),
                "message": str(item.get("msg", "Invalid value")),
            }
            for item in exc.errors()[:20]
        ]
        return JSONResponse(
            status_code=422,
            content=error_body(
                detail="Request validation failed",
                code="validation_error",
                errors=errors,
                hints=["Check the field names and value types in the API documentation."],
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(detail=detail, code="http_error"),
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # Never send stack traces or exception text to clients. The request ID is the bridge
        # to the structured server log without leaking internals.
        logger.exception(
            "Unhandled request error",
            extra={"method": request.method, "path": request.url.path},
        )
        return JSONResponse(
            status_code=500,
            content=error_body(
                detail="An unexpected server error occurred.",
                code="internal_error",
                hints=["Retry the request. If it persists, inspect the server log by request ID."],
            ),
        )
