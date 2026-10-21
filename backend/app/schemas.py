"""Pydantic request/response schemas shared by the API and the dashboard."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.constants import ChangeKind, IncidentStatus, Severity


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fingerprint: str
    source: str
    source_alert_id: str
    title: str
    description: str
    severity: str
    status: str
    service: str
    environment: str
    region: str | None
    labels: dict[str, str]
    source_metadata: dict[str, Any]
    enrichment: dict[str, Any]
    dedupe_key: str
    occurred_at: datetime
    received_at: datetime
    last_seen_at: datetime
    occurrences: int
    incident_id: int | None
    correlation: dict[str, Any] | None
    is_demo: bool
    delivery_id: str | None


class AlertListResponse(BaseModel):
    items: list[AlertRead]
    total: int
    limit: int
    offset: int


class AlertOutcomeRead(BaseModel):
    alert_id: int
    fingerprint: str
    source_alert_id: str
    title: str
    service: str
    environment: str
    severity: str
    status: str
    outcome: str
    incident_id: int | None
    created_incident: bool
    duplicate_delivery: bool
    correlation: dict[str, Any]


class WebhookIngestResponse(BaseModel):
    source: str
    received: int
    created_alerts: int
    joined_alerts: int
    updated_alerts: int
    resolved_without_incident: int
    duplicates: int
    incidents_created: int
    notifications_created: int
    outcomes: list[AlertOutcomeRead]


class IncidentSummary(BaseModel):
    id: int
    title: str
    status: str
    severity: str
    primary_service: str
    environment: str
    region: str | None
    created_at: datetime
    updated_at: datetime
    acknowledged_at: datetime | None
    acknowledged_by: str | None
    resolved_at: datetime | None
    resolved_by: str | None
    resolution_note: str | None
    alert_count: int
    sources: list[str]
    affected_services: list[str]
    age_seconds: float
    first_alert_at: datetime | None
    last_alert_at: datetime | None
    is_demo: bool


class IncidentListResponse(BaseModel):
    items: list[IncidentSummary]
    total: int
    active_count: int


class TimelineEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    message: str
    actor: str | None
    automated: bool
    occurred_at: datetime
    details: dict[str, Any]


class ServiceRead(BaseModel):
    id: str
    name: str
    description: str
    owner: str
    team: str
    tier: str
    environments: list[str]
    depends_on: list[str]
    dependents: list[str]
    repository: str | None
    runbook: str | None


class EdgeRead(BaseModel):
    source: str
    target: str


class RelatedServiceRead(BaseModel):
    service: ServiceRead
    depth: int
    path: list[str]


class TopologyContextRead(BaseModel):
    focus_service: ServiceRead | None
    service_found: bool
    owner: str
    team: str
    tier: str
    affected_services: list[str]
    upstream: list[ServiceRead]
    downstream: list[ServiceRead]
    transitive_upstream: list[RelatedServiceRead]
    transitive_downstream: list[RelatedServiceRead]
    edges: list[EdgeRead]
    catalog_version: int
    disclaimer: str


class ChangeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    service: str
    version: str
    environment: str
    region: str | None
    kind: str
    summary: str
    occurred_at: datetime
    source: str
    is_demo: bool


class NearbyChangeRead(ChangeRead):
    minutes_from_first_alert: float
    relation: str
    relationship: Literal["temporal_context_only"] = "temporal_context_only"
    disclaimer: str


class ChangeContextRead(BaseModel):
    window_minutes: int
    first_alert_at: datetime | None
    disclaimer: str


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    incident_id: int
    event_type: str
    channel: str
    payload: dict[str, Any]
    status: str
    attempts: int
    created_at: datetime
    sent_at: datetime | None
    last_error: str | None
    is_demo: bool


class IncidentDetailResponse(BaseModel):
    incident: IncidentSummary
    alerts: list[AlertRead]
    timeline: list[TimelineEntryRead]
    topology: TopologyContextRead
    nearby_changes: list[NearbyChangeRead]
    change_context: ChangeContextRead
    notifications: list[NotificationRead]


class IncidentStatusUpdate(StrictModel):
    status: Literal["acknowledged", "resolved"]
    actor: str = Field(default="local-operator", min_length=1, max_length=128)
    note: str | None = Field(default=None, max_length=2000)


class IncidentActionResponse(BaseModel):
    incident: IncidentSummary
    changed: bool
    notification_dispatched: bool


class ChangeCreate(StrictModel):
    service: str = Field(min_length=2, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    environment: str = Field(min_length=1, max_length=64)
    region: str | None = Field(default=None, max_length=64)
    kind: ChangeKind = ChangeKind.DEPLOYMENT
    summary: str = Field(min_length=3, max_length=600)
    occurred_at: datetime | None = None
    external_id: str | None = Field(default=None, min_length=1, max_length=128)


class ChangeListResponse(BaseModel):
    items: list[ChangeRead]
    total: int


class ChangeCreateResponse(BaseModel):
    item: ChangeRead
    created: bool


class ServiceCatalogResponse(BaseModel):
    services: list[ServiceRead]
    edges: list[EdgeRead]
    environments: list[str]
    catalog_version: int


class ServiceDetailResponse(BaseModel):
    service: ServiceRead
    upstream: list[ServiceRead]
    downstream: list[ServiceRead]
    transitive_upstream: list[RelatedServiceRead]
    transitive_downstream: list[RelatedServiceRead]
    edges: list[EdgeRead]
    recent_changes: list[ChangeRead]


class SourceHealthRead(BaseModel):
    source: str
    display_name: str
    alerts_24h: int
    last_received_at: datetime | None
    status: str


class AlertVolumeBucketRead(BaseModel):
    bucket_start: datetime
    count: int


class OverviewMetricsRead(BaseModel):
    active_incidents: int
    alerts_last_24h: int
    affected_services: int
    mean_time_to_acknowledge_seconds: float | None
    service_count: int


class OverviewResponse(BaseModel):
    generated_at: datetime
    metrics: OverviewMetricsRead
    severity_mix: dict[str, int]
    source_health: list[SourceHealthRead]
    alert_volume: list[AlertVolumeBucketRead]
    recent_incidents: list[IncidentSummary]
    recent_changes: list[ChangeRead]
    demo_scenario: str


class IntegrationSourceRead(BaseModel):
    source: str
    display_name: str
    description: str
    endpoint: str
    alerts_24h: int
    last_received_at: datetime | None


class NotificationCountsRead(BaseModel):
    sent: int
    pending: int
    failed: int


class IntegrationResponse(BaseModel):
    sources: list[IntegrationSourceRead]
    rate_limit: dict[str, Any]
    idempotency: dict[str, Any]
    notifications: dict[str, Any]
    mock_slack_endpoint: str


class NotificationListResponse(BaseModel):
    items: list[NotificationRead]
    counts: NotificationCountsRead


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    database: str
    catalog_services: int
    catalog_version: int
    time: datetime


class ReadinessResponse(BaseModel):
    status: str
    checks: dict[str, str]


class DemoRunRequest(StrictModel):
    scenario: Literal["payments_degradation"] = "payments_degradation"
    fresh: bool = True


class DemoIncidentRead(BaseModel):
    id: int
    title: str
    status: str
    severity: str
    primary_service: str
    environment: str
    alert_count: int
    sources: list[str]


class DemoChangeRead(BaseModel):
    id: int
    service: str


class DemoResponse(BaseModel):
    run_id: str
    scenario: str
    primary_incident_id: int | None
    primary_alert_fingerprint: str
    incidents: list[DemoIncidentRead]
    alerts_received: int
    unique_alerts: int
    duplicate_deliveries: int
    notifications_delivered: int
    changes: list[DemoChangeRead]
    summary: dict[str, Any]


class DemoResetResponse(BaseModel):
    deleted: dict[str, int]


class ApiErrorBody(BaseModel):
    detail: str
    code: str
    request_id: str | None = None
    errors: list[dict[str, str]] = Field(default_factory=list)
    hints: list[str] = Field(default_factory=list)


class SeverityCount(BaseModel):
    severity: Severity
    count: int


class IncidentStatusCount(BaseModel):
    status: IncidentStatus
    count: int
