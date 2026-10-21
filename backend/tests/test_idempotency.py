from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from app.clock import FrozenClock
from tests.fixtures import (
    alertmanager_batch,
    alertmanager_payload,
    cloudwatch_alarm,
    first_outcome,
    sns_wrap,
)


def test_replayed_delivery_is_recorded_once_without_duplicate_notifications(
    client: TestClient, frozen_clock: FrozenClock
) -> None:
    payload = alertmanager_payload(
        fingerprint="idem-replay",
        starts_at=frozen_clock.now() - timedelta(minutes=1),
    )

    first = client.post(
        "/api/webhooks/alerts/prometheus",
        json=payload,
        headers={"X-Bamboo11y-Delivery-Id": "delivery-1"},
    )
    assert first.status_code == 201, first.text
    first_body = first.json()
    assert first_body["created_alerts"] == 1
    assert first_body["duplicates"] == 0

    second = client.post(
        "/api/webhooks/alerts/prometheus",
        json=payload,
        headers={"Idempotency-Key": "delivery-2"},
    )
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body["created_alerts"] == 0
    assert second_body["duplicates"] == 1
    assert second_body["incidents_created"] == 0
    assert second_body["notifications_created"] == 0
    outcome = first_outcome(second_body)
    assert outcome["outcome"] == "deduplicated"
    assert outcome["duplicate_delivery"] is True
    assert outcome["incident_id"] == first_outcome(first_body)["incident_id"]

    alert = client.get(f"/api/alerts/{outcome['alert_id']}").json()
    assert alert["occurrences"] == 2
    assert alert["delivery_id"] == "delivery-2"
    assert alert["last_seen_at"] == frozen_clock.now().isoformat().replace("+00:00", "Z")

    assert client.get("/api/alerts").json()["total"] == 1
    assert client.get("/api/incidents").json()["total"] == 1
    notifications = client.get("/api/notifications").json()
    assert len(notifications["items"]) == 1
    assert notifications["counts"]["sent"] == 1


