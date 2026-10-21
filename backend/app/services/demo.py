"""Deterministic demo scenario executed through the real adapters and ingestion service.

The scenario intentionally includes unrelated alerts so the dashboard demonstrates
correlation rather than simply dumping every alert into one incident.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.adapters import get_adapter
from app.clock import Clock
from app.config import Settings
from app.constants import ChangeKind, Source
from app.models import (
    Alert,
    ChangeEvent,
    DemoRun,
    Incident,
    IncidentEvent,
    Notification,
)
from app.services.catalog import Catalog
from app.services.changes import ChangeService
from app.services.ingestion import AlertIngestionService
from app.services.notifications import NotificationService

SCENARIO_NAME = "payments_degradation"


class ScenarioError(ValueError):
    pass


@dataclass
class DemoResult:
    run_id: str
    scenario: str
    primary_incident_id: int | None
    primary_alert_fingerprint: str
    incidents: list[dict[str, Any]] = field(default_factory=list)
    alerts_received: int = 0
    unique_alerts: int = 0
    duplicate_deliveries: int = 0
    notifications_delivered: int = 0
    incidents_created: int = 0
    changes: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)


class DemoService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        catalog: Catalog,
        clock: Clock,
    ) -> None:
        self.session = session
        self.settings = settings
        self.catalog = catalog
        self.clock = clock
        self.ingestion = AlertIngestionService(session, settings, catalog, clock)
        self.notifications = NotificationService(session, settings, clock)
        self.changes = ChangeService(session, settings, catalog, clock)

    def reset_demo_data(self) -> dict[str, int]:
        demo_incident_ids = select(Incident.id).where(Incident.is_demo.is_(True))
        result: dict[str, int] = {}
        for label, statement in (
            ("notifications", delete(Notification).where(Notification.is_demo.is_(True))),
            (
                "events",
                delete(IncidentEvent).where(IncidentEvent.incident_id.in_(demo_incident_ids)),
            ),
            ("alerts", delete(Alert).where(Alert.is_demo.is_(True))),
            ("incidents", delete(Incident).where(Incident.is_demo.is_(True))),
            ("changes", delete(ChangeEvent).where(ChangeEvent.is_demo.is_(True))),
            ("runs", delete(DemoRun)),
        ):
            result[label] = int(self.session.execute(statement).rowcount or 0)
        self.session.flush()
        return result

    def run(
        self,
        *,
        scenario: str = SCENARIO_NAME,
        fresh: bool = True,
    ) -> DemoResult:
        if scenario != SCENARIO_NAME:
            raise ScenarioError(
                f"Unknown scenario '{scenario}'. Available scenarios: {SCENARIO_NAME}."
            )
        if fresh:
            self.reset_demo_data()

        now = self.clock.now()
        run_id = uuid.uuid4().hex[:12]
        first_payload = self._alertmanager_storm(now)

        payment_change, _ = self.changes.create(
            service="payments-api",
            version="v2.14.0",
            environment="production",
            region="us-east-1",
            kind=ChangeKind.DEPLOYMENT.value,
            summary=(
                "Canary rollout of the retry-budget refactor in the payments authorizer; "
                "error-budget guardrails enabled."
            ),
            occurred_at=now - timedelta(minutes=12),
            external_id=f"demo-{run_id}-payments-deploy",
            source="demo-deploy-feed",
            is_demo=True,
        )
        search_change, _ = self.changes.create(
            service="search-api",
            version="cfg-2026.10.21-3",
            environment="staging",
            region="us-east-1",
            kind=ChangeKind.CONFIG.value,
            summary="Ranking cache TTL reduced from 15 minutes to 3 minutes in staging.",
            occurred_at=now - timedelta(minutes=20),
            external_id=f"demo-{run_id}-search-config",
            source="demo-config-feed",
            is_demo=True,
        )

        am_adapter = get_adapter(Source.PROMETHEUS.value)
        cw_adapter = get_adapter(Source.CLOUDWATCH.value)
        assert am_adapter is not None
        assert cw_adapter is not None

        am_alerts = am_adapter.normalize(
            first_payload, received_at=now, delivery_id=f"demo-{run_id}-am-1"
        )
        first_result = self.ingestion.ingest(
            Source.PROMETHEUS,
            am_alerts,
            received_at=now,
            delivery_id=f"demo-{run_id}-am-1",
            is_demo=True,
        )

        cloudwatch_payload = self._cloudwatch_storm(now)
        notifications_payload = self._notifications_storm(now)
        cw_alerts = [
            *cw_adapter.normalize(
                cloudwatch_payload, received_at=now, delivery_id=f"demo-{run_id}-cw-1"
            ),
            *cw_adapter.normalize(
                notifications_payload, received_at=now, delivery_id=f"demo-{run_id}-cw-2"
            ),
        ]
        second_result = self.ingestion.ingest(
            Source.CLOUDWATCH,
            cw_alerts,
            received_at=now,
            delivery_id=f"demo-{run_id}-cw-1",
            is_demo=True,
        )

        # A provider retry of the first alert proves idempotency without adding noise to the
        # incident. Only the payment alert is replayed so the expected duplicate count is 1.
        duplicate_alerts = am_adapter.normalize(
            self._single_payment_payload(now),
            received_at=now,
            delivery_id=f"demo-{run_id}-am-1-retry",
        )
        duplicate_result = self.ingestion.ingest(
            Source.PROMETHEUS,
            duplicate_alerts,
            received_at=now,
            delivery_id=f"demo-{run_id}-am-1-retry",
            is_demo=True,
        )
        self.session.commit()
        dispatch = self.notifications.dispatch_pending()
        self.session.commit()

        all_results = [first_result, second_result, duplicate_result]
        primary_alert = self.session.scalar(
            select(Alert).where(
                Alert.is_demo.is_(True),
                Alert.fingerprint == am_alerts[0].fingerprint,
            )
        )
        primary_incident = primary_alert.incident if primary_alert else None
        contact = self._incident_contact(primary_incident) if primary_incident else {}

        incidents = self.session.scalars(
            select(Incident).where(Incident.is_demo.is_(True)).order_by(Incident.id.asc())
        ).all()
        incident_summaries = [self._incident_summary(incident) for incident in incidents]
        primary_id = primary_incident.id if primary_incident else None
        first_alert_at = (
            min(alert.occurred_at for alert in primary_incident.alerts) if primary_incident else now
        )
        change_minutes = round(
            abs((payment_change.occurred_at - first_alert_at).total_seconds()) / 60, 1
        )

        summary = {
            "headline": (
                "A payments canary deployment coincided with a cross-source alert burst. "
                "Bamboo11y grouped the payment and checkout symptoms into one incident and "
                "kept unrelated signals separate."
            ),
            "primary_incident_id": primary_id,
            "primary_incident_alert_count": contact.get("alert_count"),
            "primary_incident_sources": contact.get("sources", []),
            "primary_incident_affected_services": contact.get("affected_services", []),
            "nearby_change": {
                "service": payment_change.service,
                "version": payment_change.version,
                "minutes_before_first_alert": change_minutes,
                "relationship": "temporal_context_only",
            },
            "unrelated_incident_count": max(len(incidents) - 1, 0),
            "disclaimer": (
                "The deployment is shown as temporal context only; this scenario does not "
                "prove that it caused the incident."
            ),
        }
        demo_run = DemoRun(
            run_id=run_id,
            scenario=scenario,
            created_at=now,
            summary=summary,
        )
        self.session.add(demo_run)
        self.session.commit()

        return DemoResult(
            run_id=run_id,
            scenario=scenario,
            primary_incident_id=primary_id,
            primary_alert_fingerprint=am_alerts[0].fingerprint,
            incidents=incident_summaries,
            alerts_received=sum(result.received for result in all_results),
            unique_alerts=sum(result.created_alerts for result in all_results),
            duplicate_deliveries=sum(result.duplicates for result in all_results),
            notifications_delivered=dispatch.get("sent", 0),
            incidents_created=sum(result.incidents_created for result in all_results),
            changes=[
                {"id": payment_change.id, "service": payment_change.service},
                {"id": search_change.id, "service": search_change.service},
            ],
            summary=summary,
        )

    def _incident_contact(self, incident: Incident) -> dict[str, Any]:
        sources = sorted({alert.source for alert in incident.alerts})
        services = sorted({alert.service for alert in incident.alerts})
        return {
            "alert_count": len(incident.alerts),
            "sources": sources,
            "affected_services": services,
        }

    def _incident_summary(self, incident: Incident) -> dict[str, Any]:
        contact = self._incident_contact(incident)
        return {
            "id": incident.id,
            "title": incident.title,
            "status": incident.status,
            "severity": incident.severity,
            "primary_service": incident.primary_service,
            "environment": incident.environment,
            "alert_count": contact["alert_count"],
            "sources": contact["sources"],
        }

    @staticmethod
    def _alertmanager_storm(now: datetime) -> dict[str, Any]:
        base = now - timedelta(minutes=6)
        return {
            "version": "4",
            "status": "firing",
            "receiver": "bamboo11y-webhook",
            "groupKey": '{}:{alertname=~"Payments.*|Checkout.*|Search.*"}',
            "alerts": [
                {
                    "status": "firing",
                    "fingerprint": "demo-payments-error-rate",
                    "labels": {
                        "alertname": "PaymentsAPIHighErrorRate",
                        "service": "payments-api",
                        "environment": "production",
                        "region": "us-east-1",
                        "severity": "critical",
                        "cluster": "prod-use1",
                        "slo": "payment-authorization-availability",
                    },
                    "annotations": {
                        "summary": "Payment authorization errors above 5%",
                        "description": (
                            "The five-minute authorization error rate is 8.4%, above the "
                            "5% burn threshold. Checkout traffic is beginning to fail."
                        ),
                    },
                    "startsAt": base.isoformat().replace("+00:00", "Z"),
                },
                {
                    "status": "firing",
                    "fingerprint": "demo-checkout-5xx",
                    "labels": {
                        "alertname": "CheckoutErrorBudgetBurn",
                        "service": "checkout-api",
                        "environment": "production",
                        "region": "us-east-1",
                        "severity": "high",
                        "cluster": "prod-use1",
                    },
                    "annotations": {
                        "summary": "Checkout 5xx rate is burning the error budget",
                        "description": (
                            "Checkout success rate dropped after payment authorization "
                            "failures increased."
                        ),
                    },
                    "startsAt": (base + timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
                },
                {
                    "status": "firing",
                    "fingerprint": "demo-search-latency-staging",
                    "labels": {
                        "alertname": "SearchLatencyWarning",
                        "service": "search-api",
                        "environment": "staging",
                        "region": "us-east-1",
                        "severity": "medium",
                        "cluster": "staging-use1",
                    },
                    "annotations": {
                        "summary": "Search p99 latency is elevated in staging",
                        "description": (
                            "Staging search p99 exceeded 900 ms after a ranking cache "
                            "configuration change. This is unrelated to production payments."
                        ),
                    },
                    "startsAt": (base + timedelta(minutes=2)).isoformat().replace("+00:00", "Z"),
                },
            ],
        }

    @staticmethod
    def _single_payment_payload(now: datetime) -> dict[str, Any]:
        payload = DemoService._alertmanager_storm(now)
        payload["alerts"] = [payload["alerts"][0]]
        return payload

    @staticmethod
    def _cloudwatch_storm(now: datetime) -> dict[str, Any]:
        return {
            "Type": "Notification",
            "MessageId": "demo-sns-message-1",
            "TopicArn": "arn:aws:sns:us-east-1:123456789012:bamboo11y-demo",
            "Subject": "ALARM: payments-api p99 latency",
            "Timestamp": (now - timedelta(minutes=3)).isoformat().replace("+00:00", "Z"),
            "Message": json.dumps(
                {
                    "AlarmName": "payments-api-p99-latency",
                    "AlarmArn": (
                        "arn:aws:cloudwatch:us-east-1:123456789012:alarm:payments-api-p99-latency"
                    ),
                    "AlarmDescription": "Payment API p99 latency SLO burn.",
                    "NewStateValue": "ALARM",
                    "NewStateReason": (
                        "Threshold crossed: p99 request latency was 2.8 s for three "
                        "consecutive one-minute periods (threshold 1.5 s)."
                    ),
                    "StateChangeTime": (now - timedelta(minutes=3))
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "Region": "us-east-1",
                    "AccountId": "123456789012",
                    "Namespace": "Bamboo11y/Demo",
                    "Severity": "high",
                    "Dimensions": [
                        {"Name": "Service", "Value": "payments-api"},
                        {"Name": "Environment", "Value": "production"},
                    ],
                }
            ),
        }

    @staticmethod
    def _notifications_storm(now: datetime) -> dict[str, Any]:
        return {
            "AlarmName": "notifications-worker-queue-backlog",
            "AlarmArn": (
                "arn:aws:cloudwatch:us-east-1:123456789012:alarm:notifications-worker-queue-backlog"
            ),
            "AlarmDescription": "Notification delivery backlog.",
            "NewStateValue": "ALARM",
            "NewStateReason": "ApproximateAgeOfOldestMessage exceeded 900 seconds.",
            "StateChangeTime": (now - timedelta(minutes=2)).isoformat().replace("+00:00", "Z"),
            "Region": "us-east-1",
            "AccountId": "123456789012",
            "Severity": "medium",
            "Dimensions": [
                {"Name": "Service", "Value": "notifications-worker"},
                {"Name": "Environment", "Value": "production"},
            ],
        }
