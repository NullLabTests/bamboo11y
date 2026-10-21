"""Prometheus metrics with a per-application registry."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Alert, Incident


class Metrics:
    def __init__(self, catalog_services: int = 0) -> None:
        self.registry = CollectorRegistry()
        self.http_requests = Counter(
            "bamboo11y_http_requests_total",
            "HTTP requests handled by the API.",
            ["method", "status_class"],
            registry=self.registry,
        )
        self.http_duration = Histogram(
            "bamboo11y_http_request_duration_seconds",
            "HTTP request duration in seconds.",
            ["method"],
            registry=self.registry,
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
        )
        self.webhook_requests = Counter(
            "bamboo11y_webhook_requests_total",
            "Webhook requests by source and result.",
            ["source", "result"],
            registry=self.registry,
        )
        self.alerts_ingested = Counter(
            "bamboo11y_alerts_ingested_total",
            "Normalized alert outcomes by source and outcome.",
            ["source", "outcome"],
            registry=self.registry,
        )
        self.incidents_created = Counter(
            "bamboo11y_incidents_created_total",
            "Incidents created by the correlation engine.",
            registry=self.registry,
        )
        self.notifications = Counter(
            "bamboo11y_notifications_total",
            "Notification outbox attempts by result.",
            ["result"],
            registry=self.registry,
        )
        self.active_incidents = Gauge(
            "bamboo11y_incidents_active",
            "Incidents currently open or acknowledged.",
            registry=self.registry,
        )
        self.total_incidents = Gauge(
            "bamboo11y_incidents_total",
            "All incidents currently persisted.",
            registry=self.registry,
        )
        self.active_alerts = Gauge(
            "bamboo11y_alerts_firing",
            "Alerts currently in firing state.",
            registry=self.registry,
        )
        self.catalog_services = Gauge(
            "bamboo11y_catalog_services",
            "Services in the loaded catalog.",
            registry=self.registry,
        )
        self.catalog_services.set(catalog_services)

    def observe_http(self, method: str, status_code: int, duration_seconds: float) -> None:
        self.http_requests.labels(method=method, status_class=f"{status_code // 100}xx").inc()
        self.http_duration.labels(method=method).observe(duration_seconds)

    def observe_webhook(self, source: str, result: str) -> None:
        self.webhook_requests.labels(source=source, result=result).inc()

    def observe_alert(self, source: str, outcome: str) -> None:
        self.alerts_ingested.labels(source=source, outcome=outcome).inc()

    def observe_incident_created(self, count: int = 1) -> None:
        if count:
            self.incidents_created.inc(count)

    def observe_notification_result(self, result: str, count: int = 1) -> None:
        if count:
            self.notifications.labels(result=result).inc(count)

    def refresh_database_gauges(self, session: Session) -> None:
        active = session.scalar(
            select(func.count(Incident.id)).where(Incident.status.in_(("open", "acknowledged")))
        )
        total = session.scalar(select(func.count(Incident.id)))
        firing = session.scalar(select(func.count(Alert.id)).where(Alert.status == "firing"))
        self.active_incidents.set(int(active or 0))
        self.total_incidents.set(int(total or 0))
        self.active_alerts.set(int(firing or 0))
