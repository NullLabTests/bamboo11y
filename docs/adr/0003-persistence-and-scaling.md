# ADR-0003: Persistence, delivery, and scale path

- **Status:** accepted
- **Date:** 2026-10-21
- **Deciders:** Bamboo11y maintainers
- **Related:** [operations](../operations.md), [security](../security.md)

## Context

Bamboo11y must run locally with no external services, but it should not pretend that a
single SQLite file is a production incident platform. The design needs to be honest about
durability, concurrency, delivery guarantees, and the migration path.

The workload is small and bursty: webhook batches, dashboard reads, lifecycle writes, and
notification dispatch. There is no background worker in the demo. Notification delivery must
not lose messages when a sink is down, and retries must not duplicate messages.

## Decision

### Persistence

- SQLite is the system of record. The schema uses real constraints and indexes:
  unique `(fingerprint, is_demo)` alerts, unique notification dedupe keys, unique change
  external IDs, and indexes for active incidents and alert lookup.
- A single SQLAlchemy session per request owns the transaction. Ingestion batches are
  all-or-nothing.
- SQLite foreign keys, WAL-friendly settings, and a busy timeout are configured at engine
  creation where supported.
- The database path is operator configuration; generated databases are gitignored.

### Delivery

- Use a transactional outbox: notification rows are written in the same transaction as the
  incident/audit change, then dispatched.
- The default sink is a local mock-Slack record. An optional HTTP webhook is
  operator-configured and time-bounded.
- Dedupe key = incident + event. A retry of the same event cannot enqueue a second row.
- Dispatch failure leaves a `pending`/`failed` row; incident state is already committed. A
  manual retry endpoint re-dispatches pending/failed rows.
- There is no background poller in the demo. Dispatch happens after webhook ingestion and
  lifecycle actions; a production deployment should add a worker.

### Runtime

- One uvicorn process serves the API, SPA, health, and metrics.
- Rate limiting is an in-process sliding window keyed by client + source. It is a guardrail,
  not a security boundary.
- The container runs as a non-root user with a read-only root filesystem and a `/data`
  volume for SQLite.

## Rationale

- SQLite removes a setup dependency and makes the demo inspectable (`sqlite3` or any viewer).
- The outbox pattern is the smallest design that separates “incident committed” from
  “notification delivered” without lying about durability.
- A single process keeps the demo reproducible and avoids distributed-systems failure modes
  that would distract from correlation quality.
- The constraints are the real idempotency backstop; service logic handles the friendly
  behavior around them.

## Consequences

### Positive

- Zero external infrastructure; fast tests; simple backup (one file).
- No lost notification intent on sink failure.
- Clear migration seam: SQLAlchemy models, a repository-ish service layer, and a transactional
  outbox.

### Negative / risks

| Risk | Impact | Mitigation |
|---|---|---|
| SQLite single writer | Write contention under load | Short transactions; move to Postgres for multi-instance |
| Process-local rate limit | Bypass by restart or multiple replicas | Shared limiter/gateway in production |
| Synchronous dispatch | Slow sink increases request latency | Timeout; move to worker; outbox already durable |
| No retention policy | Database grows indefinitely | Add retention/archival job |
| No HA/backups automated | Data loss on disk failure | Documented backup; production managed Postgres |
| Schema evolution | Manual migration risk | Introduce Alembic before multi-user deployment |
| In-process metrics | Counters reset on restart | Scrape with Prometheus; long-term store externally |

## Production migration path

1. **Database:** move to PostgreSQL, add Alembic migrations, enable encrypted storage and
   point-in-time recovery. Keep the unique constraints.
2. **Delivery:** add a worker consuming the outbox with exponential backoff, dead-lettering,
   and per-sink circuit breaking. Make dispatch asynchronous from ingestion.
3. **Rate limiting:** move to Redis or the API gateway, keyed by verified source identity,
   with quotas and observability.
4. **Auth:** add OIDC/SSO at a proxy or in-app, RBAC for acknowledge/resolve/change, and
   verified actor identity in the audit trail.
5. **Scale reads:** add replicas only after the write path is on Postgres; keep correlation
   transactional per incident.
6. **Retention:** partition/archive alerts and notifications; define deletion and legal hold.
7. **Observability:** add tracing, centralized logs, dashboards, and SLOs. Keep the existing
   metric names where possible.
8. **Deployment:** TLS, secret manager, image signing/SBOM, dependency scanning, and a
   staged rollout with rollback.

None of these are implemented. The current repository is a local demonstration and says so
in the README, operations, and security docs.

## Verification

- `backend/tests/test_idempotency.py` — retries and unique constraints
- `backend/tests/test_lifecycle.py` — audit and duplicate actions
- `backend/tests/test_end_to_end.py` — ingest → incident retrieval
- `backend/tests/test_demo_e2e.py` — demo partition and contract
- CI container job — image build and readiness smoke test

## Notes

SQLite is appropriate for the stated local-first goal. It is not appropriate for a
multi-tenant, highly available incident platform. Stating that boundary is part of the
design, not an apology.
