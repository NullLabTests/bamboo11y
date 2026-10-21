"""Structured JSON application logging."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.core.context import request_id_var


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        for key in ("method", "path", "status", "duration_ms", "source", "outcome"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True, default=str)


def configure_logging(level: str = "INFO", *, json_logs: bool = True) -> None:
    logger = logging.getLogger("bamboo11y")
    logger.setLevel(level)
    logger.propagate = False
    if logger.handlers:
        logger.handlers.clear()
    handler = logging.StreamHandler()
    if json_logs:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
    # The app emits its own structured request log; duplicate access lines are noise.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
