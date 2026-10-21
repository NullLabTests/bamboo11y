from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from app.clock import FrozenClock
from tests.fixtures import (
    alertmanager_payload,
    cloudwatch_alarm,
    first_outcome,
    sns_wrap,
)


def _iso(value) -> str:
    return value.isoformat().replace("+00:00", "Z")


def test_clean_dashboard_state_is_explicit(client: TestClient, frozen_clock: FrozenClock) -> None:
    overview = client.get("/api/overview")
    assert overview.status_code == 200
    body = overview.json()
    assert body["metrics"] == {
        "active_incidents": 0,
        "alerts_last_24h": 0,
        "affected_services": 0,
        "mean_time_to_acknowledge_seconds": None,
        "service_count": 10,
    }
    assert body["severity_mix"] == {
        "critical": 0,
        "high": 0,
        "medium": 0,
        "low": 0,
        "info": 0,
    }
    assert len(body["alert_volume"]) == 12
    assert all(bucket["count"] == 0 for bucket in body["alert_volume"])
    assert body["recent_incidents"] == []
    assert body["recent_changes"] == []
    assert body["demo_scenario"] == "payments_degradation"
    assert [(source["source"], source["status"]) for source in body["source_health"]] == [
        ("cloudwatch", "quiet"),
        ("open-integration", "quiet"),
        ("prometheus", "quiet"),
    ]
    assert body["generated_at"] == _iso(frozen_clock.now())

    assert client.get("/api/incidents").json() == {
        "items": [],
        "total": 0,
        "active_count": 0,
    }
    assert client.get("/api/alerts").json()["total"] == 0
    assert client.get("/api/changes").json()["total"] == 0


