# Bamboo11y security

**Scope:** the local-first demonstration as shipped. This is a security review aid, not a
certification. The system is not intended to be exposed to the public internet.

## 1. Security posture in one paragraph

Bamboo11y accepts untrusted JSON from two alert-source formats, validates it against strict
schemas, caps its size and cardinality, normalizes it, and stores it in a local SQLite
database. There is no authentication or tenant model because the product is designed for a
single local operator. The container runs as a non-root user with a read-only root
filesystem, all capabilities dropped, and `no-new-privileges`. The main residual risks are
the absence of authn/authz, per-process rate limiting, and the operator-supplied notification
URL being a potential SSRF primitive if misconfigured.

## 2. Assets and trust boundaries

| Asset | Why it matters | Where it lives |
|---|---|---|
| Alert payloads and labels | May contain internal service names, regions, and incident details | SQLite `alerts` |
| Incident history and audit events | Operational truth and accountability | SQLite `incidents`, `incident_events` |
| Service catalog | Topology and ownership | `config/services.yaml` |
| Notification content | May include incident summaries | SQLite `notifications`; optional external sink |
| Configuration | DB path, webhook URL, windows, limits | Environment / `.env` |
| API availability | Dashboard and ingestion | Local process |

Trust boundaries:

1. **Internet/LAN → webhook endpoint.** Untrusted JSON, headers, and client address.
2. **Browser → API.** Same-origin dashboard in the served build; dev uses Vite proxy.
3. **API → filesystem.** SQLite path and catalog path are operator-controlled.
4. **API → notification sink.** Optional outbound HTTP to an operator-controlled URL.
5. **Container → host.** Loopback-published port, non-root user, read-only rootfs, `/data`
   volume.

## 3. Threat model

| Threat | Impact | Controls | Residual risk |
|---|---|---|---|
| Malformed or hostile webhook JSON | Crash, resource exhaustion, injection | Pydantic schemas, strict types, body cap, alert cap, label sanitization, JSON object requirement | Parser zero-days; bounded but nonzero |
| Oversized payload / alert flood | Memory/CPU/DB exhaustion | `Content-Length` + read-path cap, `max_alerts_per_request`, per-source rate limit | Distributed flood; limiter is per process |
| Duplicate/replayed deliveries | Duplicate incidents or notifications | Fingerprint uniqueness per partition, occurrence updates, event-scoped outbox keys | Source changes fingerprint for the same condition |
| SQL injection | Data disclosure/alteration | SQLAlchemy parameter binding; no string-built SQL from input | ORM/driver vulnerabilities |
| XSS in dashboard | Session/data compromise (no auth session today) | React escaping, no `dangerouslySetInnerHTML`, CSP `script-src 'self'`, no inline scripts | Malicious dependency or browser bug |
| Clickjacking | UI redress | `X-Frame-Options: DENY`, `frame-ancestors 'none'` | None known |
| MIME sniffing | Content-type confusion | `X-Content-Type-Options: nosniff` | None known |
| Sensitive data in logs | Internal detail leakage | No body/header/URL logging; request ID only | Exception messages could include data; review before production |
| Secret leakage in repo | Credential compromise | `.gitignore`, `.env.example` placeholders, config validator secret scan, no external accounts required | Human error; scan is pattern-based |
| Notification SSRF | Probe internal network via webhook URL | URL must be `http(s)`, credentials rejected, operator-only setting, 5s timeout | Operator can still point at internal hosts; restrict egress in production |
| Container escape / privilege | Host compromise | Non-root, read-only rootfs, `cap_drop: ALL`, `no-new-privileges`, loopback port | Kernel/runtime vulnerabilities; keep images updated |
| Demo/live contamination | Misleading incidents | `is_demo` partition on all queries and uniqueness constraints | Bugs in a new query that omits the partition; tests cover core paths |
| Unauthorized ack/resolve | False operational state | None (local single-user design) | **High if exposed**; add auth before any shared deployment |

## 4. Implemented controls

### Input handling

- Alertmanager and CloudWatch payloads are validated by Pydantic models with field types,
  length limits, and `extra="allow"` only where source formats require forward compatibility.
- Adapters reject unsupported states, missing alarm identity, non-JSON SNS messages, and
  malformed structures with structured errors instead of guessing.
- Labels are sanitized and bounded; strings are cleaned and truncated before storage.
- Request bodies must be JSON objects. Empty bodies and oversized bodies are rejected before
  ingestion. Batch size is capped.
