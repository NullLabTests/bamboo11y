# ADR-0002: Deterministic correlation and idempotency

- **Status:** accepted
- **Date:** 2026-10-21
- **Deciders:** Bamboo11y maintainers
- **Related:** [spec §3.2–3.4](../spec.md), [architecture §5](../architecture.md)

## Context

The product must group related alerts without over-grouping, explain every grouping, survive
retries and late deliveries, and avoid claiming causality from nearby changes. The audience
includes on-call engineers who will ask “why is this alert in this incident?” and reviewers who
will test duplicate and out-of-order deliveries.

A black-box similarity score or ML clustering would be hard to test, hard to explain, and
easy to overclaim. The system needs a decision procedure that is reproducible from stored
inputs and configurable without code changes.

## Decision

Use ordered, deterministic rules with explicit windows and stored reasons.

### Identity and idempotency

- Fingerprint = `SHA-256(source + "|" + dedupe_key)`.
- Alertmanager dedupe key: supplied `fingerprint`, else a stable hash of sanitized labels.
- CloudWatch dedupe key: alarm ARN, else `region:account:alarmName`.
- A uniqueness constraint on `(fingerprint, is_demo)` makes retries safe even under
  concurrency.
- A repeat delivery updates occurrence count, last-seen time, and status; it does not create
  a second alert, incident, or notification.
- The optional `X-Bamboo11y-Delivery-Id` is metadata, not the identity. Sources may retry
  with a new delivery ID; the alert fingerprint is what matters.

### Correlation order

For a new fingerprint, consider non-resolved incidents in the same partition and
environment, then:

1. **Same service** within `CORRELATION_WINDOW_MINUTES` (default 15) → join the most recent
   matching incident.
2. **One-hop topology** within `TOPOLOGY_WINDOW_MINUTES` (default 10) → join when the alert
   service is a direct dependency or dependent of the incident's primary service. The reason
   includes direction and a non-causality note.
3. Otherwise **create a new incident**.

Event time, not receipt time, is used for window comparisons. Future timestamps beyond
`FUTURE_SKEW_TOLERANCE_SECONDS` are clamped for comparison and the original is retained in
metadata. A resolved-only delivery with no known incident is recorded for audit without
opening one.

### Lifecycle coupling

- A source resolution updates the alert but does not resolve a human-owned incident.
- If the same fingerprint fires again after its incident is resolved, the incident reopens
  with an audit event.
- Duplicate acknowledge/resolve actions are no-ops and do not create events or
  notifications.
- Incidents escalate to the maximum alert severity; they never silently de-escalate.

### Reasons are data

Each new alert stores a `correlation` object with `rule`, `summary`, `matched_on`, and the
incident ID. Topology reasons carry an explicit non-causality note. The UI renders the stored
reason rather than reconstructing it from current state, so the explanation remains
auditable if configuration changes later.

### Demo isolation

`is_demo` is part of every correlation query and uniqueness constraint. Demo data cannot join
live incidents and live data cannot join demo incidents. Reset removes only the demo
partition.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| ML clustering / embeddings | Not explainable per alert; nondeterministic; invites false AI claims; hard to test boundaries |
| Group by alertname only | Misses cross-source and cross-service symptoms; duplicates unrelated environments |
| Group everything by time window | Over-groups; the demo's unrelated incidents prove why that is bad |
| Sink-side dedupe only | Wastes storage, creates race conditions, loses occurrence history |
| Use delivery ID as identity | Sources can retry with new IDs; duplicates would leak through |
| Two-way/transitive topology joins | Pulls an entire dependency graph into one incident; one hop is a deliberate precision choice |
| Auto-resolve incident on source resolution | Removes human ownership and hides partial recovery |

## Consequences

### Positive

- Every grouping is reproducible and explainable.
- Retries, late alerts, and re-fires have tested, deterministic behavior.
- Windows and topology behavior are configuration, not hidden constants.
- The demo contract test is a meaningful regression eval.

### Negative

- Novel relationships that do not match a rule are not discovered.
- One-hop topology misses transitive blast radius.
- Rule order can produce surprising joins if windows are widened carelessly.
- The stored reason reflects the first decision, not a later re-evaluation.

### Mitigations

- Tests cover inside/outside windows, late arrival, topology direction, demo isolation, and
  duplicate notifications.
- README and UI repeat “context, not cause.”
- Window changes require updating the spec and scenario contract deliberately.

## Verification

- `backend/tests/test_idempotency.py`
- `backend/tests/test_correlation.py`
- `backend/tests/test_lifecycle.py`
- `backend/tests/test_demo_e2e.py`
- `backend/tests/test_end_to_end.py`

A change to rule order, windows, or the demo contract is not complete until these pass and
the docs are updated.
