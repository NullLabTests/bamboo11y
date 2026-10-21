import type {
  AlertRead,
  DemoResult,
  IncidentDetail,
  IncidentSummary,
  IntegrationState,
  Overview,
  Service,
  ServiceCatalog,
} from "../src/api/types";

const generatedAt = "2026-10-21T12:00:00Z";

const buckets = Array.from({ length: 12 }, (_, index) => ({
  bucket_start: new Date(Date.UTC(2026, 9, 21, 1 + index)).toISOString(),
  count: 0,
}));

export const emptyOverview: Overview = {
  generated_at: generatedAt,
  metrics: {
    active_incidents: 0,
    alerts_last_24h: 0,
    affected_services: 0,
    mean_time_to_acknowledge_seconds: null,
    service_count: 10,
  },
  severity_mix: { critical: 0, high: 0, medium: 0, low: 0, info: 0 },
  source_health: [
    {
      source: "cloudwatch",
      display_name: "AWS CloudWatch",
      alerts_24h: 0,
      last_received_at: null,
      status: "quiet",
    },
    {
      source: "prometheus",
      display_name: "Prometheus Alertmanager",
      alerts_24h: 0,
      last_received_at: null,
      status: "quiet",
    },
  ],
  alert_volume: buckets,
  recent_incidents: [],
  recent_changes: [],
  demo_scenario: "payments_degradation",
};

export const paymentsIncident: IncidentSummary = {
  id: 7,
  title: "payments-api: Payment authorization failures",
  status: "open",
  severity: "critical",
  primary_service: "payments-api",
  environment: "production",
  region: "us-east-1",
  created_at: "2026-10-21T11:54:00Z",
  updated_at: "2026-10-21T11:58:00Z",
  acknowledged_at: null,
  acknowledged_by: null,
  resolved_at: null,
  resolved_by: null,
  resolution_note: null,
  alert_count: 3,
  sources: ["cloudwatch", "prometheus"],
  affected_services: ["checkout-api", "payments-api"],
  age_seconds: 360,
  first_alert_at: "2026-10-21T11:54:00Z",
  last_alert_at: "2026-10-21T11:57:00Z",
  is_demo: false,
};

export const paymentsAlert: AlertRead = {
  id: 11,
  fingerprint: "a".repeat(64),
  source: "prometheus",
  source_alert_id: "demo-payments-error-rate",
  title: "Payment authorization errors above 5%",
  description: "The five-minute authorization error rate is 8.4%, above the 5% burn threshold.",
  severity: "critical",
  status: "firing",
  service: "payments-api",
  environment: "production",
  region: "us-east-1",
  labels: { alertname: "PaymentsAPIHighErrorRate" },
  source_metadata: { integration: "alertmanager" },
  enrichment: { owner: "Payments Platform", tier: "critical" },
  dedupe_key: "demo-payments-error-rate",
  occurred_at: "2026-10-21T11:54:00Z",
  received_at: "2026-10-21T12:00:00Z",
  last_seen_at: "2026-10-21T12:00:00Z",
  occurrences: 2,
  incident_id: 7,
  correlation: {
    rule: "new_incident",
    summary: "No open payments-api incident was inside the 15-minute window.",
    matched_on: ["service", "environment", "event_time_window"],
    window_minutes: 15,
    note: "This is the first grouped signal.",
  },
  is_demo: false,
  delivery_id: null,
};

export const checkoutAlert: AlertRead = {
  ...paymentsAlert,
  id: 12,
  fingerprint: "b".repeat(64),
  title: "Checkout error budget is burning",
  description: "Checkout success rate dropped after payment authorization failures increased.",
  severity: "high",
  service: "checkout-api",
  occurrences: 1,
  correlation: {
    rule: "topology_proximity",
    summary:
      "checkout-api is a direct upstream caller of payments-api (checkout-api → payments-api); the alert is within the 10-minute topology window.",
    matched_on: ["service_topology", "environment", "event_time_window"],
    window_minutes: 10,
    minutes_from_nearest_alert: 1.0,
    topology: {
      relation: "dependent",
      direction: "upstream",
      edge: { source: "checkout-api", target: "payments-api" },
      hops: 1,
    },
    note: "Topology proximity is triage context, not proof of causation.",
  },
};

