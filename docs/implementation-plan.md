# Bamboo11y — Implementation plan

**Method:** Anthropic AI-native SDLC playbook — Plan, Design, Build, Test, Deploy, Maintain.  
**Goal:** a verified, local-first, full-stack demonstration, not a slideware scaffold.

## Stage 1 — Plan

- [x] Capture intent, audience, non-goals, success criteria in [`intent.md`](../intent.md).
- [x] Define the five-minute demo outcome and the “context, not causality” guardrail.
- [x] State safety constraints: local-only, no accounts, no secrets, no vendor claims.

## Stage 2 — Design

- [x] Write functional/non-functional design in [`spec.md`](spec.md).
- [x] Choose FastAPI + Pydantic v2 + SQLAlchemy + SQLite; React/TypeScript + Vite.
- [x] Define adapter registry, normalized alert contract, rule order, lifecycle, outbox.
- [x] Design demo scenario and expected result.
- [x] Write ADRs for stack, correlation/idempotency, persistence/scaling.

## Stage 3 — Build

### Backend

- [x] Settings, clock, SQLite session/engine, model schema, seed/load catalog.
- [x] Alertmanager and CloudWatch adapters with validation and normalization.
- [x] Enrichment from service catalog.
- [x] Fingerprint deduplication and incident correlation engine with reasons.
- [x] Incident lifecycle and event audit trail.
- [x] Notification outbox (local mock Slack + optional external webhook).
- [x] Topology API, change events, nearby-change context.
- [x] Demo scenario through the real ingestion pipeline.
- [x] Overview, alert stream, integrations, health/readiness, metrics.
- [x] Structured logging, request IDs, rate limiting, security headers, error shapes.

### Frontend

- [x] App shell, design system, responsive navigation, accessible primitives.
- [x] Overview with derived metrics, alert volume, source health, recent changes.
- [x] Incidents list with filters and empty/loading/error states.
- [x] Incident detail with timeline, explanations, topology, changes, actions.
- [x] Signals page, services explorer, integrations/outbox page.
- [x] Demo runner and toast feedback.

### Delivery

- [x] Local simulator CLI and deterministic fixture.
- [x] Dockerfile, Docker Compose, optional Prometheus/Alertmanager profile.
- [x] `.env.example`, Makefile, quickstart script.
- [x] README, diagrams, security/ops documentation, demo script.

## Stage 4 — Test

- [x] Feedback loop: fast unit tests, API integration tests, frontend component tests.
- [x] Normalization tests for both sources.
- [x] Invalid/unsupported/oversized/rate-limited payload tests.
- [x] Idempotency and duplicate-notification tests.
- [x] Correlation window, topology, late-arrival, and isolation tests.
- [x] Lifecycle transition and audit tests.
- [x] Ingest → normalize → correlate → incident retrieval E2E test.
- [x] Demo scenario contract test (counts, sources, topology join, nearby change).
- [x] Lint, type check, tests, frontend production build.
- [x] Independent review pass against intent/spec (agentic review as a quality gate).

## Stage 5 — Deploy

- [x] CI workflow: backend tests/lint, frontend lint/test/build, config validation.
- [x] Pre-commit gate and Claude Code approval hook for destructive commands.
- [x] Docker build path (multi-stage) and private local startup instructions.
- [x] Verify documented local startup from clean state.
- [x] Create private GitHub repository and push reviewed history.

## Stage 6 — Maintain

- [x] Health/readiness and Prometheus metrics.
- [x] Alerting examples and scrape config.
- [x] Operations/runbook and incident-feedback loop documentation.
- [x] Record known limitations and next production steps.
- [x] Use the live demo and metrics to validate the stated success criteria.

## Verification commands

```bash
make setup          # Python venv + Node dependencies
make test           # backend + frontend tests
make lint           # Ruff + ESLint + TypeScript typecheck
make build          # frontend production build
make demo           # run scenario against a running server
```

## Risks / mitigations

| Risk | Mitigation |
|---|---|
| Over-grouping alerts into giant incidents | One-hop topology limit, separate topology window, explicit reasons, tests for boundaries |
| Demo polluting user data | `is_demo` partition, correlation partition filter, demo-only reset |
| Duplicate notifications on retries | Event-scoped unique outbox keys + idempotent lifecycle actions |
| “Deployment caused it” overclaim | `temporal_context_only` contract and repeated UI disclaimer |
| Docker unavailable in authoring environment | Build assets validated statically; local path fully exercised; limitation documented |
| SQLite concurrency limitations | Documented in ADR-0003, production migration path specified |
| High-cardinality or abusive webhook traffic | Payload size cap, label/alert count caps, per-source rate limit, sanitization |
