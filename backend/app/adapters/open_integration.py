"""Open-integration-style event adapter.

Implements a vendor-neutral, one-object event contract for any monitoring system that can
POST JSON: an ``app``/``check`` identity, one of four lifecycle states, optional human
context, and arbitrary scalar dimension tags.

The state semantics intentionally mirror the pattern popularized by BigPanda's documented
Open Integration Manager concept and their MIT-licensed client/integration repositories
(``bigpanda-rb``, ``puppet-bigpanda``, ``check_graphite``) — an independent, open approach
to normalizing heterogeneous alert traffic. No code, schema files, or trademarks were
copied; the wire format here is this project's own implementation. See
``docs/inspirations.md`` for the full credit and non-affiliation note.

State mapping (documented in ``docs/spec.md``):

====================  ============  ==================  =================================
Payload ``status``    Alert status  Default severity    Rationale
====================  ============  ==================  =================================
``critical``          firing        critical            Needs an incident now
``warning``           firing        medium              Visible, may join an incident
``acknowledged``      firing        high                Owned upstream; stays visible
                                                        and correlatable
``ok``                resolved      info                Health restored
====================  ============  ==================  =================================

Identity: ``app`` + ``check`` form the dedupe key, so state transitions for the same
check flow through the same idempotency, escalation, and reopen mechanics as every
other source.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.adapters.base import (
    AdapterValidationError,
    NormalizedAlert,
    canonical_region,
    clean_text,
    ensure_safe_metadata,
    fingerprint_for,
    first_label,
    normalize_identifier,
    parse_timestamp,
    sanitize_labels,
    truncate,
)
from app.constants import (
    ENVIRONMENT_FALLBACK,
    SERVICE_FALLBACK,
    AlertStatus,
    Severity,
    Source,
    normalize_severity,
)


class OpenIntegrationEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    app: str = Field(min_length=1, max_length=80)
    check: str = Field(min_length=1, max_length=120)
    status: str = Field(min_length=1, max_length=32)
    subject: str | None = None
    description: str | None = None
    timestamp: str | None = None
    environment: str | None = None
    severity: str | None = None
    tags: dict[str, Any] | None = None


# Default severity per lifecycle state when the payload does not override it.
_STATE_DEFAULTS: dict[str, tuple[AlertStatus, Severity]] = {
    "critical": (AlertStatus.FIRING, Severity.CRITICAL),
    "warning": (AlertStatus.FIRING, Severity.MEDIUM),
    "acknowledged": (AlertStatus.FIRING, Severity.HIGH),
    "ok": (AlertStatus.RESOLVED, Severity.INFO),
}


class OpenIntegrationAdapter:
    source = Source.OPEN_INTEGRATION
    display_name = "Open Integration"
    description = (
        "Vendor-neutral app/check events with ok, critical, warning, or acknowledged "
        "states and arbitrary scalar tags, modeled on the open-integration pattern "
        "documented by BigPanda and mirrored in their MIT-licensed client repositories."
    )

    def normalize(
        self,
        payload: dict[str, Any],
        *,
        received_at: datetime,
        delivery_id: str | None = None,
    ) -> list[NormalizedAlert]:
        try:
            event = OpenIntegrationEvent.model_validate(payload)
        except ValidationError as exc:
            raise AdapterValidationError(
                "Open-integration event payload is invalid",
                errors=[
                    {
                        "field": ".".join(str(part) for part in error["loc"]),
                        "message": str(error["msg"]),
                    }
                    for error in exc.errors()[:20]
                ],
            ) from exc

        state = clean_text(event.status, max_length=32).lower()
        if state not in _STATE_DEFAULTS:
            raise AdapterValidationError(
                "Open-integration status is missing or unsupported",
                errors=[
                    {
                        "field": "status",
                        "message": "Expected one of: ok, critical, warning, acknowledged.",
                    }
                ],
            )
        status, default_severity = _STATE_DEFAULTS[state]

        try:
            tags = sanitize_labels(event.tags)
        except AdapterValidationError as exc:
            raise AdapterValidationError(
                "Open-integration tags are invalid",
                errors=exc.errors,
            ) from exc

        labels = sanitize_labels({"app": event.app, **tags})
        service = normalize_identifier(
            first_label(labels, "service", "Service") or event.app,
            fallback=SERVICE_FALLBACK,
        )
        environment = normalize_identifier(
            first_label(labels, "environment", "Environment", "env", "Env") or event.environment,
            fallback=ENVIRONMENT_FALLBACK,
            max_length=64,
        )

        explicit_severity = event.severity or first_label(labels, "severity", "Severity")
        if status is AlertStatus.RESOLVED:
            severity = Severity.INFO
        elif explicit_severity:
            severity = normalize_severity(explicit_severity, source=self.source)
        else:
            severity = default_severity

        occurred_at = parse_timestamp(event.timestamp, fallback=received_at, field="timestamp")

        dedupe_key = truncate(f"{event.app}:{event.check}", 255)
        title = clean_text(event.subject, max_length=300) or clean_text(event.check, max_length=300)
        description = (
            clean_text(event.description, max_length=4000)
            or clean_text(event.subject, max_length=4000)
            or f"{event.app} {event.check} reported {state}."
        )
        metadata = ensure_safe_metadata(
            {
                "integration": "open-integration",
                "state": state,
                "check": event.check,
                "delivery_id": delivery_id,
            }
        )

        return [
            NormalizedAlert(
                source=self.source,
                source_alert_id=truncate(dedupe_key, 255),
                dedupe_key=truncate(dedupe_key, 255),
                fingerprint=fingerprint_for(self.source, dedupe_key),
                title=title,
                description=description,
                severity=severity,
                status=status,
                service=service,
                environment=environment,
                region=canonical_region(first_label(labels, "region", "zone")),
                labels={key: value for key, value in labels.items() if key != "app"},
                source_metadata=metadata,
                occurred_at=occurred_at.astimezone(UTC),
            )
        ]
