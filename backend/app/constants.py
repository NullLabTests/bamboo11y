"""Shared enums and ordering helpers.

Domain code stores enum *values* as strings in SQLite but validates boundaries with the
enums. Keeping the order here makes severity escalation and UI sorting consistent.
"""

from __future__ import annotations

from enum import StrEnum


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class AlertStatus(StrEnum):
    FIRING = "firing"
    RESOLVED = "resolved"


class IncidentStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class Source(StrEnum):
    PROMETHEUS = "prometheus"
    CLOUDWATCH = "cloudwatch"
    OPEN_INTEGRATION = "open-integration"


class ChangeKind(StrEnum):
    DEPLOYMENT = "deployment"
    CONFIG = "config"
    ROLLBACK = "rollback"
    FEATURE_FLAG = "feature_flag"


SEVERITY_ORDER: dict[str, int] = {
    Severity.INFO.value: 0,
    Severity.LOW.value: 1,
    Severity.MEDIUM.value: 2,
    Severity.HIGH.value: 3,
    Severity.CRITICAL.value: 4,
}

ENVIRONMENT_FALLBACK = "unknown"
SERVICE_FALLBACK = "unmapped-service"


def max_severity(left: str, right: str) -> str:
    """Return the more severe of two normalized severities."""

    return left if SEVERITY_ORDER.get(left, 0) >= SEVERITY_ORDER.get(right, 0) else right


def normalize_severity(value: str | None, *, source: Source | None = None) -> Severity:
    """Map common severity vocabularies onto Bamboo11y's five levels.

    Alerts without a recognizable severity default to medium for Prometheus and high for
    CloudWatch firing states. A resolved CloudWatch state can pass ``source=None`` and is
    handled by the adapter.
    """

    raw = (value or "").strip().lower()
    mapping = {
        "critical": Severity.CRITICAL,
        "fatal": Severity.CRITICAL,
        "emergency": Severity.CRITICAL,
        "high": Severity.HIGH,
        "error": Severity.HIGH,
        "major": Severity.HIGH,
        "medium": Severity.MEDIUM,
        "warning": Severity.MEDIUM,
        "warn": Severity.MEDIUM,
        "low": Severity.LOW,
        "minor": Severity.LOW,
        "info": Severity.INFO,
        "informational": Severity.INFO,
        "debug": Severity.INFO,
    }
    if raw in mapping:
        return mapping[raw]
    if source is Source.CLOUDWATCH:
        return Severity.HIGH
    return Severity.MEDIUM


def severity_rank(value: str) -> int:
    return SEVERITY_ORDER.get(value, 0)
