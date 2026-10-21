---
name: bamboo11y-verify
description: Verify a Bamboo11y change end to end. Use before claiming work is complete, before a commit or push, or when asked to run the local quality gate.
---

# Verify Bamboo11y

Run checks in this order and report exactly what passed. Do not claim a check passed
without running it.

## 1. Static and test gates

```bash
make check
```

This runs Ruff lint/format, Pytest, ESLint, TypeScript, Vitest, the production build, and
`scripts/validate_config.py`. If a check fails, fix the cause; do not weaken a test or a
validation rule to make it pass.

## 2. Live local smoke test

```bash
rm -f data/smoke.db
BAMBOO11Y_DATABASE_URL=sqlite:///./data/smoke.db \
  PYTHONPATH=backend .venv/bin/uvicorn app.main:create_app --factory \
  --host 127.0.0.1 --port 8000
```

In a second shell:

```bash
curl -fsS http://127.0.0.1:8000/readyz
make demo
curl -fsS http://127.0.0.1:8000/api/overview | head -c 400
curl -fsS http://127.0.0.1:8000/metrics | grep bamboo11y_incidents_active
```

The demo must report 6 received, 5 unique, 1 duplicate, 3 incidents, a 3-alert primary
incident spanning two sources, and a change 6.0 minutes before the first alert.

If `frontend/dist` exists, also open `http://127.0.0.1:8000/` and confirm the SPA loads and
the primary incident detail page renders. Stop the server and remove the smoke database
afterward.

## 3. Docker

Docker is not available in every development environment. Building the image is not the
same as verifying Compose. If Docker is unavailable, say so explicitly and list
`make docker-up` as unverified. CI builds and smoke-tests the image.

## 4. Final report

Include:

- what changed and why;
- commands run and their outcomes;
- demo numbers observed;
- anything still unresolved, unverified, or environment-dependent.
