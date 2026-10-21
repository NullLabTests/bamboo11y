# AGENTS.md — Bamboo11y

The canonical AI-native SDLC guidance for this repository is in [`CLAUDE.md`](CLAUDE.md).
Read it first. This file adds OpenCode-specific working agreements.

## Working agreement

- Plan briefly before coding. For substantial work, update `intent.md` / `docs/spec.md`.
- Preserve the demo story: two sources → three related alerts in one incident → topology
  context → nearby deployment → acknowledge/resolve. If a change weakens that path, update
  the scenario contract test deliberately.
- Never silently weaken validation, idempotency, rate limiting, or the “context, not cause”
  language to make a test or UI easier.
- Before finishing: run `make check`, exercise the live demo once, and summarize any
  unverified environment limitations (for example, no Docker daemon).
- Do not create generative-AI claims. If a model is not implemented, call the approach
  rule-based.
- Keep the project independent: never claim affiliation, endorsement, or compatibility
  warranties with BigPanda. Third-party *ideas* may be used and credited in
  `docs/inspirations.md` (with an explicit non-affiliation note); third-party code,
  schemas, trademarks, or brand assets must not be copied.
- Keep commits focused. Do not commit `.env`, `data/`, build output, or generated caches.

## Useful source map

| Concern | Location |
|---|---|
| Alert formats/normalization | `backend/app/adapters/` |
| Ingestion/idempotency/correlation | `backend/app/services/ingestion.py`, `correlation.py` |
| Lifecycle + audit trail | `backend/app/services/incidents.py`, `backend/app/models.py` |
| Demo scenario | `backend/app/services/demo.py` |
| Service catalog | `config/services.yaml`, `backend/app/services/catalog.py` |
| API routes | `backend/app/api/routes/` |
| Dashboard | `frontend/src/pages/`, `frontend/src/components/` |
| CI and gates | `.github/workflows/ci.yml`, `scripts/check.sh`, `.githooks/` |
| SDLC evidence | `docs/sdlc.md` |
