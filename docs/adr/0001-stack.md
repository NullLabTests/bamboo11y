# ADR-0001: Stack and runtime shape

- **Status:** accepted
- **Date:** 2026-10-21
- **Deciders:** Bamboo11y maintainers
- **Related:** [spec](../spec.md), [architecture](../architecture.md)

## Context

Bamboo11y is a portfolio-scale, local-first incident command center. It must be runnable
by a reviewer with a fresh checkout, without paid services, credentials, or external
accounts. It must demonstrate a credible production shape: typed contracts, validation,
persistence, observability, tests, and a real frontend build. The team optimizes for clarity
and verifiability over horizontal scale.

## Decision

Use a modular monolith:

- **Backend:** Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2, SQLite, uvicorn.
- **Frontend:** React 19, TypeScript, Vite, React Router, custom CSS.
- **Tests:** Pytest with a fixed clock and temp SQLite; Vitest + Testing Library.
- **Delivery:** multi-stage Dockerfile, Compose, optional Prometheus/Alertmanager profile.
- **Configuration:** environment variables with a `BAMBOO11Y_` prefix and a documented
  `.env.example`.

The API serves the built SPA from `frontend/dist`, so the local production path is one
process and one port. Vite is a development convenience only.

## Rationale

| Choice | Why |
|---|---|
| FastAPI + Pydantic | Explicit request/response contracts, generated OpenAPI, strong validation, small team ergonomics |
| SQLAlchemy + SQLite | Real relational modeling and constraints with zero external infrastructure; easy inspection |
| React + TypeScript | Typed UI contracts, component tests, a large accessible ecosystem |
| Custom CSS | No design-system dependency; full control over responsive and reduced-motion behavior |
| Modular monolith | The interesting problem is correlation, not distributed systems; one process is easier to run and review |
| YAML catalog | Topology changes are reviewable and versioned; no runtime write API to secure |

Alternatives considered:

- **Django/DRF** — mature, but heavier for a small API and less direct Pydantic/OpenAPI
  ergonomics.
- **Node/Express or NestJS backend** — one language across the stack, but weaker fit for
  the data/validation style and the author's verification loop.
- **Postgres + Redis + worker** — closer to production, but violates the no-external-service
  constraint and adds setup failure modes that obscure the demo.
- **Next.js full-stack** — excellent DX, but couples the API and UI and complicates the
  single-process Python demo.
- **A component library** — faster, but generic visual output and a larger dependency
  surface.

## Consequences

### Positive

- One command starts the product; SQLite makes state inspectable.
- Pydantic and TypeScript catch contract drift at the boundary.
- Tests are fast and deterministic; no network mocking for core logic.
- The container is small and runs without a database service.

### Negative

- SQLite is a single-writer store; it is not an HA production database.
- The monolith deploys as one unit; service boundaries are logical, not physical.
- The custom CSS is more code to maintain than a component library.
- Python and Node toolchains are both required for a full build.

### Follow-ups

- ADR-0003 defines the Postgres/worker migration path.
- A production deployment must add auth, TLS, and a shared rate limiter; none are claimed
  here.

## Compliance notes

- No paid service, credential, or external account is required.
- The project name and UI contain no vendor branding or affiliation claims.
- The demo uses the same adapters and ingestion service as external webhooks.
