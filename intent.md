# Bamboo11y — Intent

> Development follows Anthropic's six-stage AI-native SDLC playbook:
> Plan → Design → Build → Test → Deploy → Maintain.
> See [`docs/sdlc.md`](docs/sdlc.md) for how each play is represented in this repository.

## The problem

When a production system degrades, responders receive a burst of alerts from several
monitoring tools. The alerts use different schemas, repeat on retry, and arrive without
the service ownership and dependency context needed to decide what to do. Correlated
signals are scattered across tools, while a recent deployment may sit in yet another
system. The result is slower acknowledgement, duplicate notifications, and a manual
reconstruction of the incident.

## Who this is for

- **Solutions architects and platform engineers** evaluating an alert-correlation and
  incident-management design.
- **Hiring managers** who want to inspect a working full-stack system, not a slide deck.
- **Developers** who want a small, local reference implementation of event normalization,
  deterministic correlation, and operational APIs.

## Desired outcome

A new user can start Bamboo11y locally in minutes, inject a realistic simulated alert
storm from two different monitoring formats, and watch the system:

1. validate and normalize the payloads into one alert model,
2. enrich alerts with catalog ownership and topology,
3. deduplicate retries and late repeats,
4. group explainable related signals into one incident,
5. show nearby change events with explicit “context, not causality” language,
6. deliver one idempotent notification per lifecycle event to a local mock channel, and
7. support acknowledgement and resolution with an auditable timeline.

## Goals

- **Demonstrable value in under five minutes.** A prominent deterministic demo scenario.
- **Transparent automation.** Rule-based correlation with human-readable reasons; no
  machine-learning claims.
- **Local-first.** No paid service, external account, credential, or network dependency
  is required to run the demo.
- **Portfolio quality.** Professional UI, strong README, tests, CI, ADRs, diagrams,
  health/readiness, and a thoughtful production-gap analysis.
- **Safe defaults.** Loopback binding, no auth bypass claims, sanitized logging, bounded
  payloads, rate limiting, and a local mock notification sink.
- **Maintainable boundaries.** Adapters, domain services, persistence, API routes, and UI
  separated so an additional monitoring source or storage backend has a clear home.

## Non-goals

- It is **not** a production SaaS or a replacement for PagerDuty, Opsgenie, Grafana
  OnCall, or a commercial AIOps platform.
- It does **not** use machine learning, generative AI, or an LLM to infer root cause.
- It does **not** prove causation between a deployment and an incident. Changes are shown
  as temporal context only.
- It does **not** implement authentication, tenant isolation, durable queues, high
  availability, or long-term retention. These are documented production gaps.
- It does **not** reproduce or claim affiliation with any commercial vendor or private
  system. Bamboo11y is an independent educational demonstration of common AIOps
  patterns.

## Success criteria

- `make setup && make dev` starts without cloud credentials.
- The demo action produces **one primary incident with three related alerts from two
  sources**, plus two unrelated incidents, a nearby deployment, and a mock Slack delivery.
- Every correlated alert carries a deterministic, inspectable reason.
- Replaying any webhook does not create a duplicate alert, incident, or notification.
- An alert arriving outside the configured window is not silently merged.
- Incident actions are auditable and repeat actions do not duplicate notifications.
- Backend tests cover normalization, validation, idempotency, correlation windows,
  topology joins, lifecycle transitions, and the end-to-end demo flow.
- Frontend tests cover empty dashboard, incident detail/action, and the demo action.
- Lint, type checks, backend tests, frontend tests, and the production build pass.
- A private GitHub repository is created and contains no credentials or generated data.

## Constraints and assumptions

- Backend: Python 3.12+ (validated on Python 3.14), FastAPI, Pydantic v2, SQLAlchemy,
  SQLite.
- Frontend: React, TypeScript, Vite; custom responsive CSS; no hosted UI services.
- Docker Compose is provided for a one-command local start. The authoring environment
  did not have a Docker daemon, so container startup is documented as unverified there;
  the underlying local build and test path is verified.
- Time is represented in UTC. Correlation windows use alert event timestamps where
  available, with receipt time as the fallback.
- The demo uses the same adapter and ingestion pipeline as the public webhooks.

## Key decisions

- Rules, not models: deterministic grouping is easier to explain, test, and operate.
- SQLite and synchronous request handling keep the demo portable; the persistence ADR
  records exactly what changes for production scale.
- Alert fingerprints, not delivery IDs, are the idempotency primitive because source
  systems send the same condition repeatedly with new delivery metadata.
- Notification outbox rows have unique event-scoped keys, so rejected retries and repeat
  operator actions cannot fan out duplicate messages.
- Demo data is tagged and isolated from live data, allowing a fresh, repeatable scenario
  without wiping user-created records.

## Human review points

- Confirm the demo narrative and default correlation window feel realistic.
- Confirm the UI’s change-event language never implies causality.
- Review production-gap documentation before describing the system to a customer.

## Provenance (2026-10-22)

This repository codifies the architecture developed in `signalforge` (private), rebranded
to **Bamboo11y** — bamboo + the observability numeronym "o11y" — and extended with a
vendor-neutral open-integration-style ingestion contract, implemented in this
repository, with ideas credited to BigPanda's public documentation and MIT/Apache-licensed
client repositories. The credits live in `docs/inspirations.md` with an explicit
non-affiliation note. The original `signalforge` repository remains untouched.
