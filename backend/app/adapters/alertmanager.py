"""Prometheus Alertmanager webhook adapter."""

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
    stable_labels_hash,
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


class AlertmanagerAlert(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str | None = None
    labels: dict[str, Any] = Field(default_factory=dict)
    annotations: dict[str, Any] = Field(default_factory=dict)
    startsAt: str | None = None
    endsAt: str | None = None
    fingerprint: str | None = None
    generatorURL: str | None = None


class AlertmanagerPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    version: str | None = None
    status: str | None = None
    receiver: str | None = None
    groupKey: str | None = None
    alerts: list[AlertmanagerAlert] = Field(min_length=1, max_length=100)


class AlertmanagerAdapter:
    source = Source.PROMETHEUS
    display_name = "Prometheus Alertmanager"
    description = (
        "Native Alertmanager webhook groups. Service is read from service/app/job labels; "
        "severity from the severity label; identity from the alert fingerprint or labels."
    )

    def normalize(
        self,
        payload: dict[str, Any],
        *,
        received_at: datetime,
        delivery_id: str | None = None,
    ) -> list[NormalizedAlert]:
        try:
            parsed = AlertmanagerPayload.model_validate(payload)
        except ValidationError as exc:
            raise AdapterValidationError(
                "Alertmanager payload is invalid",
                errors=[
                    {
                        "field": ".".join(str(part) for part in error["loc"]),
                        "message": str(error["msg"]),
                    }
                    for error in exc.errors()[:20]
                ],
            ) from exc

        normalized: list[NormalizedAlert] = []
        for index, alert in enumerate(parsed.alerts):
            normalized.append(
                self._normalize_alert(
                    alert,
                    index=index,
                    top_level_status=parsed.status,
                    received_at=received_at,
                    delivery_id=delivery_id,
                    group_key=parsed.groupKey,
                    receiver=parsed.receiver,
                )
            )
        return normalized

    def _normalize_alert(
        self,
        alert: AlertmanagerAlert,
        *,
        index: int,
        top_level_status: str | None,
        received_at: datetime,
        delivery_id: str | None,
        group_key: str | None,
        receiver: str | None,
    ) -> NormalizedAlert:
        field_prefix = f"alerts[{index}]"
        labels = sanitize_labels(alert.labels)
        status_raw = (alert.status or top_level_status or "firing").strip().lower()
        if status_raw not in {AlertStatus.FIRING.value, AlertStatus.RESOLVED.value}:
            raise AdapterValidationError(
                "Alertmanager alert has an unsupported status",
                errors=[
                    {
                        "field": f"{field_prefix}.status",
                        "message": "Expected 'firing' or 'resolved'.",
                    }
                ],
            )

        service = normalize_identifier(
            first_label(labels, "service", "app", "job", "container"),
            fallback=SERVICE_FALLBACK,
        )
        environment = normalize_identifier(
            first_label(labels, "environment", "env", "deployment_environment"),
            fallback=ENVIRONMENT_FALLBACK,
            max_length=64,
        )
        severity = normalize_severity(first_label(labels, "severity", "level"))
        source_alert_id = clean_text(alert.fingerprint, max_length=255) or stable_labels_hash(
            labels
        )
        dedupe_key = clean_text(alert.fingerprint, max_length=255) or stable_labels_hash(labels)
        alert_name = clean_text(labels.get("alertname"), max_length=300)
        title = (
            clean_text(alert.annotations.get("summary"), max_length=300)
            or alert_name
            or "Prometheus alert"
        )
        description = (
            clean_text(alert.annotations.get("description"), max_length=4000)
            or alert_name
            or "No description provided by Alertmanager."
        )
        occurred_at = parse_timestamp(
            alert.startsAt, fallback=received_at, field=f"{field_prefix}.startsAt"
        )
        metadata = ensure_safe_metadata(
            {
                "integration": "alertmanager",
                "alertname": alert_name,
                "group_key": group_key,
                "receiver": receiver,
                "delivery_id": delivery_id,
                "fingerprint_supplied": bool(alert.fingerprint),
            }
        )

        return NormalizedAlert(
            source=self.source,
            source_alert_id=truncate(source_alert_id, 255),
            dedupe_key=truncate(dedupe_key, 255),
            fingerprint=fingerprint_for(self.source, dedupe_key),
            title=title,
            description=description,
            severity=Severity(severity),
            status=AlertStatus(status_raw),
            service=service,
            environment=environment,
            region=canonical_region(first_label(labels, "region")),
            labels=labels,
            source_metadata=metadata,
            occurred_at=occurred_at.astimezone(UTC),
        )
