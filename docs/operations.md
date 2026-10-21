# Bamboo11y operations

**Scope:** running, checking, and recovering the local Bamboo11y deployment.  
**Audience:** the operator or reviewer who needs to start it, demo it, or debug it.

## 1. Runtime shape

| Process | Default bind | Purpose |
|---|---|---|
| FastAPI/uvicorn | `127.0.0.1:8000` | JSON API, SPA, health probes, metrics |
| Vite (development only) | `127.0.0.1:5173` | Hot-reload dashboard, proxies `/api` to the API |
| Prometheus (optional profile) | `127.0.0.1:9090` | Scrapes `/metrics` |
| Alertmanager (optional profile) | `127.0.0.1:9093` | Delivers example alerts back to the webhook |

Local state is a single SQLite file, `data/bamboo11y.db` by default. The catalog is
`config/services.yaml`. There is no background worker, message broker, or external account.

## 2. Prerequisites

- Python 3.12+ (CI covers 3.12 and 3.13)
- Node.js 20.19+ or 22.12+ for the dashboard build
- `make` and a POSIX shell
- Docker only for the container path; it was unavailable in the authoring environment

## 3. Start and stop

### Local, production-style dashboard

```bash
make setup
make run
```

`make run` builds the React app into `frontend/dist`, then starts uvicorn with the app
factory. Open <http://127.0.0.1:8000>.

Stop with `Ctrl-C`. The SQLite file remains.

### Local development

```bash
make dev
```

Starts uvicorn with `--reload` and Vite on `:5173`. The dev runner waits for `/healthz`
before starting Vite and kills the API when Vite exits. If port 8000 or 5173 is busy, set
`PORT`/`HOST` for the API; Vite's proxy uses `BAMBOO11Y_API_URL` and is strict on 5173.

### Container

```bash
make docker-up
make docker-logs
make docker-down
```

The image is multi-stage (Node build → Python runtime), runs as the `bamboo11y` user with
a read-only root filesystem, persists `/data`, drops all capabilities, and uses a health
check. The Compose file publishes only to loopback.

> **Verified where it matters:** the container image is built and smoke-tested by CI on every
> push. Compose orchestration itself was not executed in the authoring environment (no Docker
> daemon), so treat `docker compose up` as verified only after your own first run. See
> [`docs/operations.md`](docs/operations.md) for the unverified-paths note.

### Observability profile

```bash
docker compose --profile observability up -d
```

This starts Prometheus and Alertmanager alongside Bamboo11y. Prometheus scrapes
`http://bamboo11y:8000/metrics`; the example rules produce alerts; Alertmanager posts them
to `http://bamboo11y:8000/api/webhooks/alerts/prometheus`. The example
`Bamboo11yActiveIncidents` rule is an intentional feedback loop for demonstrating
ingestion. Remove or tune it if you only want operational alerts.

## 4. Configuration

Settings come from environment variables with the `BAMBOO11Y_` prefix, optionally loaded
from `.env` in the working directory. Environment variables win over `.env`.

| Variable | Default | Operational note |
|---|---|---|
| `BAMBOO11Y_ENVIRONMENT` | `local` | Shown in health and logs |
| `BAMBOO11Y_DATABASE_URL` | `sqlite:///./data/bamboo11y.db` | Parent directory is created |
| `BAMBOO11Y_SERVICE_CATALOG_PATH` | `config/services.yaml` | Restart after editing |
| `BAMBOO11Y_STATIC_DIR` | `frontend/dist` | Missing directory means API-only |
| `BAMBOO11Y_CORRELATION_WINDOW_MINUTES` | `15` | Same-service join window |
| `BAMBOO11Y_TOPOLOGY_CORRELATION_ENABLED` | `true` | One-hop joins |
| `BAMBOO11Y_TOPOLOGY_WINDOW_MINUTES` | `10` | Topology join window |
| `BAMBOO11Y_CHANGE_CONTEXT_WINDOW_MINUTES` | `120` | Nearby-change ± window |
| `BAMBOO11Y_FUTURE_SKEW_TOLERANCE_SECONDS` | `300` | Clamp future alert times |
| `BAMBOO11Y_RATE_LIMIT_PER_MINUTE` | `120` | Per client + source, per process; `0` disables |
| `BAMBOO11Y_MAX_PAYLOAD_BYTES` | `1000000` | Body cap |
| `BAMBOO11Y_MAX_ALERTS_PER_REQUEST` | `100` | Batch cap |
| `BAMBOO11Y_CORS_ORIGINS` | `http://127.0.0.1:5173,http://localhost:5173` | Dev server origins |
| `BAMBOO11Y_LOG_LEVEL` | `INFO` | DEBUG/INFO/WARNING/ERROR/CRITICAL |
| `BAMBOO11Y_LOG_JSON` | `true` | Set `false` for readable local logs |
| `BAMBOO11Y_NOTIFICATION_WEBHOOK_URL` | unset | Optional HTTP sink; no credentials in URL |
| `BAMBOO11Y_NOTIFICATION_TIMEOUT_SECONDS` | `5` | Webhook timeout |

