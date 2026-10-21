---
name: demo-scenario
description: Change or debug the Bamboo11y demo scenario. Use when editing backend/app/services/demo.py, the scenario contract test, or demo copy in the dashboard and README.
---

# Demo scenario authoring

The demo is the portfolio's proof, not a mock screen. It must go through the real
adapters, ingestion, correlation, lifecycle, and notification code.

## Contract

`backend/tests/test_demo_e2e.py` is the executable contract. The current scenario is
`payments_degradation`:

- 6 webhook deliveries, 5 unique alerts, 1 duplicate;
- 3 incidents;
- primary incident: 3 alerts, 2 sources, `payments-api` + `checkout-api`;
- unrelated incidents: `search-api` in staging and `notifications-worker`;
- a `payments-api v2.14.0` deployment 6.0 minutes before the first alert;
- 3 mock-slack notifications;
- `relationship: temporal_context_only`, never "caused by".

## Rules

1. Use the `Clock` abstraction and relative timestamps; never call `datetime.now()` in the
   scenario.
2. Route data through `get_adapter(...).normalize` and `AlertIngestionService.ingest`.
3. Mark every demo row `is_demo=True`; never let demo data join real incidents.
4. Keep at least one unrelated incident so the demo proves correlation, not grouping
   everything.
5. Keep one replayed delivery so idempotency is visible.
6. If the contract changes, update the test, `docs/spec.md`, the README demo walkthrough,
   `frontend/test/fixtures.ts`, and any hard-coded copy in one deliberate change.
7. Never add a generative-AI claim. Correlation is deterministic and rule-based.

## Verify

```bash
PYTHONPATH=backend .venv/bin/pytest backend/tests/test_demo_e2e.py -q
make check
make demo   # against a running API
```

Inspect the primary incident in the dashboard: the grouping reasons, topology, nearby
change, and "context, not cause" disclaimer must all be visible.
