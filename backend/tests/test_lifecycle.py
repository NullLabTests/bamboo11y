from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from app.clock import FrozenClock
from tests.fixtures import alertmanager_payload, first_outcome


def _open_incident(client: TestClient, clock: FrozenClock, fingerprint: str = "lifecycle-1") -> int:
    response = client.post(
        "/api/webhooks/alerts/prometheus",
        json=alertmanager_payload(
            fingerprint=fingerprint,
            starts_at=clock.now() - timedelta(minutes=2),
        ),
    )
    assert response.status_code == 201, response.text
    incident_id = first_outcome(response.json())["incident_id"]
    assert incident_id is not None
    return incident_id


def test_acknowledge_then_resolve_records_timeline_and_notifications(
    client: TestClient, frozen_clock: FrozenClock
) -> None:
    incident_id = _open_incident(client, frozen_clock)

    acknowledged = client.patch(
        f"/api/incidents/{incident_id}/status",
        json={"status": "acknowledged", "actor": "  Dana  ", "note": "Looking into it."},
    )
    assert acknowledged.status_code == 200, acknowledged.text
    body = acknowledged.json()
    assert body["changed"] is True
    assert body["notification_dispatched"] is True
    assert body["incident"]["status"] == "acknowledged"
    assert body["incident"]["acknowledged_by"] == "Dana"
    assert body["incident"]["acknowledged_at"] == frozen_clock.now().isoformat().replace(
        "+00:00", "Z"
    )

    repeat = client.patch(
        f"/api/incidents/{incident_id}/status",
        json={"status": "acknowledged", "actor": "Dana"},
    )
    assert repeat.status_code == 200
    assert repeat.json()["changed"] is False
    assert repeat.json()["notification_dispatched"] is False

    notifications_after_ack = client.get("/api/notifications").json()
    assert notifications_after_ack["counts"]["sent"] == 2  # opened + acknowledged

    resolved = client.patch(
        f"/api/incidents/{incident_id}/status",
        json={"status": "resolved", "actor": "Dana", "note": "Rolled back the canary."},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["changed"] is True
    assert resolved.json()["incident"]["status"] == "resolved"
    assert resolved.json()["incident"]["resolved_by"] == "Dana"
    assert resolved.json()["incident"]["resolution_note"] == "Rolled back the canary."

    repeat_resolved = client.patch(
        f"/api/incidents/{incident_id}/status",
        json={"status": "resolved", "actor": "Dana", "note": "Second click."},
    )
    assert repeat_resolved.status_code == 200
    assert repeat_resolved.json()["changed"] is False
    # A no-op action must not overwrite the original resolution note.
    assert repeat_resolved.json()["incident"]["resolution_note"] == "Rolled back the canary."

    detail = client.get(f"/api/incidents/{incident_id}").json()
    assert [event["event_type"] for event in detail["timeline"]] == [
        "opened",
        "acknowledged",
        "resolved",
    ]
    assert detail["timeline"][1]["actor"] == "Dana"
    assert detail["timeline"][1]["automated"] is False
    assert detail["timeline"][1]["details"]["note"] == "Looking into it."
    assert len(detail["notifications"]) == 3
    assert {item["event_type"] for item in detail["notifications"]} == {
        "opened",
        "acknowledged",
        "resolved",
    }


def test_direct_resolution_from_open_is_allowed(
    client: TestClient, frozen_clock: FrozenClock
) -> None:
    incident_id = _open_incident(client, frozen_clock, fingerprint="lifecycle-direct")
    response = client.patch(
        f"/api/incidents/{incident_id}/status",
        json={"status": "resolved", "actor": "on-call"},
    )
    assert response.status_code == 200
    assert response.json()["incident"]["status"] == "resolved"
    assert response.json()["incident"]["acknowledged_at"] is None


def test_invalid_transitions_are_rejected_and_audited_state_is_unchanged(
    client: TestClient, frozen_clock: FrozenClock
) -> None:
    incident_id = _open_incident(client, frozen_clock, fingerprint="lifecycle-invalid")
    assert (
        client.patch(
            f"/api/incidents/{incident_id}/status",
            json={"status": "resolved", "actor": "on-call"},
        ).status_code
        == 200
    )

    response = client.patch(
        f"/api/incidents/{incident_id}/status",
        json={"status": "acknowledged", "actor": "on-call"},
    )
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "invalid_transition"
    assert "Cannot move incident from resolved to acknowledged." in body["detail"]

    detail = client.get(f"/api/incidents/{incident_id}").json()
    assert detail["incident"]["status"] == "resolved"
    assert detail["timeline"][-1]["event_type"] == "resolved"


def test_control_characters_are_stripped_from_actor_and_blank_note_is_dropped(
    client: TestClient, frozen_clock: FrozenClock
) -> None:
    incident_id = _open_incident(client, frozen_clock, fingerprint="lifecycle-sanitize")
    response = client.patch(
        f"/api/incidents/{incident_id}/status",
        json={"status": "acknowledged", "actor": "\u0001", "note": "   "},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["incident"]["acknowledged_by"] == "local-operator"
    detail = client.get(f"/api/incidents/{incident_id}").json()
    assert detail["timeline"][-1]["details"]["note"] is None


def test_unknown_incident_actions_return_structured_404(client: TestClient) -> None:
    get_response = client.get("/api/incidents/9999")
    assert get_response.status_code == 404
    assert get_response.json()["code"] == "incident_not_found"

    patch_response = client.patch(
        "/api/incidents/9999/status",
        json={"status": "acknowledged", "actor": "on-call"},
    )
    assert patch_response.status_code == 404
    assert patch_response.json()["code"] == "incident_not_found"


def test_status_payload_is_strict(client: TestClient, frozen_clock: FrozenClock) -> None:
    incident_id = _open_incident(client, frozen_clock, fingerprint="lifecycle-strict")
    unknown_field = client.patch(
        f"/api/incidents/{incident_id}/status",
        json={"status": "acknowledged", "actor": "on-call", "reopen": True},
    )
    assert unknown_field.status_code == 422
    assert unknown_field.json()["code"] == "validation_error"

    reopen = client.patch(
        f"/api/incidents/{incident_id}/status",
        json={"status": "open", "actor": "on-call"},
    )
    assert reopen.status_code == 422
    assert reopen.json()["code"] == "validation_error"
