from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from app.clock import FrozenClock
from tests.fixtures import first_outcome


def _oim_payload(
    *,
    app: str = "payments-api",
    check: str = "authorization-health",
    status: str = "critical",
    **overrides: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "app": app,
        "check": check,
        "status": status,
        "subject": "Authorization pipeline unhealthy",
        "description": "Synthetic health checks report authorization degraded.",
        "timestamp": None,
        "tags": {"service": "payments-api", "environment": "production"},
    }
    payload.update(overrides)
    return {key: value for key, value in payload.items() if value is not None} or {
        "app": app,
        "check": check,
        "status": status,
    }


def test_open_integration_critical_event_creates_incident_with_defaults(
    client: TestClient, frozen_clock: FrozenClock
) -> None:
    payload = _oim_payload(
        timestamp=frozen_clock.now().isoformat().replace("+00:00", "Z"),
        tags={"service": "payments-api", "env": "staging", "region": "us-east-1", "tier": "gold"},
    )

    response = client.post("/api/webhooks/alerts/open-integration", json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["received"] == 1
    assert body["created_alerts"] == 1
    assert body["incidents_created"] == 1
    assert body["notifications_created"] == 1
    outcome = first_outcome(body)
    assert outcome["outcome"] == "created"
    assert outcome["correlation"]["rule"] == "new_incident"

    alert = client.get(f"/api/alerts/{outcome['alert_id']}").json()
    assert alert["source"] == "open-integration"
    assert alert["status"] == "firing"
    assert alert["severity"] == "critical"
    assert alert["service"] == "payments-api"  # tag may override, app is fallback
    assert alert["environment"] == "staging"
    assert alert["region"] == "us-east-1"
    assert alert["title"] == "Authorization pipeline unhealthy"
    assert alert["dedupe_key"] == "payments-api:authorization-health"
    assert alert["source_metadata"]["integration"] == "open-integration"
    assert alert["source_metadata"]["state"] == "critical"
    assert "app" not in alert["labels"]  # identity is promoted, not duplicated in labels
    assert alert["enrichment"]["service_found"] is True
    assert alert["enrichment"]["tier"] == "critical"


def test_open_integration_app_falls_back_to_service_when_no_service_tag(
    client: TestClient,
) -> None:
    payload = _oim_payload(app="Inventory Service", check="queue-depth", status="warning")
    payload["tags"] = None

    response = client.post("/api/webhooks/alerts/open-integration", json=payload)
    assert response.status_code == 201, response.text
    alert = client.get(f"/api/alerts/{first_outcome(response.json())['alert_id']}").json()
    assert alert["service"] == "inventory-service"  # normalized identifier
    assert alert["severity"] == "medium"  # warning -> medium default
    assert alert["environment"] == "unknown"


def test_open_integration_acknowledged_event_stays_firing_and_visible(client: TestClient) -> None:
    response = client.post(
        "/api/webhooks/alerts/open-integration",
        json=_oim_payload(status="acknowledged", subject=None, description=None),
    )
    assert response.status_code == 201, response.text
    alert = client.get(f"/api/alerts/{first_outcome(response.json())['alert_id']}").json()
    assert alert["status"] == "firing"
    assert alert["severity"] == "high"
    assert alert["title"] == "authorization-health"  # falls back to check name
    assert alert["description"].endswith("reported acknowledged.")


def test_open_integration_ok_resolves_the_alert_without_a_new_incident(
    client: TestClient, frozen_clock: FrozenClock
) -> None:
    start = frozen_clock.now() - timedelta(minutes=1)
    firing = client.post(
        "/api/webhooks/alerts/open-integration",
        json=_oim_payload(timestamp=start.isoformat().replace("+00:00", "Z")),
    )
    incident_id = first_outcome(firing.json())["incident_id"]

    ok = _oim_payload(
        timestamp=frozen_clock.now().isoformat().replace("+00:00", "Z"),
        status="ok",
        subject=None,
        description=None,
    )
    response = client.post("/api/webhooks/alerts/open-integration", json=ok)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["incidents_created"] == 0
    outcome = first_outcome(body)
    assert outcome["outcome"] == "updated"

    alert = client.get(f"/api/alerts/{outcome['alert_id']}").json()
    assert alert["status"] == "resolved"
    # Severity is retained at the escalated max by design (ingestion escalates, never
    # de-escalates, on update) — resolution shows in status, not severity.
    assert alert["severity"] == "critical"

    detail = client.get(f"/api/incidents/{incident_id}").json()
    assert detail["incident"]["status"] == "open"  # source resolution != incident resolution
    assert detail["timeline"][-1]["event_type"] == "alert_resolved"
    assert detail["timeline"][-1]["automated"] is True


def test_open_integration_repeat_delivery_is_deduplicated(client: TestClient) -> None:
    payload = _oim_payload(subject=None, description=None)

    first = client.post("/api/webhooks/alerts/open-integration", json=payload)
    assert first.status_code == 201, first.text
    second = client.post("/api/webhooks/alerts/open-integration", json=payload)
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["created_alerts"] == 0
    assert body["duplicates"] == 1
    assert body["incidents_created"] == 0
    assert body["notifications_created"] == 0
    assert client.get("/api/alerts").json()["total"] == 1


def test_open_integration_unsupported_status_is_rejected_with_field_errors(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/webhooks/alerts/open-integration",
        json=_oim_payload(status="banana"),
    )
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "invalid_payload"
    assert any(error["field"] == "status" for error in body["errors"])


def test_open_integration_missing_required_fields_are_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/webhooks/alerts/open-integration",
        json={"check": "alone", "status": "ok"},
    )
    assert response.status_code == 422, response.text
    body = response.json()
    assert any(error["field"] == "app" for error in body["errors"])


def test_open_integration_non_scalar_tags_are_rejected_with_a_clear_error(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/webhooks/alerts/open-integration",
        json=_oim_payload(tags={"nested": {"too": "deep"}}),
    )
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "invalid_payload"
    assert "tags" in body["detail"]
