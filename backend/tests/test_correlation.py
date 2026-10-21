from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.adapters.alertmanager import AlertmanagerAdapter
from app.clock import FrozenClock
from app.config import Settings
from app.main import create_app
from app.models import Alert, Incident
from app.services.correlation import CorrelationEngine
from tests.fixtures import alertmanager_payload, first_outcome


def _post(
    client: TestClient,
    clock: FrozenClock,
    *,
    fingerprint: str,
    service: str = "payments-api",
    environment: str = "production",
    minutes_ago: float = 0,
    severity: str = "critical",
) -> dict:
    response = client.post(
        "/api/webhooks/alerts/prometheus",
        json=alertmanager_payload(
            fingerprint=fingerprint,
            service=service,
            environment=environment,
            severity=severity,
            starts_at=clock.now() - timedelta(minutes=minutes_ago),
        ),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_same_service_joins_within_the_window(
    client: TestClient, frozen_clock: FrozenClock
) -> None:
    first = _post(client, frozen_clock, fingerprint="corr-a", minutes_ago=20)
    second = _post(client, frozen_clock, fingerprint="corr-b", minutes_ago=5)

    outcome = first_outcome(second)
    assert outcome["outcome"] == "joined"
    assert outcome["incident_id"] == first_outcome(first)["incident_id"]
    assert outcome["correlation"]["rule"] == "service_environment_window"
    assert outcome["correlation"]["window_minutes"] == 15
    assert outcome["correlation"]["minutes_from_nearest_alert"] == 15.0
    assert "does not prove" in outcome["correlation"]["note"]
    assert second["incidents_created"] == 0

    detail = client.get(f"/api/incidents/{outcome['incident_id']}").json()
    assert detail["incident"]["alert_count"] == 2
    assert detail["incident"]["sources"] == ["prometheus"]
    assert [alert["occurrences"] for alert in detail["alerts"]] == [1, 1]


def test_same_service_outside_the_window_opens_a_new_incident(
    client: TestClient, frozen_clock: FrozenClock
) -> None:
    first = _post(client, frozen_clock, fingerprint="window-old", minutes_ago=30)
    second = _post(client, frozen_clock, fingerprint="window-new", minutes_ago=0)

    outcome = first_outcome(second)
    assert outcome["outcome"] == "created"
    assert outcome["correlation"]["rule"] == "new_incident"
    assert outcome["incident_id"] != first_outcome(first)["incident_id"]
    assert second["incidents_created"] == 1
    assert client.get("/api/incidents").json()["total"] == 2


def test_late_arriving_alert_uses_event_time_not_delivery_time(
    client: TestClient, frozen_clock: FrozenClock
) -> None:
    first = _post(client, frozen_clock, fingerprint="late-latest", minutes_ago=1)
    # Delivered now, but the source says it started 14 minutes before "now": the event-time
    # distance to the incident span is 13 minutes, inside the 15-minute window.
    late = _post(client, frozen_clock, fingerprint="late-older", minutes_ago=14)

    outcome = first_outcome(late)
    assert outcome["outcome"] == "joined"
    assert outcome["incident_id"] == first_outcome(first)["incident_id"]
    assert outcome["correlation"]["minutes_from_nearest_alert"] == 13.0


def test_direct_dependency_joins_through_topology(
    client: TestClient, frozen_clock: FrozenClock
) -> None:
    payments = _post(client, frozen_clock, fingerprint="topo-payments", minutes_ago=5)
    checkout = _post(
        client,
        frozen_clock,
        fingerprint="topo-checkout",
        service="checkout-api",
        minutes_ago=0,
    )

    outcome = first_outcome(checkout)
    assert outcome["outcome"] == "joined"
    assert outcome["incident_id"] == first_outcome(payments)["incident_id"]
    reason = outcome["correlation"]
    assert reason["rule"] == "topology_proximity"
    assert reason["window_minutes"] == 10
    assert reason["topology"]["relation"] == "dependent"
    assert reason["topology"]["direction"] == "upstream"
    assert reason["topology"]["hops"] == 1
    assert reason["topology"]["edge"] == {"source": "checkout-api", "target": "payments-api"}
    assert "not proof of causation" in reason["note"]

    detail = client.get(f"/api/incidents/{outcome['incident_id']}").json()
    assert detail["incident"]["primary_service"] == "payments-api"
    assert detail["incident"]["affected_services"] == ["checkout-api", "payments-api"]
    assert detail["topology"]["service_found"] is True
    assert [service["id"] for service in detail["topology"]["upstream"]] == ["checkout-api"]
    assert [service["id"] for service in detail["topology"]["downstream"]] == [
        "postgres-orders",
        "fraud-check",
    ]


def test_topology_outside_its_shorter_window_does_not_join(
    client: TestClient, frozen_clock: FrozenClock
) -> None:
    payments = _post(client, frozen_clock, fingerprint="topo-far-payments", minutes_ago=30)
    checkout = _post(
        client,
        frozen_clock,
        fingerprint="topo-far-checkout",
        service="checkout-api",
        minutes_ago=0,
    )
    assert first_outcome(checkout)["outcome"] == "created"
    assert first_outcome(checkout)["incident_id"] != first_outcome(payments)["incident_id"]
    assert checkout["incidents_created"] == 1


def test_topology_correlation_can_be_disabled(
    settings: Settings, frozen_clock: FrozenClock
) -> None:
    disabled = settings.model_copy(update={"topology_correlation_enabled": False})
    app = create_app(disabled, clock=frozen_clock)
    try:
        with TestClient(app) as client:
            payments = _post(client, frozen_clock, fingerprint="topo-off-payments", minutes_ago=2)
            checkout = _post(
                client,
                frozen_clock,
                fingerprint="topo-off-checkout",
                service="checkout-api",
                minutes_ago=0,
            )
            assert first_outcome(checkout)["outcome"] == "created"
            assert first_outcome(checkout)["incident_id"] != first_outcome(payments)["incident_id"]
    finally:
        app.state.engine.dispose()


def test_environments_are_isolated(client: TestClient, frozen_clock: FrozenClock) -> None:
    production = _post(client, frozen_clock, fingerprint="env-prod", minutes_ago=2)
    staging = _post(
        client, frozen_clock, fingerprint="env-staging", environment="staging", minutes_ago=1
    )
    assert first_outcome(staging)["outcome"] == "created"
    assert first_outcome(staging)["incident_id"] != first_outcome(production)["incident_id"]
    assert staging["incidents_created"] == 1


def test_resolved_incidents_are_not_correlation_candidates(
    client: TestClient, frozen_clock: FrozenClock
) -> None:
    first = _post(client, frozen_clock, fingerprint="resolved-corr-a", minutes_ago=3)
    incident_id = first_outcome(first)["incident_id"]
    resolved = client.patch(
        f"/api/incidents/{incident_id}/status",
        json={"status": "resolved", "actor": "on-call", "note": "Recovered."},
    )
    assert resolved.status_code == 200

    second = _post(client, frozen_clock, fingerprint="resolved-corr-b", minutes_ago=1)
    assert first_outcome(second)["outcome"] == "created"
    assert second["incidents_created"] == 1
    assert first_outcome(second)["incident_id"] != incident_id


def test_exact_service_match_wins_over_topology_proximity(
    app, session: Session, frozen_clock: FrozenClock
) -> None:
    now = frozen_clock.now()

    def incident(service: str, offset: int) -> Incident:
        item = Incident(
            title=f"{service}: test",
            status="open",
            severity="critical",
            primary_service=service,
            environment="production",
            correlation_key=f"{service}:production",
            created_at=now - timedelta(minutes=offset),
            updated_at=now - timedelta(minutes=offset),
            is_demo=False,
        )
        session.add(item)
        session.flush()
        session.add(
            Alert(
                fingerprint=f"manual-{service}",
                source="prometheus",
                source_alert_id=service,
                title=f"{service} alert",
                description="test",
                severity="critical",
                status="firing",
                service=service,
                environment="production",
                labels={},
                source_metadata={},
                enrichment={},
                dedupe_key=service,
                occurred_at=now - timedelta(minutes=offset),
                received_at=now - timedelta(minutes=offset),
                last_seen_at=now - timedelta(minutes=offset),
                occurrences=1,
                is_demo=False,
                incident_id=item.id,
            )
        )
        return item

    payments = incident("payments-api", 10)
    checkout = incident("checkout-api", 8)
    session.flush()

    alert = AlertmanagerAdapter().normalize(
        alertmanager_payload(
            fingerprint="priority-payments",
            service="payments-api",
            starts_at=now,
        ),
        received_at=now,
    )[0]
    engine = CorrelationEngine(app.state.settings, app.state.catalog)
    match = engine.find_match(session, alert, is_demo=False)

    assert match is not None
    assert match.incident.id == payments.id
    assert match.incident.id != checkout.id
    assert match.reason["rule"] == "service_environment_window"
