from __future__ import annotations

from fastapi.testclient import TestClient

from app.clock import FrozenClock
from app.config import Settings
from app.main import create_app
from tests.fixtures import alertmanager_payload, cloudwatch_alarm


def test_unsupported_source_lists_supported_sources(client: TestClient) -> None:
    response = client.post("/api/webhooks/alerts/datadog", json={"alerts": []})
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "unsupported_source"
    assert body["supported_sources"] == ["cloudwatch", "open-integration", "prometheus"]
    assert body["request_id"]


def test_invalid_json_returns_helpful_error(client: TestClient) -> None:
    response = client.post(
        "/api/webhooks/alerts/prometheus",
        content='{"alerts": [}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "invalid_json"
    assert "line" in body["errors"][0]["message"]
    assert body["hints"]


def test_non_object_json_is_rejected(client: TestClient) -> None:
    response = client.post("/api/webhooks/alerts/cloudwatch", json=["not", "an", "object"])
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_payload"


def test_empty_alertmanager_group_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/webhooks/alerts/prometheus",
        json={"version": "4", "status": "firing", "alerts": []},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "invalid_payload"
    assert any("alerts" in item["field"] for item in body["errors"])


def test_cloudwatch_missing_alarm_name_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/webhooks/alerts/cloudwatch",
        json={"NewStateValue": "ALARM", "Region": "us-east-1"},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "invalid_payload"
    assert body["errors"]


def test_cloudwatch_invalid_state_is_rejected(client: TestClient) -> None:
    payload = cloudwatch_alarm()
    payload["NewStateValue"] = "PANIC"
    response = client.post("/api/webhooks/alerts/cloudwatch", json=payload)
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_payload"


def test_cloudwatch_sns_message_must_be_json(client: TestClient) -> None:
    response = client.post(
        "/api/webhooks/alerts/cloudwatch",
        json={"Type": "Notification", "Message": "AlarmName: plain text"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_payload"


def test_malformed_timestamp_is_rejected(client: TestClient) -> None:
    payload = alertmanager_payload()
    payload["alerts"][0]["startsAt"] = "not-a-date"
    response = client.post("/api/webhooks/alerts/prometheus", json=payload)
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_payload"


def test_oversized_payload_is_rejected_before_processing(
    settings: Settings, frozen_clock: FrozenClock
) -> None:
    limited = settings.model_copy(update={"max_payload_bytes": 1024})
    app = create_app(limited, clock=frozen_clock)
    try:
        with TestClient(app) as test_client:
            payload = alertmanager_payload(description="x" * 4000)
            response = test_client.post("/api/webhooks/alerts/prometheus", json=payload)
            assert response.status_code == 413
            assert response.json()["code"] == "payload_too_large"
            assert test_client.get("/api/alerts").json()["total"] == 0
    finally:
        app.state.engine.dispose()


def test_rate_limit_returns_retry_after_and_does_not_persist(
    settings: Settings, frozen_clock: FrozenClock
) -> None:
    limited = settings.model_copy(update={"rate_limit_per_minute": 2})
    app = create_app(limited, clock=frozen_clock)
    try:
        with TestClient(app) as test_client:
            payload = alertmanager_payload(fingerprint="rate-limit")
            assert (
                test_client.post("/api/webhooks/alerts/prometheus", json=payload).status_code == 201
            )
            assert (
                test_client.post("/api/webhooks/alerts/prometheus", json=payload).status_code == 200
            )
            response = test_client.post("/api/webhooks/alerts/prometheus", json=payload)
            assert response.status_code == 429
            body = response.json()
            assert body["code"] == "rate_limited"
            assert int(response.headers["Retry-After"]) >= 1
            assert response.headers["X-RateLimit-Remaining"] == "0"
            assert test_client.get("/api/alerts").json()["total"] == 1
    finally:
        app.state.engine.dispose()


def test_validation_error_for_incident_filter(client: TestClient) -> None:
    response = client.get("/api/incidents?severity=urgent")
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert body["errors"]


def test_unknown_api_route_returns_structured_404(client: TestClient) -> None:
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.json()["code"] == "http_error"
