# Five-minute demo script

**Goal:** show a complete, honest incident workflow in five minutes without slides or
hand-waving. The demo uses the real ingestion path and real persisted data.

## Preflight (before the audience arrives)

```bash
make setup            # once
make run              # build + API + dashboard on http://127.0.0.1:8000
curl -fsS http://127.0.0.1:8000/readyz
```

Open two tabs:

1. <http://127.0.0.1:8000> — overview and demo runner
2. <http://127.0.0.1:8000/docs> — API surface (optional)

Have a terminal ready for the webhook path:

```bash
make demo
```

If the demo was run before and the primary incident already exists, use **Reset demo data**
or `make demo-reset`. The demo is isolated, so this will not touch live data.

## 0:00–0:45 — Frame the problem

> “On-call engineers do not suffer from a shortage of alerts. They suffer from not knowing
> which alerts belong together, why they belong together, and what changed nearby. Most
> correlation demos hide that reasoning. This one exposes it.”

Set the guardrails immediately:

- It is local-first: SQLite, no accounts, no cloud services.
- It is rule-based, not AI. There is no model and no probabilistic score.
- Deployments are shown as **temporal context, not proof of cause**.
- It is an independent project, not a vendor reproduction.

## 0:45–1:30 — Run the scenario

Click **Run demo scenario** on the overview.

> “This sends five unique alerts through the same webhook adapters and ingestion service as
> a real Alertmanager or CloudWatch source, plus one deliberate retry.”

Point at the result panel:

- **6 received · 5 unique · 1 duplicate**
- **3 incidents**
- primary incident has **3 alerts from 2 sources**
- a deployment **6.0 minutes before the first alert**
- two unrelated incidents preserved

> “The duplicate is not discarded silently. The alert row records the occurrence, and no
> second incident or notification is created.”

Terminal alternative:

```bash
make demo
```

## 1:30–2:30 — Overview and queue

Return to the overview.

- Active incidents, alerts in the last 24 hours, affected services.
- Alert volume chart and severity mix are derived from rows, not seeded UI numbers.
- Source health shows the last delivery from each adapter.
- The incident queue is ranked by recency/severity; filters live in the URL.

Open **Incidents**. Point out:

- the primary payments incident is critical, the other two are separate;
- search is in staging, notifications-worker is a different service — they were not swept
  into the payments incident;
- filters and pagination are shareable/refresh-safe.

## 2:30–3:30 — Explain the grouping

Open the primary incident.

Walk down the detail page:

1. **Alerts:** payments production and checkout production, plus the CloudWatch latency
   alarm. The primary is `payments-api`.
2. **Why these are together:** each alert shows the stored rule and matched facts.
   - payment alert: same service + environment window;
   - checkout alert: one-hop topology (`checkout-api` depends on `payments-api`);
   - CloudWatch payment alarm: same service, cross-source.
3. **Topology:** affected services, direct dependencies, and dependents. The engine only
   joins one hop, on purpose, to avoid giant incidents.
4. **Nearby changes:** `payments-api v2.14.0` six minutes before the first alert, labeled
   `temporal_context_only`.

> “This is the most important sentence in the demo: the deployment is context. The product
> does not say it caused the incident. There is no root-cause field, and the disclaimer is
> in the data contract and the UI.”

Mention late/retry behavior:

> “Windows use event time, not receipt time. A late delivery can still join. A re-fire after
> resolution reopens the incident with an audit event. A source resolution does not silently
> resolve a human-owned incident.”

## 3:30–4:15 — Act on it

Click **Acknowledge**, optionally add a note.

- The status changes to acknowledged.
- The timeline gains an append-only audit event with actor and timestamp.
- A notification is queued and dispatched to the local mock-Slack outbox.
- Clicking acknowledge again is a no-op: no duplicate event, no duplicate notification.

Then **Resolve** with a short note. Open the **Integrations** page and show the outbox rows
and channel state. Emphasize that no real Slack workspace was contacted; the default sink is
local and clearly labeled. An operator can set `BAMBOO11Y_NOTIFICATION_WEBHOOK_URL` to
exercise a real receiver.