export const paymentsService: Service = {
  id: "payments-api",
  name: "Payments API",
  description: "Authorizes and captures payments; owns the payment-intent state machine.",
  owner: "Payments Platform",
  team: "payments-platform",
  tier: "critical",
  environments: ["production", "staging"],
  depends_on: ["postgres-orders"],
  dependents: ["checkout-api"],
  repository: "example/payments-api",
  runbook: null,
};

export const checkoutService: Service = {
  ...paymentsService,
  id: "checkout-api",
  name: "Checkout API",
  description: "Cart validation, order orchestration, and checkout session management.",
  owner: "Checkout Experience",
  team: "checkout-experience",
  tier: "critical",
  depends_on: ["payments-api"],
  dependents: [],
};

export const postgresService: Service = {
  ...paymentsService,
  id: "postgres-orders",
  name: "Orders PostgreSQL",
  description: "Primary transactional database for orders and payment intents.",
  owner: "Data Platform",
  team: "data-platform",
  depends_on: [],
  dependents: ["payments-api"],
  repository: null,
};

export const serviceCatalog: ServiceCatalog = {
  services: [paymentsService, checkoutService, postgresService],
  edges: [
    { source: "checkout-api", target: "payments-api" },
    { source: "payments-api", target: "postgres-orders" },
  ],
  environments: ["production", "staging"],
  catalog_version: 1,
};

export const incidentDetail: IncidentDetail = {
  incident: paymentsIncident,
  alerts: [paymentsAlert, checkoutAlert],
  timeline: [
    {
      id: 1,
      event_type: "opened",
      message: "Incident opened for payments-api in production by the rule-based correlation engine.",
      actor: "Bamboo11y correlation",
      automated: true,
      occurred_at: "2026-10-21T11:54:00Z",
      details: { rule: "new_incident" },
    },
    {
      id: 2,
      event_type: "alert_linked",
      message: "Alert linked: Checkout error budget is burning",
      actor: "Bamboo11y correlation",
      automated: true,
      occurred_at: "2026-10-21T11:55:00Z",
      details: { rule: "topology_proximity" },
    },
  ],
  topology: {
    focus_service: paymentsService,
    service_found: true,
    owner: "Payments Platform",
    team: "payments-platform",
    tier: "critical",
    affected_services: ["checkout-api", "payments-api"],
    upstream: [checkoutService],
    downstream: [postgresService],
    transitive_upstream: [],
    transitive_downstream: [],
    edges: [
      { source: "checkout-api", target: "payments-api" },
      { source: "payments-api", target: "postgres-orders" },
    ],
    catalog_version: 1,
    disclaimer:
      "Topology comes from the checked-in service catalog. It is context, not evidence that one symptom caused another.",
  },
  nearby_changes: [
    {
      id: 3,
      service: "payments-api",
      version: "v2.14.0",
      environment: "production",
      region: "us-east-1",
      kind: "deployment",
      summary: "Canary rollout of the retry-budget refactor.",
      occurred_at: "2026-10-21T11:48:00Z",
      source: "demo-deploy-feed",
      is_demo: false,
      minutes_from_first_alert: -6.0,
      relation: "before_first_alert",
      relationship: "temporal_context_only",
      disclaimer:
        "Temporal proximity is context for investigation, not proof of causation. Bamboo11y does not calculate a root cause.",
    },
  ],
  change_context: {
    window_minutes: 120,
    first_alert_at: "2026-10-21T11:54:00Z",
    disclaimer:
      "Temporal proximity is context for investigation, not proof of causation. Bamboo11y does not calculate a root cause.",
  },
  notifications: [
    {
      id: 1,
      incident_id: 7,
      event_type: "opened",
      channel: "mock-slack",
      payload: { text: "[CRITICAL] Opened: payments-api" },
      status: "sent",
      attempts: 1,
      created_at: "2026-10-21T11:54:00Z",
      sent_at: "2026-10-21T11:54:00Z",
      last_error: null,
      is_demo: false,
    },
  ],
};

