# Bamboo11y — Requirements and design

**Status:** implemented  
**Last updated:** 2026-10-21  
**Related:** [`intent.md`](../intent.md), [`implementation-plan.md`](implementation-plan.md)

## 1. Experience summary

Bamboo11y is a local incident command center. Monitoring sources send webhooks; the
server validates and normalizes each alert, enriches it from a service catalog, deduplicates
it by fingerprint, and applies deterministic correlation rules. The dashboard exposes the
incident queue, the alert stream, the service catalog/topology, and the local notification
outbox. A demo action runs a deterministic scenario through the real ingestion pipeline.

## 2. Personas and jobs

| Persona | Job to be done | Product response |
|---|---|---|
| On-call engineer | “Which incident matters now?” | Ranked incident queue, severity/status, age, source mix |
| Incident commander | “Why are these alerts together?” | Rule-level correlation explanation per alert |
| Service owner | “What is affected and what did we change?” | Topology context and nearby changes, labelled as context only |
| Platform/Solutions architect | “How does this integrate and scale?” | Explicit adapters, contracts, ADRs, security/ops docs |

## 3. Functional requirements

### 3.1 Ingestion

- `POST /api/webhooks/alerts/prometheus` accepts Alertmanager webhook payloads.
- `POST /api/webhooks/alerts/cloudwatch` accepts a CloudWatch alarm state change, either
  directly or wrapped in an SNS notification envelope.
- `POST /api/webhooks/alerts/open-integration` accepts a vendor-neutral `{app, check,
  status, ...}` event (open-integration style; see `docs/inspirations.md`). States:
  `critical`/`warning`/`acknowledged` → firing (default severity critical/medium/high),
  `ok` → resolved (info). `app` + `check` is the deduplication key.
- Unknown sources return a helpful `404` listing supported sources.
- Malformed JSON, invalid schema, unsupported alert states, oversized payloads, and excess
  label cardinality return a consistent structured error; no partial writes occur for a
  rejected request.
- Each normalized alert contains source, source alert ID, title, description, normalized
  severity, firing/resolved status, service, environment, region, labels, source metadata,
  event time, receipt time, deduplication key, and internal fingerprint.
- An optional `X-Bamboo11y-Delivery-Id` (or `Idempotency-Key`) header is retained as
  metadata. It does not replace fingerprint idempotency.
- Per-process rate limiting applies to ingest routes. Default: 120 requests/minute per
  source and client address. A `429` includes `Retry-After`, limit, and remaining headers.
- No source payload body, authorization header, or secret is logged.

### 3.2 Normalization rules

| Field | Alertmanager | CloudWatch | Open Integration |
|---|---|---|---|
| Source ID | alert `fingerprint`, else stable hash of labels | `AlarmArn`, else region/account/alarm name | `app` + `check` |
| Service | `service`, `app`, `job`, `container`, else `unmapped-service` | `Service`/`service` dimension or tag, else `unmapped-service` | `service`/`Service` tag, else `app`, else `unmapped-service` |
| Environment | `environment`, `env`, `deployment_environment`, else `unknown` | `Environment` dimension/tag/field, else `unknown` | `environment`/`env` tag or field, else `unknown` |
| Region | `region` label, else null | `Region` field when canonical, else null | `region`/`zone` tag when canonical, else null |
| Status | per-alert `status`, falling back to top-level status | `ALARM`/`INSUFFICIENT_DATA` → firing; `OK` → resolved | `critical`/`warning`/`acknowledged` → firing; `ok` → resolved |
| Severity | normalized `severity` label; unrecognized → medium | explicit `Severity`/tag; else high for firing, info for resolved | explicit `severity`/tag for firing states; else `critical`→critical, `warning`→medium, `acknowledged`→high; `ok`→info |
| Title | `annotations.summary`, `alertname`, else default | `AlarmName`, optionally prefixed by SNS subject | `subject`, else `check` |
| Time | `startsAt`; fallback to receipt time | `StateChangeTime`/SNS `Timestamp`; fallback to receipt time | `timestamp`; fallback to receipt time |

