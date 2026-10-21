"""Shared normalized alert contract and normalization helpers."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from app.constants import AlertStatus, Severity, Source

MAX_LABELS = 50
MAX_LABEL_KEY = 100
MAX_LABEL_VALUE = 500
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_REGION_PATTERN = re.compile(r"^[a-z]{2}(?:-gov)?-[a-z]+-\d$")


class NormalizedAlert(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: Source
    source_alert_id: str
    dedupe_key: str
    fingerprint: str
    title: str
    description: str
    severity: Severity
    status: AlertStatus
    service: str
    environment: str
    region: str | None
    labels: dict[str, str]
    source_metadata: dict[str, Any]
    occurred_at: datetime


class AdapterValidationError(ValueError):
    """Structured, safe validation failure produced by an adapter."""

    def __init__(
        self,
        message: str,
        *,
        errors: list[dict[str, str]] | None = None,
        supported_sources: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.errors = errors or []
        self.supported_sources = supported_sources


class AlertSourceAdapter(Protocol):
    source: Source
    display_name: str
    description: str

    def normalize(
        self,
        payload: dict[str, Any],
        *,
        received_at: datetime,
        delivery_id: str | None = None,
    ) -> list[NormalizedAlert]: ...


def clean_text(value: object, *, max_length: int, default: str = "") -> str:
    """Sanitize untrusted text while preserving readable newlines/tabs."""

    if value is None:
        return default
    text = _CONTROL_CHARS.sub("", str(value)).strip()
    if not text:
        return default
    if len(text) > max_length:
        return text[: max_length - 1].rstrip() + "…"
    return text


def normalize_identifier(value: object, *, fallback: str, max_length: int = 128) -> str:
    """Normalize service/environment names into stable, catalog-friendly keys."""

    raw = clean_text(value, max_length=max_length).lower()
    if not raw:
        return fallback
    normalized = re.sub(r"[\s_]+", "-", raw)
    normalized = re.sub(r"[^a-z0-9.:/@-]+", "-", normalized)
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
    return normalized[:max_length] or fallback


def sanitize_labels(labels: object) -> dict[str, str]:
    if labels is None:
        return {}
    if not isinstance(labels, dict):
        raise AdapterValidationError(
            "labels must be an object of string keys and values",
            errors=[{"field": "labels", "message": "Expected an object."}],
        )
    if len(labels) > MAX_LABELS:
        raise AdapterValidationError(
            f"too many labels ({len(labels)}); maximum is {MAX_LABELS}",
            errors=[{"field": "labels", "message": f"Maximum {MAX_LABELS} labels are allowed."}],
        )
    result: dict[str, str] = {}
    for raw_key, raw_value in labels.items():
        if not isinstance(raw_key, str) or not isinstance(raw_value, (str, int, float, bool)):
            raise AdapterValidationError(
                "labels must contain string keys and scalar values",
                errors=[{"field": "labels", "message": "Keys and values must be scalar strings."}],
            )
        key = clean_text(raw_key, max_length=MAX_LABEL_KEY)
        value = clean_text(raw_value, max_length=MAX_LABEL_VALUE)
        if not key:
            continue
        result[key] = value
    return result


def first_label(labels: dict[str, str], *names: str) -> str | None:
    for name in names:
        value = labels.get(name)
        if value:
            return value
    # Labels from other tools are case-sensitive, but users commonly write `Service`.
    lowered = {key.lower(): value for key, value in labels.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value:
            return value
    return None


def parse_timestamp(value: object, *, fallback: datetime, field: str = "timestamp") -> datetime:
    if value in (None, ""):
        return fallback
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        # Source systems sometimes use epoch seconds; milliseconds are also common.
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000
        parsed = datetime.fromtimestamp(number, tz=UTC)
    elif isinstance(value, str):
        text = value.strip()
        if not text or text.startswith("0001-01-01"):
            return fallback
        # CloudWatch commonly emits +0000 while Python's fromisoformat accepts +00:00.
        text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)
        text = text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise AdapterValidationError(
                f"invalid {field} timestamp",
                errors=[{"field": field, "message": f"Could not parse timestamp: {text[:80]}"}],
            ) from exc
    else:
        raise AdapterValidationError(
            f"invalid {field} timestamp",
            errors=[{"field": field, "message": "Expected an ISO-8601 timestamp."}],
        )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def clamp_future_timestamp(
    value: datetime, *, now: datetime, tolerance_seconds: int = 300
) -> datetime:
    """Clamp implausibly future event times for deterministic correlation.

    The original source value is retained in metadata by adapters where useful. This guard
    prevents a malformed future timestamp from pinning an incident at the end of time.
    """

    if value > now + timedelta(seconds=tolerance_seconds):
        return now
    return value


def fingerprint_for(source: Source, dedupe_key: str) -> str:
    return hashlib.sha256(f"{source.value}|{dedupe_key}".encode()).hexdigest()


def stable_labels_hash(labels: dict[str, str]) -> str:
    canonical = json.dumps(labels, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]


def canonical_region(value: object) -> str | None:
    candidate = clean_text(value, max_length=64)
    if candidate and _REGION_PATTERN.match(candidate.lower()):
        return candidate.lower()
    return None


def truncate(value: str, max_length: int) -> str:
    return value if len(value) <= max_length else value[: max_length - 1] + "…"


def ensure_safe_metadata(data: dict[str, Any]) -> dict[str, Any]:
    """Only retain small, non-secret scalar/string metadata from payload wrappers."""

    safe: dict[str, Any] = {}
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            safe[clean_text(key, max_length=60)] = clean_text(value, max_length=300)
        elif isinstance(value, list) and all(
            isinstance(item, (str, int, float, bool)) for item in value
        ):
            safe[clean_text(key, max_length=60)] = [
                clean_text(item, max_length=100) for item in value[:20]
            ]
    return safe
