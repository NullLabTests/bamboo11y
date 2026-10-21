from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from app.clock import FrozenClock
from tests.fixtures import alertmanager_payload, first_outcome


def test_demo_scenario_satisfies_the_published_contract(client: TestClient) -> None:
    response = client.post("/api/demo/run", json={"scenario": "payments_degradation"})
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["scenario"] == "payments_degradation"
    assert len(body["run_id"]) == 12
    assert body["alerts_received"] == 6
    assert body["unique_alerts"] == 5
    assert body["duplicate_deliveries"] == 1
    assert body["notifications_delivered"] == 3
    assert len(body["incidents"]) == 3
    assert body["primary_incident_id"] is not None
    assert body["primary_alert_fingerprint"]

    summary = body["summary"]
    assert summary["primary_incident_id"] == body["primary_incident_id"]
    assert summary["primary_incident_alert_count"] == 3
    assert summary["primary_incident_sources"] == ["cloudwatch", "prometheus"]
    assert summary["primary_incident_affected_services"] == ["checkout-api", "payments-api"]
    assert summary["unrelated_incident_count"] == 2
    assert summary["nearby_change"] == {
        "service": "payments-api",
        "version": "v2.14.0",
        "minutes_before_first_alert": 6.0,
        "relationship": "temporal_context_only",
    }
    assert "does not prove" in summary["disclaimer"]

    by_service = {incident["primary_service"]: incident for incident in body["incidents"]}
    assert set(by_service) == {"payments-api", "search-api", "notifications-worker"}
    assert by_service["payments-api"]["alert_count"] == 3
    assert by_service["payments-api"]["sources"] == ["cloudwatch", "prometheus"]
    assert by_service["search-api"]["environment"] == "staging"
    assert by_service["notifications-worker"]["alert_count"] == 1
    assert sorted(change["service"] for change in body["changes"]) == [
        "payments-api",
        "search-api",
    ]


def test_demo_primary_incident_explains_correlation_topology_and_change_context(
    client: TestClient,
) -> None:
    body = client.post("/api/demo/run", json={}).json()
    incident_id = body["primary_incident_id"]

    detail = client.get(f"/api/incidents/{incident_id}").json()
    assert detail["incident"]["alert_count"] == 3
    assert detail["incident"]["severity"] == "critical"
    assert len(detail["alerts"]) == 3
    rules = {alert["correlation"]["rule"] for alert in detail["alerts"]}
    assert rules == {"new_incident", "service_environment_window", "topology_proximity"}

    topology = detail["topology"]
    assert topology["service_found"] is True
    assert topology["focus_service"]["id"] == "payments-api"
    assert topology["owner"] == "Payments Platform"
    assert [service["id"] for service in topology["upstream"]] == ["checkout-api"]
    assert topology["affected_services"] == ["checkout-api", "payments-api"]

    assert detail["change_context"]["window_minutes"] == 120
    assert detail["change_context"]["first_alert_at"] is not None
    assert "not proof of causation" in detail["change_context"]["disclaimer"]
    assert len(detail["nearby_changes"]) == 1
    change = detail["nearby_changes"][0]
    assert change["service"] == "payments-api"
    assert change["version"] == "v2.14.0"
    assert change["relation"] == "before_first_alert"
    assert change["minutes_from_first_alert"] == -6.0
    assert change["relationship"] == "temporal_context_only"
    assert "not proof of causation" in change["disclaimer"]

    assert [event["event_type"] for event in detail["timeline"]] == [
        "opened",
        "alert_linked",
        "alert_linked",
    ]
    assert detail["timeline"][0]["automated"] is True
    assert len(detail["notifications"]) == 1
    assert detail["notifications"][0]["event_type"] == "opened"
    assert detail["notifications"][0]["status"] == "sent"


