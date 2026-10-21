"""CloudWatch alarm state-change adapter.

Supports both a direct EventBridge/state-change object and the SNS notification wrapper
that CloudWatch commonly posts to HTTP endpoints. The SNS envelope's ``Message`` is parsed
as JSON; a plain-text message is rejected instead of being guessed at.
"""

from __future__ import annotations

import json
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


class CloudWatchDimension(BaseModel):
    model_config = ConfigDict(extra="allow")

    Name: str
    Value: str


class CloudWatchTag(BaseModel):
    model_config = ConfigDict(extra="allow")

    Key: str
    Value: str


class CloudWatchAlarm(BaseModel):
    model_config = ConfigDict(extra="allow")

    AlarmName: str = Field(min_length=1, max_length=255)
    AlarmArn: str | None = None
    AlarmDescription: str | None = None
    NewStateValue: str | None = None
    NewStateReason: str | None = None
    StateChangeTime: str | None = None
    Region: str | None = None
    AccountId: str | None = None
    Namespace: str | None = None
    Severity: str | None = None
    Environment: str | None = None
    Dimensions: list[CloudWatchDimension] = Field(default_factory=list, max_length=30)
    Tags: list[CloudWatchTag] = Field(default_factory=list, max_length=30)


class CloudWatchAdapter:
    source = Source.CLOUDWATCH
    display_name = "AWS CloudWatch"
    description = (
        "Alarm state changes, direct or inside an SNS envelope. Service/environment come "
        "from Dimensions or Tags; identity from the alarm ARN or account/region/alarm name."
    )

    def normalize(
        self,
        payload: dict[str, Any],
        *,
        received_at: datetime,
        delivery_id: str | None = None,
    ) -> list[NormalizedAlert]:
        alarm_payload, envelope = self._unwrap(payload)
        try:
            alarm = CloudWatchAlarm.model_validate(alarm_payload)
        except ValidationError as exc:
            raise AdapterValidationError(
                "CloudWatch alarm payload is invalid",
                errors=[
                    {
                        "field": ".".join(str(part) for part in error["loc"]),
                        "message": str(error["msg"]),
                    }
                    for error in exc.errors()[:20]
                ],
            ) from exc
        return [
            self._normalize_alarm(
                alarm,
                received_at=received_at,
                delivery_id=delivery_id,
                envelope=envelope,
            )
        ]

    def _unwrap(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
        if "AlarmName" in payload:
            return payload, None
        message = payload.get("Message")
        if isinstance(message, str):
            try:
                inner = json.loads(message)
            except json.JSONDecodeError as exc:
                raise AdapterValidationError(
                    "SNS Message does not contain a CloudWatch alarm JSON document",
                    errors=[
                        {
                            "field": "Message",
                            "message": (
                                "Expected a JSON string containing AlarmName and state fields."
                            ),
                        }
                    ],
                ) from exc
            if not isinstance(inner, dict):
                raise AdapterValidationError(
                    "SNS Message must decode to an alarm object",
                    errors=[{"field": "Message", "message": "Expected a JSON object."}],
                )
            envelope = {
                "sns_message_id": payload.get("MessageId"),
                "sns_topic_arn": payload.get("TopicArn"),
                "sns_subject": payload.get("Subject"),
                "sns_timestamp": payload.get("Timestamp"),
            }
            return inner, envelope
        raise AdapterValidationError(
            "CloudWatch payload must include AlarmName or an SNS Message envelope",
            errors=[
                {
                    "field": "AlarmName",
                    "message": "Missing AlarmName. If using SNS, include a JSON Message field.",
                }
            ],
        )

    def _normalize_alarm(
        self,
        alarm: CloudWatchAlarm,
        *,
        received_at: datetime,
        delivery_id: str | None,
        envelope: dict[str, Any] | None,
    ) -> NormalizedAlert:
        state = clean_text(alarm.NewStateValue, max_length=32).upper()
        if state not in {"ALARM", "OK", "INSUFFICIENT_DATA"}:
            raise AdapterValidationError(
                "CloudWatch NewStateValue is missing or unsupported",
                errors=[
                    {
                        "field": "NewStateValue",
                        "message": "Expected ALARM, OK, or INSUFFICIENT_DATA.",
                    }
                ],
            )
        status = AlertStatus.RESOLVED if state == "OK" else AlertStatus.FIRING

        dimension_labels = {item.Name: item.Value for item in alarm.Dimensions}
        tag_labels = {item.Key: item.Value for item in alarm.Tags}
        combined = {**tag_labels, **dimension_labels}
        labels = sanitize_labels(combined)
        service = normalize_identifier(
            first_label(labels, "service", "Service", "application", "Application"),
            fallback=SERVICE_FALLBACK,
        )
        environment = normalize_identifier(
            first_label(labels, "environment", "Environment", "env", "Env") or alarm.Environment,
            fallback=ENVIRONMENT_FALLBACK,
            max_length=64,
        )
        explicit_severity = alarm.Severity or first_label(labels, "severity", "Severity")
        if explicit_severity:
            severity = normalize_severity(explicit_severity, source=Source.CLOUDWATCH)
        elif status is AlertStatus.RESOLVED:
            severity = Severity.INFO
        else:
            severity = Severity.HIGH

        occurred_at = parse_timestamp(
            alarm.StateChangeTime
            or (envelope or {}).get("sns_timestamp")
            or (envelope or {}).get("Timestamp"),
            fallback=received_at,
            field="StateChangeTime",
        )
        region = canonical_region(alarm.Region)
        dedupe_key = clean_text(alarm.AlarmArn, max_length=255) or clean_text(
            f"{region or 'unknown'}:{alarm.AccountId or 'unknown'}:{alarm.AlarmName}",
            max_length=255,
        )
        title = clean_text(alarm.AlarmName, max_length=300) or "CloudWatch alarm"
        description = (
            clean_text(alarm.NewStateReason, max_length=4000)
            or clean_text(alarm.AlarmDescription, max_length=4000)
            or f"CloudWatch alarm entered {state}."
        )
        metadata = ensure_safe_metadata(
            {
                "integration": "cloudwatch",
                "state": state,
                "account_id": alarm.AccountId,
                "namespace": alarm.Namespace,
                "alarm_arn": alarm.AlarmArn,
                "delivery_id": delivery_id,
                "sns_message_id": (envelope or {}).get("sns_message_id"),
                "sns_subject": (envelope or {}).get("sns_subject"),
            }
        )

        return NormalizedAlert(
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
            region=region,
            labels=labels,
            source_metadata=metadata,
            occurred_at=occurred_at.astimezone(UTC),
        )