Fingerprint format: `SHA-256(source + "|" + deduplication_key)`. Duplicate deliveries reuse
the same alert row and increment an occurrence counter. The stored correlation reason is
the one from the first grouping and remains inspectable.

### 3.3 Enrichment

- Catalog lookup supplies owner/team, tier, description, environments, runbook path, and
  direct/transitive dependency context.
- Missing catalog entries do not drop alerts. They render as unmapped with an explicit
  warning in the detail API/UI.
- Demo records have `is_demo=true`; correlation only compares records in the same demo/live
  partition, so a demo cannot pollute a live incident (and vice versa).

### 3.4 Correlation

Candidates are non-resolved incidents in the same demo/live partition, environment, and
correlation window. Rules are applied in this order:

1. **Existing fingerprint** → update the existing alert and linked incident. Never create a
   duplicate.
2. **Same service + environment + correlation key** (`service:environment` by default) →
   join the most recent open/acknowledged incident within `CORRELATION_WINDOW_MINUTES`.
3. **One-hop topology proximity** → join when the alert’s service is a direct dependency or
   dependent of the incident’s primary service, in the same environment, within
   `TOPOLOGY_WINDOW_MINUTES`. The reason includes the direction and a non-causality note.
4. Otherwise **open a new incident** with the alert’s severity and service.

Alert event timestamps are used to evaluate windows, so a late-delivered alert whose event
falls within the incident window can still join. Future-skewed timestamps are clamped for
comparison and surfaced in metadata. A source-resolved event updates the existing alert; it
does not automatically resolve a human-owned incident. If the same fingerprint fires again
after its incident was resolved, the incident is reopened with an audit event.

The response for every ingested alert contains `outcome` and a `correlation` object with
`rule`, `summary`, matched facts, and the incident ID. No model, embedding, or probabilistic
score is involved.

### 3.5 Incident lifecycle

- States: `open` → `acknowledged` → `resolved`.
- `open` may resolve directly. Repeated actions are idempotent and do not emit events or
  notifications. `resolved` cannot be acknowledged. A source re-fire may reopen a resolved
  incident; manual reopening is not exposed.
- Acknowledge/resolve accepts `actor` (default `local-operator`) and an optional note.
- Every transition and alert linkage writes an append-only `incident_events` row.
- Incidents show severity escalation (maximum alert severity), first/last alert time, age,
  affected services, source mix, and notification deliveries.

### 3.6 Changes

- The API can list and create deployment/config/rollback/feature-flag events.
- Incident detail returns changes for affected services and one-hop topology neighbors in
  the same environment, within a ±120-minute context window.
- Each result has `relationship: "temporal_context_only"` and a minutes-before-first-alert
  value. The UI repeats the disclaimer; no field is named or presented as root cause.

### 3.7 Notifications

- Incident lifecycle events enqueue a Slack-style message in an outbox.
- Default sink is local mock delivery; no credentials are required. An optional external
  webhook URL can be supplied by the operator through environment configuration.
- Each outbox row has a unique event-derived dedupe key, attempt count, status, and payload.
  Repeat alerts and repeat lifecycle actions cannot enqueue duplicates.
- If an external delivery fails, the incident operation still succeeds and the outbox row
  remains available for inspection/retry. No background worker is required for the demo.

### 3.8 Dashboard

- Overview: active incidents, alerts in the last 24 hours, services with active incidents,
  mean time to acknowledge (only when data exists), severity mix, 12-hour alert volume,
  source health, recent changes, and the demo entry point.
- Incidents: filter by status, severity, source, and service; search; responsive list.
- Incident detail: summary, lifecycle actions, rule explanations, alert timeline, topology
  context, nearby changes with disclaimer, and mock notification deliveries.
- Signals: normalized alert stream filterable by source, status, severity, service, and
  environment; source format and dedupe counts visible.