def test_demo_reset_only_removes_demo_rows(client: TestClient, frozen_clock: FrozenClock) -> None:
    live = client.post(
        "/api/webhooks/alerts/prometheus",
        json=alertmanager_payload(
            fingerprint="demo-payments-error-rate",
            starts_at=frozen_clock.now() - timedelta(minutes=6),
        ),
    )
    assert live.status_code == 201, live.text

    demo = client.post("/api/demo/run", json={}).json()
    assert demo["unique_alerts"] == 5
    assert client.get("/api/incidents").json()["total"] == 4
    assert client.get("/api/alerts").json()["total"] == 6

    reset = client.post("/api/demo/reset")
    assert reset.status_code == 200
    deleted = reset.json()["deleted"]
    assert deleted["incidents"] == 3
    assert deleted["alerts"] == 5
    assert deleted["notifications"] == 3
    assert deleted["changes"] == 2
    assert deleted["runs"] == 1

    incidents = client.get("/api/incidents").json()
    assert incidents["total"] == 1
    assert incidents["items"][0]["is_demo"] is False
    alerts = client.get("/api/alerts").json()
    assert alerts["total"] == 1
    assert alerts["items"][0]["is_demo"] is False
    assert alerts["items"][0]["dedupe_key"] == "demo-payments-error-rate"
    assert client.get("/api/changes").json()["total"] == 0


def test_demo_is_repeatable_and_replays_are_idempotent(client: TestClient) -> None:
    first = client.post("/api/demo/run", json={"fresh": True}).json()
    second = client.post("/api/demo/run", json={"fresh": True}).json()
    assert second["alerts_received"] == 6
    assert second["unique_alerts"] == 5
    assert second["duplicate_deliveries"] == 1
    assert len(second["incidents"]) == 3
    assert client.get("/api/incidents").json()["total"] == 3
    assert client.get("/api/alerts").json()["total"] == 5
    assert first["run_id"] != second["run_id"]

    replay = client.post("/api/demo/run", json={"fresh": False}).json()
    assert replay["alerts_received"] == 6
    assert replay["unique_alerts"] == 0
    assert replay["duplicate_deliveries"] == 6
    assert replay["notifications_delivered"] == 0
    assert len(replay["incidents"]) == 3
    assert client.get("/api/alerts").json()["total"] == 5
    assert client.get("/api/incidents").json()["total"] == 3


def test_demo_and_lifecycle_observe_metrics(client: TestClient) -> None:
    demo = client.post("/api/demo/run", json={"fresh": True}).json()
    text = client.get("/metrics").text
    assert "bamboo11y_incidents_created_total 3.0" in text
    assert 'bamboo11y_notifications_total{result="sent"} 3.0' in text

    acknowledged = client.patch(
        f"/api/incidents/{demo['primary_incident_id']}/status",
        json={"status": "acknowledged", "actor": "metrics-test"},
    )
    assert acknowledged.status_code == 200
    text = client.get("/metrics").text
    assert 'bamboo11y_notifications_total{result="sent"} 4.0' in text


def test_unknown_demo_scenario_is_rejected(client: TestClient) -> None:
    response = client.post("/api/demo/run", json={"scenario": "meteor_strike"})
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert client.get("/api/incidents").json()["total"] == 0


def test_demo_does_not_contaminate_live_correlation(
    client: TestClient, frozen_clock: FrozenClock
) -> None:
    demo = client.post("/api/demo/run", json={}).json()
    live = client.post(
        "/api/webhooks/alerts/prometheus",
        json=alertmanager_payload(
            fingerprint="live-after-demo",
            service="checkout-api",
            starts_at=frozen_clock.now() - timedelta(minutes=1),
        ),
    )
    assert live.status_code == 201, live.text
    outcome = first_outcome(live.json())
    assert outcome["outcome"] == "created"
    assert outcome["correlation"]["rule"] == "new_incident"
    assert outcome["incident_id"] not in {item["id"] for item in demo["incidents"]}

    detail = client.get(f"/api/incidents/{outcome['incident_id']}").json()
    assert detail["incident"]["is_demo"] is False
    assert detail["incident"]["alert_count"] == 1
    assert detail["nearby_changes"] == []
