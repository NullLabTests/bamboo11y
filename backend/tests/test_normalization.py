from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.clock import FrozenClock
from tests.fixtures import (
    alertmanager_payload,
    cloudwatch_alarm,
    first_outcome,
    sns_wrap,
)


def test_alertmanager_payload_is_normalized_enriched_and_correlated(
    client: TestClient, frozen_clock: FrozenClock
) -> None:
    starts_at = frozen_clock.now() - timedelta(minutes=4)
    payload = alertmanager_payload(
        fingerprint="am-normalization-1",
        severity="warning",
        starts_at=starts_at,
        summary="Payment authorization errors elevated",
        description="Error rate exceeded the burn threshold.",
        region="us-east-1",
    )

    response = client.post("/api/webhooks/alerts/prometheus", json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["received"] == 1
    assert body["created_alerts"] == 1
    assert body["incidents_created"] == 1
    assert body["notifications_created"] == 1
    outcome = first_outcome(body)
    assert outcome["outcome"] == "created"
    assert outcome["correlation"]["rule"] == "new_incident"
    assert outcome["incident_id"] is not None

    alert_response = client.get(f"/api/alerts/{outcome['alert_id']}")
    assert alert_response.status_code == 200
    alert = alert_response.json()
    assert alert["source"] == "prometheus"
    assert alert["severity"] == "medium"  # warning maps to medium
    assert alert["status"] == "firing"
    assert alert["service"] == "payments-api"
    assert alert["environment"] == "production"
    assert alert["region"] == "us-east-1"
    assert alert["title"] == "Payment authorization errors elevated"
    assert alert["occurred_at"].startswith(starts_at.isoformat()[:16])
    assert alert["labels"]["alertname"] == "PaymentsAPIHighErrorRate"
    assert alert["enrichment"]["service_found"] is True
    assert alert["enrichment"]["owner"] == "Payments Platform"
    assert alert["enrichment"]["tier"] == "critical"
    assert alert["dedupe_key"] == "am-normalization-1"
    assert len(alert["fingerprint"]) == 64

    incident = client.get(f"/api/incidents/{outcome['incident_id']}").json()
    assert incident["incident"]["primary_service"] == "payments-api"
    assert incident["alerts"][0]["correlation"]["rule"] == "new_incident"


def test_cloudwatch_sns_payload_normalizes_and_uses_dimensions(
    client: TestClient, frozen_clock: FrozenClock
) -> None:
    alarm = cloudwatch_alarm(
        alarm_name="payments-api-p99-latency",
        severity=None,
        time=frozen_clock.now() - timedelta(minutes=2),
    )
    payload = sns_wrap(alarm)

    response = client.post("/api/webhooks/alerts/cloudwatch", json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    alert = client.get(f"/api/alerts/{first_outcome(body)['alert_id']}").json()

    assert alert["source"] == "cloudwatch"
    assert alert["service"] == "payments-api"
    assert alert["environment"] == "production"
    assert alert["region"] == "us-east-1"
    assert alert["severity"] == "high"  # no severity field -> firing default
    assert alert["title"] == "payments-api-p99-latency"
    assert alert["source_metadata"]["sns_message_id"] == "sns-test-1"
    assert alert["source_metadata"]["account_id"] == "123456789012"
    assert alert["source_alert_id"].endswith("payments-api-p99-latency")


def test_cloudwatch_resolved_only_does_not_open_incident(client: TestClient) -> None:
    payload = cloudwatch_alarm(state="OK", severity="info", alarm_name="all-clear-alarm")
    response = client.post("/api/webhooks/alerts/cloudwatch", json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    outcome = first_outcome(body)
    assert outcome["outcome"] == "resolved_without_incident"
    assert outcome["incident_id"] is None
    assert body["incidents_created"] == 0

    incidents = client.get("/api/incidents").json()
    assert incidents["total"] == 0
    alert = client.get(f"/api/alerts/{outcome['alert_id']}").json()
    assert alert["status"] == "resolved"
    assert alert["severity"] == "info"


def test_alertmanager_batch_creates_multiple_alerts_atomically(
    client: TestClient, frozen_clock: FrozenClock
) -> None:
    now = frozen_clock.now()
    first = alertmanager_payload(fingerprint="batch-1", starts_at=now)
    second = alertmanager_payload(
        fingerprint="batch-2",
        service="notifications-worker",
        severity="medium",
        alertname="QueueBacklog",
        starts_at=now,
    )
    payload = {
        "version": "4",
        "status": "firing",
        "groupKey": "batch",
        "alerts": [first["alerts"][0], second["alerts"][0]],
    }
    response = client.post("/api/webhooks/alerts/prometheus", json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["received"] == 2
    assert body["created_alerts"] == 2
    assert body["incidents_created"] == 2
    assert all(item["outcome"] == "created" for item in body["outcomes"])
    assert client.get("/api/alerts").json()["total"] == 2


def test_alertmanager_accepts_rfc3339_with_offset_and_missing_timestamp(
    client: TestClient,
) -> None:
    payload = alertmanager_payload(fingerprint="offset-ts")
    payload["alerts"][0]["startsAt"] = "2026-10-21T09:30:00.000+02:00"
    response = client.post("/api/webhooks/alerts/prometheus", json=payload)
    assert response.status_code == 201
    alert = client.get(f"/api/alerts/{first_outcome(response.json())['alert_id']}").json()
    assert alert["occurred_at"].startswith("2026-10-21T07:30")

    missing = alertmanager_payload(fingerprint="missing-ts")
    response = client.post("/api/webhooks/alerts/prometheus", json=missing)
    assert response.status_code == 201
    alert = client.get(f"/api/alerts/{first_outcome(response.json())['alert_id']}").json()
    # Receipt time is the fallback at the frozen test clock.
    assert alert["occurred_at"].startswith(
        datetime(2026, 10, 21, 12, 0, tzinfo=UTC).isoformat()[:16]
    )


def test_future_timestamp_is_clamped_and_flagged(
    client: TestClient, frozen_clock: FrozenClock
) -> None:
    payload = alertmanager_payload(
        fingerprint="future-ts",
        starts_at=frozen_clock.now() + timedelta(hours=4),
    )
    response = client.post("/api/webhooks/alerts/prometheus", json=payload)
    assert response.status_code == 201
    alert = client.get(f"/api/alerts/{first_outcome(response.json())['alert_id']}").json()
    assert alert["occurred_at"].startswith(frozen_clock.now().isoformat()[:16])
    assert "future_timestamp_clamped_from" in alert["source_metadata"]