- Services: catalog cards, service detail with upstream (callers) and downstream
  (dependencies), transitive lists, recent changes, and a readable topology view.
- Integrations: actual source counts, endpoint copy controls, idempotency/rate-limit
  explanation, notification channel state, and a change-event form.
- Loading, empty, validation, and backend-error states are present. Severity/status use
  icon/text labels as well as color. Controls are keyboard accessible.

### 3.9 Demo

`POST /api/demo/run` accepts `{scenario, fresh}`. The default `payments_degradation`
scenario:

1. optionally deletes only `is_demo` records;
2. records a `payments-api` v2.14.0 canary change 12 minutes before the first alert;
3. ingests three Alertmanager alerts (payments production, checkout production, search
   staging);
4. ingests two CloudWatch alarms (payments production, notifications-worker production);
5. replays the first delivery to demonstrate idempotency.

Expected result: 5 unique alerts + 1 duplicate delivery, 3 incidents. The primary
`payments-api` incident has 3 alerts from 2 sources and 2 affected services; checkout joins
via one-hop topology. Search and notifications-worker produce unrelated incidents. The
change is available in the primary incident with temporal-context language.

### 3.10 Operational endpoints

- `/healthz` liveness; `/readyz` database + catalog readiness; `/api/health` dashboard health.
- `/metrics` Prometheus text exposition with HTTP, webhook, alert, incident, and
  notification metrics.
- Structured JSON request logs with request ID, status, duration; no bodies or headers.
- Security headers on responses; bounded request body; sanitized strings.

## 4. Non-functional requirements

- Local startup with Python 3.12+ and Node 20.19+ or 22.12+; Docker Compose optional.
- SQLite is the only required datastore. Database and generated files are gitignored.
- Deterministic tests use a controllable clock and isolated temp database.
- Default binds: API `127.0.0.1:8000`, Vite `127.0.0.1:5173`, Docker published to loopback.
- API and UI use explicit TypeScript/Pydantic contracts; no fake dashboard numbers.
- A production deployment is explicitly out of scope and its gaps are documented.

## 5. API surface

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Dashboard health |
| GET | `/healthz`, `/readyz` | Liveness/readiness |
| POST | `/api/webhooks/alerts/{source}` | Alert ingestion |
| GET | `/api/overview` | Dashboard data |
| GET | `/api/incidents` | Filtered incident summaries |
| GET | `/api/incidents/{id}` | Full incident context |
| PATCH | `/api/incidents/{id}/status` | Acknowledge/resolve |
| GET | `/api/alerts` | Filtered alert stream |
| GET | `/api/alerts/{id}` | Single alert |
| GET | `/api/services` | Catalog + edges |
| GET | `/api/services/{id}` | Service context + changes |
| GET | `/api/changes` | Change events |
| POST | `/api/changes` | Record a change |
| GET | `/api/integrations` | Integration/outbox state |
| GET | `/api/notifications` | Notification outbox |
| POST | `/api/demo/run` | Deterministic demo |
| POST | `/api/demo/reset` | Reset demo partition |
| GET | `/metrics` | Prometheus metrics |

## 6. UX design principles

- **Signal over decoration:** every number is computed from persisted data.
- **Explain before asking for trust:** correlation reasons appear on the alert and incident.
- **Context is not cause:** nearby changes are styled as context and carry a visible note.
- **Calm incident command:** high information density with generous spacing, strong
  hierarchy, and restrained amber accents on a graphite surface.
- **Accessible by default:** text labels with every color-coded state, semantic controls,
  skip link, visible focus, reduced-motion support, responsive layouts, and explicit
  loading/empty/error states.

## 7. Out of scope / production gaps

Authentication/authorization, tenant isolation, durable queue/worker, distributed rate
limiting, HA SQLite replacement, retention/archival, secret manager, alert suppression
windows, escalation policies, external ticketing, and formal SLO tracking. See
[`operations.md`](operations.md) and ADR-0003.