- Future timestamps beyond the skew tolerance are clamped for correlation and the original
  value is retained in metadata.

### Idempotency and integrity

- Alert identity is `SHA-256(source|dedupe_key)` with a uniqueness constraint on
  `(fingerprint, is_demo)`. A retry updates occurrence/last-seen fields; it does not create a
  second alert or incident.
- Notification identity is derived from the incident event, with a unique `dedupe_key`.
  Repeat lifecycle actions produce no event and no notification.
- A batch is transactional: validation failures do not leave partial alerts.
- Lifecycle transitions are guarded by a state machine; invalid transitions return 409 and do
  not write audit events.

### HTTP and browser

- Security headers on every response: CSP, `X-Frame-Options: DENY`, `Referrer-Policy:
  no-referrer`, `Permissions-Policy`, `X-Content-Type-Options: nosniff`.
- The dashboard CSP is self-only. Swagger/ReDoc get a narrowly scoped CDN exception.
- Request IDs are validated against a safe pattern to prevent log/header injection.
- CORS is limited to the configured dev origins, with credentials disabled.
- Errors have stable machine codes and hints without stack traces.

### Operations

- Structured logs exclude request bodies, authorization headers, and notification URLs.
- Health/readiness separate liveness from dependency checks.
- Parameters are validated at startup (windows, limits, log level); the catalog is validated
  for duplicate IDs, unknown dependencies, self-dependencies, and cycles.
- Container: multi-stage build, pinned major toolchain, non-root user, read-only rootfs,
  `tmpfs` for `/tmp`, dropped capabilities, loopback-only publish.
- Optional notification webhook is operator-configured, must use HTTP(S), and rejects
  embedded credentials.
- The config validator scans the working tree for credential-shaped strings.

## 5. Deliberate non-controls

These are **not implemented** and must not be implied:

- authentication, sessions, API keys, RBAC, or tenant isolation;
- TLS termination or HSTS (local HTTP only);
- CSRF protection (there are no cookies or authenticated state);
- distributed rate limiting, WAF, or bot protection;
- audit identity verification (actors are self-asserted strings);
- secret manager integration;
- data retention, encryption at rest, or secure deletion;
- egress allow-listing for the optional notification sink;
- dependency scanning/SBOM in CI (only npm audit during development, not a gate).

## 6. Production hardening checklist

Before exposing any shared deployment:

- [ ] Put the API behind TLS and an authenticated reverse proxy or identity-aware proxy.
- [ ] Add authorization for acknowledge/resolve and change creation; record verified actor
      identity in the audit trail.
- [ ] Move to PostgreSQL with encrypted storage and tested backups.
- [ ] Replace the in-memory limiter with a shared gateway/Redis limiter and add request
      quotas per source.
- [ ] Allow-list notification egress destinations; keep URLs in a secret manager.
- [ ] Add retention and archival for alerts, incidents, and notification payloads.
- [ ] Add dependency and image scanning, SBOM generation, and pinned digests.
- [ ] Review CSP and CORS for the chosen auth model; add CSRF protection if cookies are used.
- [ ] Add centralized logs with access control and alerting on auth/admin actions.
- [ ] Run a threat-model review for multi-tenant isolation before adding tenants.

## 7. Verification evidence

| Control | Evidence |
|---|---|
| Invalid/oversized/unsupported payloads rejected | `backend/tests/test_validation.py` |
| Duplicate deliveries do not duplicate data | `backend/tests/test_idempotency.py` |
| Correlation boundaries and late alerts | `backend/tests/test_correlation.py` |
| Lifecycle guards and audit | `backend/tests/test_lifecycle.py` |
| Source normalization | `backend/tests/test_normalization.py` |
| Demo cannot pollute live partition | `backend/tests/test_demo_e2e.py` |
| Config/catalog/secret scan | `scripts/validate_config.py` |
| Headers and limits | Manual smoke test and middleware code review |

## 8. Reporting

This is a portfolio project without a security response team. If you find a vulnerability,
open a private security advisory on the repository rather than a public issue, and include a
minimal reproduction. Do not test against systems you do not own. No bug bounty is offered.

## 9. Known limitations

- The local environment had no Docker daemon, so Compose orchestration was not run. The image
  is built and smoke-tested by CI (run `39692358695`); a local `docker compose up` remains
  the strongest remaining verification.
- GitHub Actions and dependency versions can change; re-run CI before relying on an old run.
- The secret scan is a guardrail, not a substitute for GitHub secret scanning or a dedicated
  tool.
