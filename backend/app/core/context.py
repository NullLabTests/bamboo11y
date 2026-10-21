"""Request-scoped context values used by logging and errors."""

from __future__ import annotations

from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("bamboo11y_request_id", default=None)
