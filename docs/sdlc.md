# Bamboo11y — AI-native SDLC evidence

> Provenance: the architecture and delivery tooling were developed in the `signalforge`
> repository; this repository is its continuation, rebranded and extended with a
> vendor-neutral open-integration ingestion adapter (credits and non-affiliation note in
> [`inspirations.md`](inspirations.md)). Evidence below was executed in **this** checkout.

This project is a worked example of Anthropic's **AI-native SDLC playbook**:
[Plan → Design → Build → Test → Deploy → Maintain](https://claude.com/blog/the-ai-native-sdlc-playbook).
The goal is not process theatre. Each stage leaves a durable artifact or an executable
gate that a new contributor can use.

| Stage | Playbook practice | Artifact / evidence in this repo |
|---|---|---|
| Plan | Capture intent in human-readable, machine-actionable form | [`intent.md`](../intent.md) — problem, users, non-goals, success criteria, review points |
| Design | Compress requirements and design into a working spec | [`docs/spec.md`](spec.md), [`docs/adr/`](adr/), [`docs/architecture.md`](architecture.md) |
| Build | Plan before code; maintain durable agent context; use skills for repeatable knowledge | [`docs/implementation-plan.md`](implementation-plan.md), [`CLAUDE.md`](../CLAUDE.md), [`AGENTS.md`](../AGENTS.md), [`.claude/skills/`](../.claude/skills/) |
| Build | Parallel independent work with subagents where useful | Backend and frontend contracts were built in parallel; an independent review pass runs before release |
| Test | Give the agent a fast feedback loop; weave evals through implementation | `pytest`, Vitest, Ruff, ESLint, typecheck, [`scripts/check.sh`](../scripts/check.sh); scenario tests act as behavior evals |
| Test | Run evals continuously in CI | [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs backend and frontend gates on every push/PR |
| Deploy | Agentic review with human judgement for critical changes | `docs/implementation-plan.md` review checklist; conventional PR-sized history; no auto-deploy |
| Deploy | Hooks as approval gates | [`.githooks/pre-commit`](../.githooks/pre-commit), [`.claude/settings.json`](../.claude/settings.json) blocks destructive shell commands |
| Maintain | Close the loop from production signals back into intent | Overview + Prometheus metrics, `/readyz`, [`docs/operations.md`](operations.md), limitations and next actions fed back into this doc |

## How the SDLC was exercised on this task

1. **Plan:** the brief was turned into `intent.md` before implementation, including what the
   system must not claim (AI, causality, vendor affiliation).
2. **Design:** the ingest-to-incident contract, rule order, demo outcome, and explicit
   production gaps were written in `spec.md` and three ADRs.
3. **Build:** implementation followed module boundaries from the spec. The demo sends data
   through the same adapters and ingestion service as external webhooks. Agent context was
   kept in `CLAUDE.md`/`AGENTS.md`; a scenario-authoring skill captures the repeatable way
   to add a new demo.
4. **Test:** deterministic fixture tests plus a scenario contract test cover the behaviors
   the showcase depends on. The full local gate is available through `make check`.
5. **Deploy:** CI mirrors the local gate. A pre-commit hook and a Claude Code pre-tool hook
   guard destructive actions. Release is deliberately manual; the environment is local.
6. **Maintain:** health, readiness, structured logs, derived dashboard metrics, and
   Prometheus metrics are paired with an operations doc and an explicit “what changes for
   production” section. The demo's scenario contract is the regression eval for the story.

## Intent → evidence traceability

| Success criterion | Test / evidence |
|---|---|
| Two source formats normalized to one model | `backend/tests/test_normalization.py` |
| Helpful rejection of malformed/unsupported requests | `backend/tests/test_validation.py` |
| Retries do not duplicate alerts/incidents/notifications | `backend/tests/test_idempotency.py` |
| Related alerts group within configurable windows | `backend/tests/test_correlation.py` |
| Explainable topology join | `backend/tests/test_correlation.py`, incident detail API |
| Late and repeated alerts handled sensibly | `backend/tests/test_correlation.py`, `test_lifecycle.py` |
| Lifecycle transitions are safe and auditable | `backend/tests/test_lifecycle.py` |
| Demo contract (3 incidents, 3-alert primary, nearby change) | `backend/tests/test_demo_e2e.py` |
| Ingest → normalize → correlate → retrieve | `backend/tests/test_end_to_end.py` |
| Dashboard behavior and action controls | `frontend/src/**/*.test.tsx` |
| Local build works | `make check`, `make build` |

## Verification evidence — 2026-10-22

Recorded from the executed gates. Docker was unavailable locally, and the container path is
**exercised by CI**: job `Container build` builds the multi-stage image and smoke-tests
`/readyz` on run 39692358695 (green). Compose orchestration itself has not been executed
anywhere.

| Gate | Result |
|---|---|
| `ruff check backend scripts` + `ruff format --check` | Clean |
| `pytest backend/tests -q` | **57 passed** |
| `npm run lint` (ESLint) + `tsc --noEmit` | Clean |
| Vitest behavior tests | **8 passed** |
| `npm run build` (Vite production) | Success (~325 kB JS / ~36 kB CSS) |
| `scripts/validate_config.py` | Catalog, settings, Compose, CI, secret scan all valid |
| CI run `39692358695` | Backend 3.12 ✓ / 3.13 ✓ / Frontend ✓ / Configuration ✓ / **Container build + `/readyz` smoke ✓** |
| Live smoke on clean DB | `/readyz` ready; demo produced 6 received / 5 unique / 1 duplicate / 3 incidents / 3 notifications; primary incident 3 alerts across 2 sources; payment change 6.0 min before first alert; unrelated incidents 2; reset removed only demo rows, live incident stayed |
| Idempotency probe | Repeat webhook return 200 duplicate → same alert row, no new incident/notification |
| Lifecycle probe | Ack → resolve with notes; distinct audit events, one notification each; duplicate actions no-op |
| Review pass | Fresh read-only review (self-run; the spawned reviewer agent was rate-limited): ingestion/correlation/lifecycle/security/delivery checked; no blocking findings. No TODO/stub markers, no committed secrets, no vendor branding in tracked files. |

Bugs and defects caught and fixed along the way:

1. `ingestion.py` compared alert status with `is` on an enum *value* string, so the
   firing-after-resolve reopen path was never reached. Caught by idempotency tests; fixed and
   now covered.
2. Adding ESLint surfaced three real frontend correctness lints: a ref written during render
   and two synchronous `setState` calls inside effects (`useResource`, `IncidentsPage`).
   Fixed with `useEffectEvent` and derived draft state instead of suppressing the rule.
3. Review pass found the demo and lifecycle routes never observed Prometheus notification/
   incident counters, so `/metrics` undercounted demo and operator actions. Fixed and asserted
   by `test_demo_and_lifecycle_observe_metrics`.
4. Review pass found `default_severity` was dead configuration never read by any service.
   Removed rather than documented.
5. First CI run failed where local typecheck passed: `@types/node` existed only as an
   install-time artifact, not a declared dev dependency. The restricted `types` tsconfig array
   hid it from CI's `npm ci` tree. Declared explicitly and added `node` to `types` — CI caught
   what a locally over-satisfied `node_modules` masked.

## Governance notes

- Human judgement owns the design claims, security posture, and release decision.
- CI and hooks are deterministic gates, not proof of correctness.
- There is no deployment pipeline to a hosted environment; that would require explicit
  human approval and the production work listed in ADR-0003.
- The repository never stores secrets or generated databases. `.env.example` contains safe
  placeholders only.
