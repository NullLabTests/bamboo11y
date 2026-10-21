"""Deterministic webhook fixtures shared by tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def alertmanager_payload(
    *,
    fingerprint: str = "fp-payments-1",
    service: str = "payments-api",
    environment: str = "production",
    severity: str = "critical",
    status: str = "firing",
    starts_at: datetime | None = None,
    alertname: str = "PaymentsAPIHighErrorRate",
    summary: str = "Payment errors are elevated",
    description: str = "The payment error rate crossed the burn threshold.",
    region: str = "us-east-1",
) -> dict[str, Any]:
    alert: dict[str, Any] = {
        "status": status,
        "fingerprint": fingerprint,
        "labels": {
            "alertname": alertname,
            "service": service,
            "environment": environment,
            "region": region,
            "severity": severity,
        },
        "annotations": {"summary": summary, "description": description},
    }
    if starts_at is not None:
        alert["startsAt"] = iso(starts_at)
    return {
        "version": "4",
        "status": status,
        "receiver": "bamboo11y-test",
        "groupKey": '{test="true"}',
        "alerts": [alert],
    }


def alertmanager_batch(alerts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "version": "4",
        "status": "firing",
        "receiver": "bamboo11y-test",
        "groupKey": '{test="batch"}',
        "alerts": alerts,
    }


def cloudwatch_alarm(
    *,
    alarm_name: str = "payments-api-p99-latency",
    arn: str | None = None,
    service: str = "payments-api",
    environment: str = "production",
    state: str = "ALARM",
    time: datetime | None = None,
    severity: str | None = "high",
    region: str = "us-east-1",
) -> dict[str, Any]:
    alarm: dict[str, Any] = {
        "AlarmName": alarm_name,
        "AlarmArn": arn or f"arn:aws:cloudwatch:us-east-1:123456789012:alarm:{alarm_name}",
        "AlarmDescription": "Synthetic test alarm",
        "NewStateValue": state,
        "NewStateReason": "Threshold crossed for three consecutive periods.",
        "Region": region,
        "AccountId": "123456789012",
        "Namespace": "Bamboo11y/Test",
        "Dimensions": [
            {"Name": "Service", "Value": service},
            {"Name": "Environment", "Value": environment},
        ],
    }
    if time is not None:
        alarm["StateChangeTime"] = iso(time)
    if severity:
        alarm["Severity"] = severity
    return alarm


def sns_wrap(alarm: dict[str, Any], *, message_id: str = "sns-test-1") -> dict[str, Any]:
    import json

    return {
        "Type": "Notification",
        "MessageId": message_id,
        "TopicArn": "arn:aws:sns:us-east-1:123456789012:bamboo11y-test",
        "Subject": f"ALARM: {alarm.get('AlarmName', 'alarm')}",
        "Timestamp": iso(datetime(2026, 10, 21, 11, 58, tzinfo=UTC)),
        "Message": json.dumps(alarm),
    }


def first_outcome(response_json: dict[str, Any]) -> dict[str, Any]:
    return response_json["outcomes"][0]