def test_ingest_correlate_filter_and_resolve_end_to_end(
    client: TestClient, frozen_clock: FrozenClock
) -> None:
    now = frozen_clock.now()
    payments = client.post(
        "/api/webhooks/alerts/prometheus",
        json=alertmanager_payload(
            fingerprint="e2e-payments",
            starts_at=now - timedelta(minutes=4),
            summary="Payment authorization failures",
        ),
    )
    assert payments.status_code == 201, payments.text
    payments_body = payments.json()
    incident_id = first_outcome(payments_body)["incident_id"]
    assert incident_id is not None

    latency = client.post(
        "/api/webhooks/alerts/cloudwatch",
        json=sns_wrap(
            cloudwatch_alarm(
                time=now - timedelta(minutes=2),
                severity="high",
            )
        ),
    )
    assert latency.status_code == 201, latency.text
    assert first_outcome(latency.json())["outcome"] == "joined"
    assert first_outcome(latency.json())["incident_id"] == incident_id

    backlog = client.post(
        "/api/webhooks/alerts/prometheus",
        json=alertmanager_payload(
            fingerprint="e2e-backlog",
            service="notifications-worker",
            severity="medium",
            alertname="QueueBacklog",
            summary="Notification backlog is growing",
            starts_at=now - timedelta(minutes=1),
        ),
    )
    assert backlog.status_code == 201, backlog.text
    assert backlog.json()["incidents_created"] == 1
    backlog_incident_id = first_outcome(backlog.json())["incident_id"]
    assert backlog_incident_id != incident_id

    incident = client.get(f"/api/incidents/{incident_id}").json()
    assert incident["incident"]["title"] == "payments-api: Payment authorization failures"
    assert incident["incident"]["alert_count"] == 2
    assert incident["incident"]["sources"] == ["cloudwatch", "prometheus"]
    assert incident["incident"]["affected_services"] == ["payments-api"]
    assert [event["event_type"] for event in incident["timeline"]] == ["opened", "alert_linked"]
    assert incident["topology"]["owner"] == "Payments Platform"
    assert incident["topology"]["tier"] == "critical"
    assert incident["notifications"][0]["payload"]["channel"] == "#bamboo11y-demo"
    assert incident["notifications"][0]["payload"]["text"].startswith("[CRITICAL] Opened:")

    listed = client.get("/api/incidents?active=true&limit=1").json()
    assert listed["total"] == 2
    assert listed["active_count"] == 2
    assert len(listed["items"]) == 1

    assert client.get("/api/incidents?severity=critical").json()["total"] == 1
    assert client.get("/api/incidents?severity=high").json()["total"] == 0
    assert client.get("/api/incidents?service=payments-api").json()["total"] == 1
    assert client.get("/api/incidents?source=cloudwatch").json()["total"] == 1
    assert client.get("/api/incidents?source=prometheus").json()["total"] == 2
    assert client.get("/api/incidents?environment=production").json()["total"] == 2
    assert client.get("/api/incidents?q=notifications").json()["total"] == 1
    assert client.get("/api/incidents?status=resolved").json()["total"] == 0

    alerts = client.get("/api/alerts?source=prometheus").json()
    assert alerts["total"] == 2
    assert alerts["limit"] == 50
    assert client.get(f"/api/alerts?incident_id={incident_id}").json()["total"] == 2
    assert client.get("/api/alerts?severity=high").json()["total"] == 1
    assert client.get("/api/alerts?service=notifications-worker").json()["total"] == 1
    assert client.get("/api/alerts?status=firing").json()["total"] == 3

    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["database"] == "ok"
    assert health["catalog_services"] == 10
    assert client.get("/healthz").json() == {"status": "ok"}
    readiness = client.get("/readyz")
    assert readiness.status_code == 200
    assert readiness.json() == {
        "status": "ready",
        "checks": {"database": "ok", "catalog": "ok (10 services)"},
    }
    assert client.get("/api/stats").json() == {
        "alerts": 3,
        "incidents": 2,
        "active_incidents": 2,
    }

    overview = client.get("/api/overview").json()
    assert overview["metrics"]["active_incidents"] == 2
    assert overview["metrics"]["alerts_last_24h"] == 3
    assert overview["metrics"]["affected_services"] == 2
    assert overview["metrics"]["service_count"] == 10
    assert overview["severity_mix"]["critical"] == 1
    assert overview["severity_mix"]["medium"] == 1
    assert overview["alert_volume"][-1]["count"] == 3
    assert {(item["source"], item["alerts_24h"]) for item in overview["source_health"]} == {
        ("prometheus", 2),
        ("cloudwatch", 1),
        ("open-integration", 0),
    }
    assert len(overview["recent_incidents"]) == 2

    acknowledged = client.patch(
        f"/api/incidents/{incident_id}/status",
        json={"status": "acknowledged", "actor": "e2e-operator"},
    )
    assert acknowledged.status_code == 200
    overview = client.get("/api/overview").json()
    assert overview["metrics"]["mean_time_to_acknowledge_seconds"] == 0.0

    resolved = client.patch(
        f"/api/incidents/{incident_id}/status",
        json={"status": "resolved", "actor": "e2e-operator", "note": "Canary rolled back."},
    )
    assert resolved.status_code == 200
    assert resolved.json()["incident"]["status"] == "resolved"

    overview = client.get("/api/overview").json()
    assert overview["metrics"]["active_incidents"] == 1
    assert overview["severity_mix"]["critical"] == 0
    assert len(overview["recent_incidents"]) == 1
    assert overview["recent_incidents"][0]["primary_service"] == "notifications-worker"

    notifications = client.get("/api/notifications").json()
    assert notifications["counts"] == {"sent": 4, "pending": 0, "failed": 0}
    assert len(notifications["items"]) == 4
    assert [item["event_type"] for item in notifications["items"]] == [
        "resolved",
        "acknowledged",
        "opened",
        "opened",
    ]

    integrations = client.get("/api/integrations").json()
    assert [source["source"] for source in integrations["sources"]] == [
        "cloudwatch",
        "open-integration",
        "prometheus",
    ]
    assert integrations["sources"][0]["alerts_24h"] == 1
    assert integrations["sources"][1]["alerts_24h"] == 0
    assert integrations["sources"][2]["alerts_24h"] == 2
    assert integrations["notifications"]["channel"] == "mock-slack"
    assert integrations["notifications"]["counts"]["sent"] == 4
    assert integrations["idempotency"]["strategy"].startswith("SHA-256")
    assert integrations["mock_slack_endpoint"] == "/api/mock/slack"

    mock_slack = client.post("/api/mock/slack", json={"text": "hello"})
    assert mock_slack.status_code == 200
    assert mock_slack.json()["ok"] is True