export const demoResult: DemoResult = {
  run_id: "abc123def456",
  scenario: "payments_degradation",
  primary_incident_id: 42,
  primary_alert_fingerprint: "c".repeat(64),
  incidents: [
    {
      id: 42,
      title: "payments-api: Payment authorization errors above 5%",
      status: "open",
      severity: "critical",
      primary_service: "payments-api",
      environment: "production",
      alert_count: 3,
      sources: ["cloudwatch", "prometheus"],
    },
    {
      id: 43,
      title: "search-api: Search latency warning",
      status: "open",
      severity: "medium",
      primary_service: "search-api",
      environment: "staging",
      alert_count: 1,
      sources: ["prometheus"],
    },
    {
      id: 44,
      title: "notifications-worker: Queue backlog",
      status: "open",
      severity: "medium",
      primary_service: "notifications-worker",
      environment: "production",
      alert_count: 1,
      sources: ["cloudwatch"],
    },
  ],
  alerts_received: 6,
  unique_alerts: 5,
  duplicate_deliveries: 1,
  notifications_delivered: 3,
  changes: [
    { id: 1, service: "payments-api" },
    { id: 2, service: "search-api" },
  ],
  summary: {
    headline:
      "A payments canary deployment coincided with a cross-source alert burst. Bamboo11y grouped the payment and checkout symptoms into one incident and kept unrelated signals separate.",
    primary_incident_id: 42,
    primary_incident_alert_count: 3,
    primary_incident_sources: ["cloudwatch", "prometheus"],
    primary_incident_affected_services: ["checkout-api", "payments-api"],
    nearby_change: {
      service: "payments-api",
      version: "v2.14.0",
      minutes_before_first_alert: 6.0,
      relationship: "temporal_context_only",
    },
    unrelated_incident_count: 2,
    disclaimer:
      "The deployment is shown as temporal context only; this scenario does not prove that it caused the incident.",
  },
};

export const integrationState: IntegrationState = {
  sources: [
    {
      source: "cloudwatch",
      display_name: "AWS CloudWatch",
      description: "Alarm state changes, direct or inside an SNS envelope.",
      endpoint: "/api/webhooks/alerts/cloudwatch",
      alerts_24h: 2,
      last_received_at: "2026-10-21T11:57:00Z",
    },
    {
      source: "prometheus",
      display_name: "Prometheus Alertmanager",
      description: "Native Alertmanager webhook groups.",
      endpoint: "/api/webhooks/alerts/prometheus",
      alerts_24h: 3,
      last_received_at: "2026-10-21T11:54:00Z",
    },
  ],
  rate_limit: {
    requests_per_minute: 120,
    scope: "per source and client address, per API process (in-memory)",
    note: "A reverse proxy or API gateway should enforce shared limits in production.",
  },
  idempotency: {
    strategy: "SHA-256(source + '|' + deduplication_key)",
    duplicate_behavior:
      "Repeat deliveries update occurrence count and last-seen time; they do not create a second alert, incident, or notification.",
    delivery_header: "X-Bamboo11y-Delivery-Id (retained as metadata; optional)",
  },
  notifications: {
    channel: "mock-slack",
    external_webhook_configured: false,
    counts: { sent: 4, pending: 0, failed: 0 },
    recent: incidentDetail.notifications,
    local_sink_note:
      "The default sink is the local outbox labelled mock-slack. Set BAMBOO11Y_NOTIFICATION_WEBHOOK_URL to exercise an HTTP receiver.",
  },
  mock_slack_endpoint: "/api/mock/slack",
};

export const emptyIncidentList = {
  items: [],
  total: 0,
  active_count: 0,
};