Run `make validate` after changing configuration or delivery files. It checks the catalog,
documented settings, Compose wiring, CI shape, and obvious committed secrets.

## 5. Health, readiness, and metrics

| Endpoint | Meaning | Use |
|---|---|---|
| `/healthz` | Process is alive; no dependencies | Liveness probe |
| `/readyz` | SQLite query + catalog loaded | Readiness probe; returns 503 when not ready |
| `/api/health` | Version, environment, DB status, catalog count/version | Dashboard and support |
| `/metrics` | Prometheus text exposition | Scraping and debugging |
| `/api/stats` | Alert/incident counts (not in OpenAPI) | Smoke tests |

Metrics:

| Metric | Type | What it tells you |
|---|---|---|
| `bamboo11y_http_requests_total` | counter | Requests by method and status class |
| `bamboo11y_http_request_duration_seconds` | histogram | Request latency by method |
| `bamboo11y_webhook_requests_total` | counter | Webhook outcomes by source |
| `bamboo11y_alerts_ingested_total` | counter | Alert outcomes by source and result |
| `bamboo11y_incidents_created_total` | counter | Incidents created by correlation |
| `bamboo11y_notifications_total` | counter | Outbox attempts by result |
| `bamboo11y_incidents_active` | gauge | Open + acknowledged incidents |
| `bamboo11y_incidents_total` | gauge | All persisted incidents |
| `bamboo11y_alerts_firing` | gauge | Alerts currently firing |
| `bamboo11y_catalog_services` | gauge | Services loaded from YAML |

The gauges refresh when `/metrics` is scraped. Counters reset when the process restarts;
they are process-local, not durable analytics. Alert counters instrument external webhook
deliveries; the demo endpoint records incidents and notifications in the counters, while the
gauges include every persisted row (demo and live).

Quick checks:

```bash
curl -fsS http://127.0.0.1:8000/readyz
curl -fsS http://127.0.0.1:8000/metrics | grep '^bamboo11y_'
curl -fsS http://127.0.0.1:8000/api/stats
```

## 6. Logs

Request logs are structured JSON by default:

```json
{"timestamp":"2026-10-21T12:00:00.000000Z","level":"info","logger":"bamboo11y.request","message":"request completed","request_id":"8f...","method":"POST","path":"/api/webhooks/alerts/prometheus","status":201,"duration_ms":12.4}
```

Request IDs are returned in `X-Request-ID`. Supply your own only with 1–64 characters from
`A-Z a-z 0-9 . _ -`; otherwise the server generates one. Logs do not include request bodies,
authorization headers, or notification URLs.

For readable local logs:

```bash
BAMBOO11Y_LOG_JSON=false make run
```

## 7. Routine tasks

### Run the demo

```bash
make demo          # requires a running API
make demo-reset    # removes demo-partition rows only
```

The demo is deterministic and isolated by `is_demo`. It does not delete live alerts,
incidents, changes, or notifications.

### Send and resolve an alert

```bash
python scripts/simulate.py prometheus
python scripts/simulate.py prometheus --status resolved
python scripts/simulate.py cloudwatch --state ALARM
python scripts/simulate.py cloudwatch --state OK
```

The simulator sends the same payloads a real source would. `--repeat` is useful for
idempotency demonstrations.

### Retry the notification outbox

```bash
curl -fsS -X POST 'http://127.0.0.1:8000/api/notifications/dispatch?include_failed=true'
curl -fsS http://127.0.0.1:8000/api/notifications | python3 -m json.tool
```

Failed rows remain inspectable. The incident operation is not rolled back when a sink is
unavailable.

