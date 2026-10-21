# CLAUDE.md

Bamboo11y is a local-first AIOps incident-management portfolio project. Read `intent.md`,
`docs/spec.md`, and `docs/implementation-plan.md` before substantial changes.

## Stack

- Backend: Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2, SQLite. Lives in `backend/app/`.
- Frontend: React + TypeScript + Vite. Lives in `frontend/src/`.
- Data: service catalog in `config/services.yaml`; SQLite at `data/bamboo11y.db` (ignored).
- Ops: Dockerfile + `docker-compose.yml`; optional Prometheus/Alertmanager under `ops/`.

## Commands

```bash
make setup       # create .venv and install backend/frontend deps
make dev         # API on 127.0.0.1:8000; Vite on 127.0.0.1:5173
make test        # backend + frontend
make lint        # Ruff, ESLint, TypeScript
make check       # full local gate
make demo-data   # run demo against a running API
make reset-db    # delete local SQLite database (not demo reset)
```

Backend-only: `.venv/bin/pytest backend/tests -q` from the repo root. Set
`BAMBOO11Y_ENV_FILE=/dev/null` in tests/scripts when inheriting a local `.env`.

## Invariants — do not break without updating tests and docs

1. Alert identity is the dedupe fingerprint. Retries update the existing alert; they never
   create a second alert, incident, or notification.
2. Correlation is deterministic and rule-based. Do not describe it as AI/ML. Every linked
   alert must expose a human-readable reason.
3. Correlation only compares records in the same `is_demo` partition.
4. Changes are temporal context only. Never present a change as root cause. API responses
   use `relationship: "temporal_context_only"`.
5. Lifecycle transitions: open → acknowledged → resolved; open → resolved allowed; repeated
   actions are idempotent; resolved → acknowledged is rejected. Source re-fire may reopen.
6. Notification outbox keys are unique per incident event. Repeat ingestion/actions must not
   fan out duplicate messages.
7. The local demo must require no credentials and no network access beyond localhost.
8. Do not log payload bodies, authorization headers, or secrets. Do not add credentials.
9. All UI numbers must be derived from API data. No invented metrics.
10. Bind to loopback by default. Authentication/tenancy are documented gaps, not silently
    “solved” by hiding the app.

## Style

- Type hints everywhere on the backend; Pydantic validation at boundaries; explicit error
  shapes (`detail`, `code`, optional hints).
- Keep adapters isolated by source. Add a new source in a new module plus registry test.
- Frontend: functional components, typed API client, semantic HTML, text labels alongside
  color, responsive layouts, reduced-motion support.
- Tests should use the controllable clock and temporary SQLite database; no sleeps.
- Prefer small modules over monoliths, but do not create abstraction layers without a
  second use case.

## Definition of done

- New behavior has backend and/or frontend tests.
- `make check` passes.
- Demo scenario contract still holds (see `backend/tests/test_demo_e2e.py`).
- Docs updated for any changed contract, limit, or production caveat.
- A human has reviewed any new security or causal claim.