## 4:15–4:45 — Show the seam

Open **Signals**:

- both source formats in one normalized stream;
- severity/status/service/environment filters;
- dedupe counts and source metadata.

Optional terminal:

```bash
python scripts/simulate.py prometheus
python scripts/simulate.py cloudwatch --state ALARM
```

> “The simulator uses only the standard library and the public webhook endpoints. You can
> inspect the exact payload with `--dry-run`.”

## 4:45–5:00 — Close on engineering quality

> “The interesting part is not the dashboard. It is that the scenario is a contract test,
> the correlation reasons are stored, the demo cannot pollute live data, and the full gate
> runs in CI. The repo includes the spec, three ADRs, security/ops docs, and the discovery
> narrative.”

Open `docs/sdlc.md` or the CI badge if there is time. Be explicit about limits:

- no auth or multi-tenancy; local-first only;
- Docker Compose was not executable in the authoring environment; CI builds the image and
  smoke-tests readiness on every push; compose `up` itself remains unexercised.
- SQLite is single-writer; ADR-0003 describes the production path.

## Likely questions

**Is this AI/ML?**  
No. It is deterministic rule correlation with stored explanations. Calling it AI would be
inaccurate and would make the demo less trustworthy.

**What happens if two alerts arrive out of order?**  
Windows use event time. A late alert within the window can join; future-skewed timestamps are
clamped and surfaced. Tests cover late arrival.

**Why not group everything by service?**  
That over-groups across unrelated environments and time. The demo deliberately keeps search
(staging) and notifications-worker separate to prove the boundary.

**Why one-hop topology?**  
It captures the common caller/callee blast radius without pulling an entire dependency graph
into one incident. It is a deliberate precision/recall tradeoff, tested at the boundary.

**What if the notification sink is down?**  
The incident commit succeeds and the outbox row stays pending/failed for retry. Notifications
never block incident state.

**How do you know the dashboard numbers are real?**  
The API computes them from SQLite; the demo runs through the real pipeline; the contract test
asserts counts, sources, topology join, and the nearby change. There are no seeded UI values.

**What would you do before production?**  
Authn/authz, TLS, Postgres, a durable worker, distributed rate limiting, retention,
suppression/escalation, and secret management. See `docs/security.md` and ADR-0003.

## Recovery

| Problem | Fix |
|---|---|
| Demo says the scenario already ran / data looks doubled | Click **Reset demo data** or `make demo-reset`; re-run |
| `make demo` cannot connect | Start `make run` first; check `/readyz` |
| Port 8000 busy | `PORT=8010 make run`, then `BASE_URL=http://127.0.0.1:8010 make demo` |
| Dashboard is stale after a backend change | `make build` then restart, or use `make dev` |
| Docker path requested but unavailable | Say so directly; show the CI container job and static validation instead of pretending |

## Discovery narrative

This project started as a “build an AIOps dashboard” exercise. The useful discoveries came
from refusing to fake the hard parts:

1. **Grouping is easy to demo and hard to justify.** The first design returned a score. That
   was replaced with ordered rules and a stored reason object because a score cannot answer
   “why is checkout in this incident?” in a way an operator can audit.
2. **Retries are the real test.** Writing the idempotency tests exposed a status-comparison
   bug: a firing replay after source resolution used identity comparison on an enum value
   instead of equality, so the reopen path was not reached reliably. The fix is small; the
   lesson is that idempotency is behavior, not a unique index alone.
3. **Demo data is a product risk.** The demo originally reused the live tables. A partition
   (`is_demo`) was added to every correlation query and uniqueness constraint so the
   portfolio story cannot corrupt a user's real incidents — and vice versa.
4. **“Nearby change” wants to become “root cause.”** The UI and API deliberately use
   `temporal_context_only` and repeated copy. Restraint is a feature.
5. **The scenario is the regression eval.** Counts and relationships are asserted end to end.
   If a future correlation change breaks the story, CI fails before a reviewer sees it.

The result is smaller than a production platform and more honest than a mock: a complete
local workflow with explicit boundaries, executable evidence, and a clear list of what is
missing.
