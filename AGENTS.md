# CLAUDE.md — nami AI Agent Dev Notes

Quick-start router for AI coding agents working on nami. **Read this first**,
then the owning doc for the area you're touching. Full architecture and
roadmap live in [README.md](README.md).

---

## Mission

nami (波) is a natural-language hypothetical stress explorer for equity portfolios.
Gemini grounds a scenario against current news + historical analogs. The default
legacy engine derives validated shocks; the optional Quant V2 challenger maps
semantic directions to a supported joint historical factor vector.

**Educational/research tool only** — not investment advice, not a forecast. The
disclaimer is enforced in `app/utils/disclaimers.py` and rendered on every page.

---

## Stack at a glance

- **Python 3.12** + **uv**; **FastAPI** backend at `app/api/main.py`
- **React + TypeScript + Vite + Plotly.js** frontend under `frontend/`
- **GCP** — Vertex AI (`gemini-3.5-flash`, region `global`), public research/FRED
  data, Cloud Storage
  (cache), Firestore (persistence), Cloud Run + Cloud Build (deploy, region
  `asia-northeast1` — the region split matters; see deploy-ops).

---

## Where the knowledge lives — read the owning doc BEFORE touching an area

| Touching… | Read first |
| --- | --- |
| `app/factors/*` — engine math, attribution, analogs, replay harness | [docs/agents/engine.md](docs/agents/engine.md) |
| `app/llm/*` — prompts, PROMPT_VERSION, validation, scenario orchestration, adjustments | [docs/agents/llm-pipeline.md](docs/agents/llm-pipeline.md) |
| `app/data/*`, `app/utils/calendar.py` — yfinance, caches, FX, marking, sample books | [docs/agents/data-market.md](docs/agents/data-market.md) |
| `app/api/*`, `app/observability/*` — endpoints, SSE, auth, limits, errors, Firestore | [docs/agents/api-backend.md](docs/agents/api-backend.md) |
| `frontend/src/*` — App shell, state hooks, areas/tabs, results surfaces, overlays | [docs/agents/frontend.md](docs/agents/frontend.md) |
| `frontend/src/styles.css`, `theme.ts`, `copy/` — tokens, dual theme, responsive, motion | [docs/agents/design-system.md](docs/agents/design-system.md) |
| `cloudbuild.yaml`, Dockerfile, GCP config, local env quirks | [docs/agents/deploy-ops.md](docs/agents/deploy-ops.md) |
| Phase history (what shipped when, and why) | [docs/agents/phase-log.md](docs/agents/phase-log.md) |

Every invariant lives in exactly ONE owning doc. When your change alters a
contract, update the owning doc **in the same commit**.

---

## Commands you'll actually use

```powershell
# from <repo root>

uv sync                            # install/update deps from pyproject.toml
uv run uvicorn app.api.main:api --reload --host 0.0.0.0 --port 8080
cd frontend; npm install; npm run dev
uv run pytest tests/ -v            # run unit tests
uv run ruff check .                # lint
uv run black --check .             # format check
cd frontend; npm run typecheck; npm test; npm run build
uv run python scripts/run_engine_replay.py   # regenerate engine-replay artifacts (network)
uv run python scripts/run_quant_challenger.py --input cases.json --fail-on-gate
```

To exercise the GCS cache or Vertex AI, the local `.env` must have all 4
REQUIRED keys populated. Template: `.env.example`.

---

## Coding conventions (specific to this repo)

- **Type hints required** on every public function (params + return).
- **`from __future__ import annotations`** at the top of every new module.
- **`@dataclass(frozen=True)`** for value objects (`Config`, `Portfolio`, `Factor`).
- **Validate at boundaries.** Raise `ValueError` / `RuntimeError` with specific
  messages when inputs violate invariants (see `Portfolio.__post_init__`).
- **No `print()` in library code**; no commented-out code, no `# TODO:`.
- **Comments only when the WHY is non-obvious.**
- **Frontend colors live in tokens** — never hard-code hex/rgba in rules (a
  literal renders in ONE theme only; see design-system).

---

## Quality gates before "done"

1. `uv run pytest tests/ -v` — all green
2. `uv run ruff check .` — clean
3. `uv run black --check .` — clean
4. `cd frontend; npm run typecheck; npm test; npm run build` — frontend green
5. For UI changes: run FastAPI + Vite locally and verify in the browser. Both
   themes. Type-checking passing ≠ feature working.

---

## Cardinal rules (What NOT to do)

- **Never commit `.env` or any `*.json` that looks like a service-account key.** `.gitignore` covers common patterns; the real mitigation is keeping keys outside the repo (e.g., `~/.gcp/nami-sa.json` or `C:/Users/<you>/.gcp/nami-sa.json`).
- **Never paste terminal output, shell prompts, or absolute filesystem paths into committed files** (README, CLAUDE.md, code comments, anywhere). Such pastes leak the user's Windows username, repo location, and project tree layout — and look unprofessional in a public repo. If you need to show example output, strip prompts (`PS C:\...>`, `$`) and replace paths with `<repo root>` / `~/path/`.
- **Never put proprietary or third-party product/vendor names in commit messages, branch names, PR text, or committed files** (code, comments, docs, prompts). Describe the capability generically instead — never the vendor. The same rule applies to LLM prompt strings in `app/llm/prompts.py`. Reason: public repo, educational tool; trading on a vendor's marks invites trademark/association problems.
- **A force-push does NOT erase a leaked name.** The orphaned commit stays reachable by SHA on GitHub, the force-push is logged, and Cloud Build recorded the original SHA. Mitigation is *prevention* — scan before pushing.
- **Before any `git push`, run the pre-commit content scan** — grep the *staged diff* for accidental pastes, project-ID leaks, and embedded credentials, plus a private (un-committed) vendor wordlist.
- **Never auto-commit on the user's behalf** unless explicitly asked. Stage explicit files, never `git add .` until ignores are verified.
- **Don't phase-jump.** Phases are ordered; each must be functional + tested before the next.
- **Don't preemptively migrate yfinance → Polygon.** There is a deliberate one-file-change path in `app/data/market.py` when reliability demands it; don't add abstractions for it until needed.
- **Don't add Shapley logic to `app/factors/shocks.py`.** Factor-level Shapley lives in `app/factors/attribution.py`; narrative-level in `app/llm/narrative_shapley.py`; `shocks.py` only orchestrates.
- **`PROMPT_VERSION` bumps ONLY for prompt-semantics or `ScenarioResult`-shape changes; engine math rides `regression_spec`.** Full rules in llm-pipeline.md — read it before touching either lever.
- **Keep `CLAUDE.md` and `AGENTS.md` byte-identical.** They are the same router for different tool ecosystems: edit one, `cp` it over the other in the same commit. `tests/test_agent_docs.py` fails CI on drift. Area knowledge goes in `docs/agents/*.md` (single-owner, no mirror), NOT here.
- **Don't widen the disclaimer surface or soften its language** — it's load-bearing for the regulatory framing ("scenario explorer" not "stress testing").

---

## Phase status

Phases 0–36 shipped (most recently Phase 36: optional Quant V2 methodology,
public-data provenance, simple controls, and offline promotion gates). The full append-only log — one dated entry per phase with scope
and rationale — lives in [docs/agents/phase-log.md](docs/agents/phase-log.md).