### Change the service catalog

1. Edit `config/services.yaml`.
2. Run `make validate`.
3. Restart the API (`make run` or `make dev`).

Validation covers duplicate IDs, unknown dependency targets, self-dependencies, and cycles.

### Back up and restore SQLite

Stop the API for a consistent copy, or use SQLite's backup API while it runs:

```bash
.venv/bin/python - <<'PY'
import sqlite3
source = sqlite3.connect("data/bamboo11y.db")
target = sqlite3.connect("data/bamboo11y.backup.db")
with target:
    source.backup(target)
source.close()
target.close()
PY
```

Restore by stopping the API, replacing `data/bamboo11y.db` with the backup, and starting
again. The database contains no secrets, but it may contain alert metadata; handle it as
operational data.

### Full reset (destructive)

Stop the API, then remove the database file. This deletes **all** live and demo data:

```bash
rm data/bamboo11y.db
```

The schema is recreated on the next start. `make clean` does **not** delete `data/`.

## 8. Failure modes and responses

| Symptom | Likely cause | Response |
|---|---|---|
| `readyz` returns 503, `database: error` | Missing/unwritable DB path, disk full | Check permissions and free space; set `BAMBOO11Y_DATABASE_URL` to a writable path |
| Startup fails with `CatalogError` | Invalid YAML, duplicate ID, unknown dependency, cycle | Run `make validate`, fix `config/services.yaml` |
| Webhook returns 404 `unsupported_source` | Wrong URL | Use `/api/webhooks/alerts/prometheus` or `/cloudwatch` |
| Webhook returns 422 with `errors` | Payload shape or missing required fields | Compare with the adapter fixtures and README examples |
| Webhook returns 413 | Body or alert count cap | Coalesce batches or adjust caps deliberately |
| Webhook returns 429 | Rate limit | Honor `Retry-After`; check per-process limits; coalesce alerts |
| Duplicate delivery returns 200 | Fingerprint already seen | Expected; inspect `occurrences` and `last_seen_at` |
| Incident not grouped as expected | Outside window, different environment, or more than one hop | Inspect the alert's `correlation` reason; adjust windows only with tests |
| Notification row `failed` | Sink unavailable/timeout | Fix the receiver, then dispatch with `include_failed=true` |
| Dashboard shows API error | API down or CSP/proxy mismatch | Check `/readyz` and browser console; use `make dev` if Vite proxy is wrong |
| Port already in use | Another process | Set `PORT` or stop the other process; Vite uses 5173 |
| Container unhealthy | DB volume permissions | Ensure the volume is writable by the non-root user; inspect `docker logs` |

## 9. Release and rollback (local)

There is no hosted deployment pipeline. The release unit is a reviewed git commit and a
green CI run.

1. `make check`
2. Exercise the live demo once (`make run` + `make demo`).
3. Commit focused changes.
4. Tag only after CI is green and the demo numbers match the contract.
5. Roll back by checking out the previous commit and restarting. The SQLite schema is
   created idempotently; back up the database before changing model definitions.

Any externally visible action (publishing a repository, deploying, changing production
data) requires explicit human approval. The project intentionally does not auto-deploy.

## 10. Scale and production notes

The current design is a single-process modular monolith with SQLite. For production:

- move to PostgreSQL and a migration tool; treat SQLite-only SQL as a portability bug;
- move notification dispatch to a durable worker/queue with retries and dead-lettering;
- replace the in-memory rate limiter with a shared store (Redis/gateway);
- add authentication, authorization, tenant isolation, and audit identity;
- terminate TLS at a proxy and add CSRF/CORS review for any cookie-based auth;
- add retention/archival, suppression windows, escalation policies, and ticketing;
- add HA, backups with restore drills, and SLO/error-budget reporting.

ADR-0003 contains the detailed migration path. None of these are claimed as implemented.

## 11. Known environment limitations

- Docker/Compose were not executable in the authoring environment (no daemon). Compose is
  statically validated and the image is built + smoke-tested in CI; orchestration itself
  remains unexercised.
- The rate limiter is per process and resets on restart; it is not a security boundary for a
  public deployment.
- The dashboard has no authentication because the product is local-first and single-user.
- The optional Prometheus/Alertmanager profile uses pinned images but was not run locally;
  review the configs before relying on them.