def test_metrics_health_and_security_headers(client: TestClient, frozen_clock: FrozenClock) -> None:
    client.post(
        "/api/webhooks/alerts/prometheus",
        json=alertmanager_payload(
            fingerprint="metrics-alert", starts_at=frozen_clock.now() - timedelta(minutes=1)
        ),
    )

    health = client.get("/api/health", headers={"X-Request-ID": "trace-e2e-1"})
    assert health.headers["X-Request-ID"] == "trace-e2e-1"
    assert health.headers["X-Content-Type-Options"] == "nosniff"
    assert health.headers["X-Frame-Options"] == "DENY"
    assert health.headers["Referrer-Policy"] == "no-referrer"
    assert "default-src 'self'" in health.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in health.headers["Content-Security-Policy"]

    generated = client.get("/api/health", headers={"X-Request-ID": "bad id with spaces"})
    assert generated.headers["X-Request-ID"] != "bad id with spaces"
    assert len(generated.headers["X-Request-ID"]) == 32

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert metrics.headers["content-type"].startswith("text/plain")
    text = metrics.text
    assert 'bamboo11y_webhook_requests_total{result="accepted",source="prometheus"} 1.0' in text
    assert 'bamboo11y_alerts_ingested_total{outcome="created",source="prometheus"} 1.0' in text
    assert "bamboo11y_incidents_created_total 1.0" in text
    assert "bamboo11y_catalog_services 10.0" in text
    assert "bamboo11y_incidents_active 1.0" in text
    assert "bamboo11y_alerts_firing 1.0" in text
    assert "bamboo11y_http_requests_total" in text

    docs = client.get("/docs")
    assert docs.status_code == 200
    assert "cdn.jsdelivr.net" in docs.headers["Content-Security-Policy"]


def test_change_events_are_idempotent_and_context_only(
    client: TestClient, frozen_clock: FrozenClock
) -> None:
    now = frozen_clock.now()
    alert = client.post(
        "/api/webhooks/alerts/prometheus",
        json=alertmanager_payload(
            fingerprint="change-context", starts_at=now - timedelta(minutes=4)
        ),
    )
    incident_id = first_outcome(alert.json())["incident_id"]

    payload = {
        "service": "payments-api",
        "version": "v2.14.0",
        "environment": "production",
        "region": "us-east-1",
        "kind": "deployment",
        "summary": "Canary rollout of the retry-budget refactor.",
        "occurred_at": _iso(now - timedelta(minutes=10)),
        "external_id": "deploy-e2e-42",
    }
    created = client.post("/api/changes", json=payload)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["created"] is True
    assert body["item"]["service"] == "payments-api"
    assert body["item"]["version"] == "v2.14.0"
    assert body["item"]["occurred_at"] == _iso(now - timedelta(minutes=10))

    repeated = client.post("/api/changes", json={**payload, "summary": "ignored on replay"})
    assert repeated.status_code == 200
    assert repeated.json()["created"] is False
    assert repeated.json()["item"]["id"] == body["item"]["id"]
    assert repeated.json()["item"]["summary"] == payload["summary"]
    assert client.get("/api/changes").json()["total"] == 1

    conflict = client.post(
        "/api/changes",
        json={**payload, "service": "checkout-api", "version": "v1.0.0"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "change_external_id_conflict"

    unknown_service = client.post(
        "/api/changes",
        json={**payload, "service": "nope-service", "external_id": "deploy-e2e-43"},
    )
    assert unknown_service.status_code == 422
    assert unknown_service.json()["code"] == "unknown_service"

    unknown_environment = client.post(
        "/api/changes",
        json={**payload, "environment": "qa", "external_id": "deploy-e2e-44"},
    )
    assert unknown_environment.status_code == 422
    assert unknown_environment.json()["code"] == "unknown_environment"

    detail = client.get(f"/api/incidents/{incident_id}").json()
    assert len(detail["nearby_changes"]) == 1
    nearby = detail["nearby_changes"][0]
    assert nearby["version"] == "v2.14.0"
    assert nearby["minutes_from_first_alert"] == -6.0
    assert nearby["relation"] == "before_first_alert"
    assert nearby["relationship"] == "temporal_context_only"
    assert "not proof of causation" in nearby["disclaimer"]
    assert "not proof of causation" in detail["change_context"]["disclaimer"]

    service = client.get("/api/services/payments-api").json()
    assert service["service"]["owner"] == "Payments Platform"
    assert [item["id"] for item in service["upstream"]] == ["checkout-api"]
    assert [item["id"] for item in service["downstream"]] == ["postgres-orders", "fraud-check"]
    assert [item["version"] for item in service["recent_changes"]] == ["v2.14.0"]
    assert service["edges"] == [
        {"source": "checkout-api", "target": "payments-api"},
        {"source": "payments-api", "target": "postgres-orders"},
        {"source": "payments-api", "target": "fraud-check"},
    ]
    assert [item["service"]["id"] for item in service["transitive_upstream"]][:2] == [
        "checkout-api",
        "edge-gateway",
    ]

    catalog = client.get("/api/services").json()
    assert len(catalog["services"]) == 10
    assert catalog["catalog_version"] == 1
    assert catalog["environments"] == ["production", "staging"]
    assert len(catalog["edges"]) == 10

    missing = client.get("/api/services/nope-service")
    assert missing.status_code == 404
    assert missing.json()["code"] == "service_not_found"