def test_duplicate_inside_one_batch_is_created_once(
    client: TestClient, frozen_clock: FrozenClock
) -> None:
    alert = alertmanager_payload(
        fingerprint="idem-batch", starts_at=frozen_clock.now() - timedelta(minutes=2)
    )["alerts"][0]
    response = client.post(
        "/api/webhooks/alerts/prometheus", json=alertmanager_batch([alert, alert])
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["received"] == 2
    assert body["created_alerts"] == 1
    assert body["duplicates"] == 1
    assert [item["outcome"] for item in body["outcomes"]] == ["created", "deduplicated"]
    assert client.get("/api/alerts").json()["total"] == 1
    assert client.get("/api/incidents").json()["total"] == 1


def test_source_resolution_updates_the_alert_and_keeps_the_incident_open(
    client: TestClient, frozen_clock: FrozenClock
) -> None:
    now = frozen_clock.now()
    firing = alertmanager_payload(fingerprint="idem-resolve", starts_at=now - timedelta(minutes=3))
    created = client.post("/api/webhooks/alerts/prometheus", json=firing)
    assert created.status_code == 201
    incident_id = first_outcome(created.json())["incident_id"]

    resolved = alertmanager_payload(
        fingerprint="idem-resolve",
        status="resolved",
        starts_at=now - timedelta(minutes=3),
    )
    resolved["alerts"][0]["endsAt"] = now.isoformat().replace("+00:00", "Z")
    response = client.post("/api/webhooks/alerts/prometheus", json=resolved)
    assert response.status_code == 200, response.text
    body = response.json()
    assert first_outcome(body)["outcome"] == "updated"
    assert body["duplicates"] == 1

    alert = client.get(f"/api/alerts/{first_outcome(body)['alert_id']}").json()
    assert alert["status"] == "resolved"
    detail = client.get(f"/api/incidents/{incident_id}").json()
    assert detail["incident"]["status"] == "open"
    assert detail["timeline"][-1]["event_type"] == "alert_resolved"
    assert detail["timeline"][-1]["automated"] is True

    # A firing replay of the same fingerprint while the incident is still open is an
    # update, not a new incident and not a reopen.
    refire = client.post("/api/webhooks/alerts/prometheus", json=firing)
    assert refire.status_code == 200
    body = refire.json()
    assert first_outcome(body)["outcome"] == "updated"
    assert body["incidents_created"] == 0
    detail = client.get(f"/api/incidents/{incident_id}").json()
    assert detail["incident"]["status"] == "open"
    assert detail["timeline"][-1]["event_type"] == "alert_refired"


def test_fingerprint_replay_after_resolution_reopens_the_incident(
    client: TestClient, frozen_clock: FrozenClock
) -> None:
    now = frozen_clock.now()
    firing = alertmanager_payload(fingerprint="idem-reopen", starts_at=now - timedelta(minutes=5))
    created = client.post("/api/webhooks/alerts/prometheus", json=firing)
    incident_id = first_outcome(created.json())["incident_id"]
    assert incident_id is not None

    resolve = client.patch(
        f"/api/incidents/{incident_id}/status",
        json={"status": "resolved", "actor": "on-call", "note": "Mitigated upstream."},
    )
    assert resolve.status_code == 200, resolve.text
    assert resolve.json()["incident"]["status"] == "resolved"
    notifications_before = len(client.get("/api/notifications").json()["items"])

    replay = client.post("/api/webhooks/alerts/prometheus", json=firing)
    assert replay.status_code == 200, replay.text
    body = replay.json()
    outcome = first_outcome(body)
    assert outcome["outcome"] == "reopened"
    assert outcome["incident_id"] == incident_id
    assert body["incidents_created"] == 0
    assert len(client.get("/api/notifications").json()["items"]) == notifications_before + 1

    detail = client.get(f"/api/incidents/{incident_id}").json()
    assert detail["incident"]["status"] == "open"
    assert detail["incident"]["resolved_at"] is None
    assert detail["incident"]["resolved_by"] is None
    assert detail["timeline"][-1]["event_type"] == "reopened"
    assert detail["timeline"][-1]["details"]["rule"] == "fingerprint_replay"
    assert [alert["status"] for alert in detail["alerts"]] == ["firing"]
    assert detail["alerts"][0]["occurrences"] == 2


def test_same_dedupe_key_from_different_sources_creates_distinct_alerts(
    client: TestClient, frozen_clock: FrozenClock
) -> None:
    arn = "arn:aws:cloudwatch:us-east-1:123456789012:alarm:payments-api-p99-latency"
    am_payload = alertmanager_payload(
        fingerprint=arn,
        starts_at=frozen_clock.now() - timedelta(minutes=2),
    )
    assert client.post("/api/webhooks/alerts/prometheus", json=am_payload).status_code == 201

    alarm = cloudwatch_alarm(
        alarm_name="payments-api-p99-latency",
        arn=arn,
        time=frozen_clock.now() - timedelta(minutes=1),
    )
    cw_response = client.post("/api/webhooks/alerts/cloudwatch", json=sns_wrap(alarm))
    assert cw_response.status_code == 201, cw_response.text
    # Same service and event-time window means the second signal joins the first incident,
    # while the source-scoped fingerprint keeps the alerts distinguishable.
    assert cw_response.json()["incidents_created"] == 0
    assert first_outcome(cw_response.json())["outcome"] == "joined"

    alerts = client.get("/api/alerts").json()
    assert alerts["total"] == 2
    fingerprints = {alert["fingerprint"] for alert in alerts["items"]}
    assert len(fingerprints) == 2
    assert {alert["source"] for alert in alerts["items"]} == {"cloudwatch", "prometheus"}
    incident = client.get(
        f"/api/incidents/{first_outcome(cw_response.json())['incident_id']}"
    ).json()
    assert incident["incident"]["alert_count"] == 2
    assert incident["incident"]["sources"] == ["cloudwatch", "prometheus"]
