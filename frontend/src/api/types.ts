export type Severity = "critical" | "high" | "medium" | "low" | "info";
export type IncidentStatus = "open" | "acknowledged" | "resolved";
export type AlertStatus = "firing" | "resolved";
export type Source = "cloudwatch" | "open-integration" | "prometheus";
export type ChangeKind = "deployment" | "config" | "rollback" | "feature_flag";

export interface IncidentSummary {
  id: number;
  title: string;
  status: IncidentStatus;
  severity: Severity;
  primary_service: string;
  environment: string;
  region: string | null;
  created_at: string;
  updated_at: string;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  resolved_at: string | null;
  resolved_by: string | null;
  resolution_note: string | null;
  alert_count: number;
  sources: Source[];
  affected_services: string[];
  age_seconds: number;
  first_alert_at: string | null;
  last_alert_at: string | null;
  is_demo: boolean;
}

export interface CorrelationReason {
  rule: string;
  summary: string;
  matched_on?: string[];
  window_minutes?: number;
  minutes_from_nearest_alert?: number;
  note?: string;
  topology?: {
    relation: string;
    direction: string;
    edge: { source: string; target: string };
    hops: number;
  };
}

export interface AlertRead {
  id: number;
  fingerprint: string;
  source: Source;
  source_alert_id: string;
  title: string;
  description: string;
  severity: Severity;
  status: AlertStatus;
  service: string;
  environment: string;
  region: string | null;
  labels: Record<string, string>;
  source_metadata: Record<string, unknown>;
  enrichment: Record<string, unknown>;
  dedupe_key: string;
  occurred_at: string;
  received_at: string;
  last_seen_at: string;
  occurrences: number;
  incident_id: number | null;
  correlation: CorrelationReason | null;
  is_demo: boolean;
  delivery_id: string | null;
}

export interface TimelineEntry {
  id: number;
  event_type: string;
  message: string;
  actor: string | null;
  automated: boolean;
  occurred_at: string;
  details: Record<string, unknown>;
}

export interface Service {
  id: string;
  name: string;
  description: string;
  owner: string;
  team: string;
  tier: Severity | "high" | "medium" | "low";
  environments: string[];
  depends_on: string[];
  dependents: string[];
  repository: string | null;
  runbook: string | null;
}

export interface Edge {
  source: string;
  target: string;
}

export interface RelatedService {
  service: Service;
  depth: number;
  path: string[];
}

export interface TopologyContext {
  focus_service: Service | null;
  service_found: boolean;
  owner: string;
  team: string;
  tier: string;
  affected_services: string[];
  upstream: Service[];
  downstream: Service[];
  transitive_upstream: RelatedService[];
  transitive_downstream: RelatedService[];
  edges: Edge[];
  catalog_version: number;
  disclaimer: string;
}

export interface ChangeRead {
  id: number;
  service: string;
  version: string;
  environment: string;
  region: string | null;
  kind: ChangeKind;
  summary: string;
  occurred_at: string;
  source: string;
  is_demo: boolean;
}

export interface NearbyChange extends ChangeRead {
  minutes_from_first_alert: number;
  relation: "before_first_alert" | "after_first_alert";
  relationship: "temporal_context_only";
  disclaimer: string;
}

export interface NotificationRead {
  id: number;
  incident_id: number;
  event_type: string;
  channel: string;
  payload: Record<string, unknown>;
  status: "pending" | "sent" | "failed";
  attempts: number;
  created_at: string;
  sent_at: string | null;
  last_error: string | null;
  is_demo: boolean;
}

export interface IncidentDetail {
  incident: IncidentSummary;
  alerts: AlertRead[];
  timeline: TimelineEntry[];
  topology: TopologyContext;
  nearby_changes: NearbyChange[];
  change_context: {
    window_minutes: number;
    first_alert_at: string | null;
    disclaimer: string;
  };
  notifications: NotificationRead[];
}

export interface IncidentList {
  items: IncidentSummary[];
  total: number;
  active_count: number;
}

export interface AlertList {
  items: AlertRead[];
  total: number;
  limit: number;
  offset: number;
}

export interface ServiceCatalog {
  services: Service[];
  edges: Edge[];
  environments: string[];
  catalog_version: number;
}

export interface ServiceDetail {
  service: Service;
  upstream: Service[];
  downstream: Service[];
  transitive_upstream: RelatedService[];
  transitive_downstream: RelatedService[];
  edges: Edge[];
  recent_changes: ChangeRead[];
}

export interface ChangeList {
  items: ChangeRead[];
  total: number;
}

export interface ChangeCreateResponse {
  item: ChangeRead;
  created: boolean;
}

export interface SourceHealth {
  source: Source;
  display_name: string;
  alerts_24h: number;
  last_received_at: string | null;
  status: "receiving" | "quiet";
}

export interface MetricSummary {
  active_incidents: number;
  alerts_last_24h: number;
  affected_services: number;
  mean_time_to_acknowledge_seconds: number | null;
  service_count: number;
}

export interface AlertVolumeBucket {
  bucket_start: string;
  count: number;
}

export interface Overview {
  generated_at: string;
  metrics: MetricSummary;
  severity_mix: Record<Severity, number>;
  source_health: SourceHealth[];
  alert_volume: AlertVolumeBucket[];
  recent_incidents: IncidentSummary[];
  recent_changes: ChangeRead[];
  demo_scenario: string;
}

export interface IntegrationSource {
  source: Source;
  display_name: string;
  description: string;
  endpoint: string;
  alerts_24h: number;
  last_received_at: string | null;
}

export interface IntegrationState {
  sources: IntegrationSource[];
  rate_limit: {
    requests_per_minute: number;
    scope: string;
    note: string;
  };
  idempotency: {
    strategy: string;
    duplicate_behavior: string;
    delivery_header: string;
  };
  notifications: {
    channel: string;
    external_webhook_configured: boolean;
    counts: { sent: number; pending: number; failed: number };
    recent: NotificationRead[];
    local_sink_note: string;
  };
  mock_slack_endpoint: string;
}

export interface NotificationList {
  items: NotificationRead[];
  counts: { sent: number; pending: number; failed: number };
}

export interface DemoIncident {
  id: number;
  title: string;
  status: IncidentStatus;
  severity: Severity;
  primary_service: string;
  environment: string;
  alert_count: number;
  sources: Source[];
}

export interface DemoResult {
  run_id: string;
  scenario: string;
  primary_incident_id: number | null;
  primary_alert_fingerprint: string;
  incidents: DemoIncident[];
  alerts_received: number;
  unique_alerts: number;
  duplicate_deliveries: number;
  notifications_delivered: number;
  changes: { id: number; service: string }[];
  summary: {
    headline: string;
    primary_incident_id: number | null;
    primary_incident_alert_count: number;
    primary_incident_sources: Source[];
    primary_incident_affected_services: string[];
    nearby_change: {
      service: string;
      version: string;
      minutes_before_first_alert: number;
      relationship: "temporal_context_only";
    };
    unrelated_incident_count: number;
    disclaimer: string;
  };
}

export interface IncidentActionResponse {
  incident: IncidentSummary;
  changed: boolean;
  notification_dispatched: boolean;
}
