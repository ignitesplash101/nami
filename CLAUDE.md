# CLAUDE.md — nami AI Agent Dev Notes

Quick reference for AI coding agents (Claude Code sessions, etc.) working on nami. **Read this first** before making changes.

Full architecture and roadmap live in [README.md](README.md). This file is the agent quick-start.

---

## Mission

nami (波) is an LLM-driven scenario explorer for equity portfolios. User describes a market scenario in natural language → Gemini grounds it against current news + historical analogs → derives factor shocks → the engine computes portfolio P&L with cited reasoning.

**Educational/research tool only** — not investment advice. The disclaimer is enforced in `app/utils/disclaimers.py` and rendered on every page.

---

## Stack at a glance

- **Python 3.12** (pinned in `.python-version` and `pyproject.toml`)
- **uv** for env/dep management
- **FastAPI** backend at `app/api/main.py`
- **React + TypeScript + Vite + Plotly.js** frontend under `frontend/`
- **GCP** — Vertex AI (`gemini-3.5-flash`), Cloud Storage (cache), Cloud Run (deploy)
- **Region split** (this matters):
  - Cloud Run / GCS bucket / Artifact Registry → `asia-northeast1`
  - Vertex AI → `global` (gemini-3.5-flash is NOT on `asia-northeast1` or `us-central1`)

---

## Where things live

```
app/
├── config.py                # env-var loader; validates 3 REQUIRED keys
├── api/                     # FastAPI endpoints, auth/session cookies, API schemas
├── data/
│   ├── market.py            # yfinance wrapper: fetch_weekly_prices, compute_weekly_returns
│   ├── cache.py             # CloudStorageCache: parquet I/O with TTL via blob.updated
│   └── sample_portfolios.py # 4 curated portfolios (Portfolio dataclass)
├── factors/                 # Phase 2 — factor model (universe, regression, shocks)
│                            # Phase 3 — historical analog matcher (analogs.py)
├── llm/                     # Phase 4 — Vertex AI / Gemini integration
│                            #   schemas.py · prompts.py · grounding.py · validation.py
│                            #   gemini_client.py · scenario.py (orchestrator)
└── utils/
    └── disclaimers.py       # disclaimer strings + footer

frontend/                    # React/Vite workbench; Plotly.js client-side charts
tests/                       # pytest unit tests, in sync with the implementation phase
```

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
uv run black .                     # format fix
cd frontend; npm test; npm run build
```

To exercise the GCS cache or Vertex AI, the local `.env` must have all 4 REQUIRED keys populated. Template: `.env.example`.

---

## Coding conventions (specific to this repo)

- **Type hints required** on every public function (params + return).
- **`from __future__ import annotations`** at the top of every new module — keeps type hints as strings so `dict[str, float]` / `X | None` work without runtime cost.
- **`@dataclass(frozen=True)`** for value objects (`Config`, `Portfolio`, `Factor`).
- **Validate at boundaries.** Raise `ValueError` / `RuntimeError` with specific messages when inputs violate invariants. See `Portfolio.__post_init__` (weight sum) for the pattern.
- **No `print()` in library code** — `print` is for `__main__` smoke checks or CLI scripts only. FastAPI code should use structured responses/exceptions; frontend code should surface user-facing errors in state.
- **No commented-out code, no `# TODO:`** — if you're not implementing it now, raise `NotImplementedError` and open a separate scope.
- **Comments only when the WHY is non-obvious.** Names + types do the explaining. Comments document irreducible context (a workaround, a constraint).

---

## Quality gates before "done"

1. `uv run pytest tests/ -v` — all green
2. `uv run ruff check .` — clean
3. `uv run black --check .` — clean
4. `cd frontend; npm test; npm run build` — frontend green
5. For UI changes: run FastAPI + Vite locally and verify in the browser. Type-checking passing ≠ feature working.

---

## Known gotchas

- **yfinance silently drops tickers it can't fetch.** Any function that maps tickers → returns must validate set membership and raise loudly. Documented at `app/data/market.py` (the dropna step).
- **PowerShell `python -c "..."` collides with embedded `f"..."`.** The outer `"` eats the inner `"`. Workarounds: single-quoted f-strings (`f'...'`), here-strings, or a real `.py` file.
- **Parquet round-trip normalizes datetime precision** (`datetime64[s]` → `datetime64[ms]`). Values are identical; only the index dtype changes. Use `assert_frame_equal(..., check_index_type=False)` in tests.
- **`fetch_weekly_prices(..., lookback_weeks=N)` anchors on `end` if provided, else `utcnow()`.** Both `fetch_weekly_prices` and `fetch_daily_prices` share an internal `_fetch_prices` helper — if you touch one, verify the other.
- **yfinance's `end` is EXCLUSIVE.** `start=2020-02-19, end=2020-03-23` returns bars through 2020-03-20, NOT 2020-03-23. `fetch_event_returns` in `app/factors/analogs.py` adds 1 day before calling yfinance to get inclusive-end semantics; callers wanting "include the end date's close" must do the same +1-day transform.
- **yfinance `interval="1wk"` returns Monday-anchored bars, not week-ending Fridays.** `fetch_weekly_prices(start="2020-02-19", end="2020-03-23")` returns a first row dated **2020-02-17** (Monday). This breaks "first Friday ≥ start" intuition — Phase 3 uses `fetch_daily_prices` instead to get exact-day alignment for event windows.
- **Scenario cache key MUST include all semantic inputs.** The Phase 4 `scenario_cache_key()` hashes scenario_text + portfolio_key + holdings dict + market_date + model_id + prompt_version + factor_universe_version + events_version. Dropping any of these would silently return wrong P&L (e.g. same tickers + different weights produces different P&L but would have hit the same cache entry).
- **`portfolio_pnl()` returns JSON-safe dicts** (not pd.Series) since Phase 4 — Series would break the cache serialization round-trip. Shape: `{total_pnl, by_factor, by_ticker_factor, by_ticker_periphery, by_ticker_total}`, all values plain floats or dicts of floats.
- **Gemini grounding + `response_schema` in one call is unreliable.** `gemini-3.5-flash` can return valid JSON while skipping `google_search`, leaving `grounding_metadata` empty. `propose_shocks_with_retry` deliberately splits Call 2 into `_grounded_narrative` (text + Google Search, no schema) and `_extract_structured_shocks` (schema, no tools). Do NOT merge them back together or add a "retry without grounding" fallback.
- **`run_scenario` accepts injected `gemini` and `cache`** — tests use mocks (`tests/conftest.py::InMemoryCache` and `_MockGeminiClient`) instead of `storage.Client()` and `genai.Client()`. Production code calls with defaults (which read `Config` and construct real clients).
- **PROMPT_VERSION** in `app/llm/prompts.py` MUST be bumped for ANY change that affects `ScenarioResult`'s shape OR prompt semantics. Schema changes invalidate the cache exactly the same way prompt changes do. v3 means `ScenarioResult` carries `portfolio_name` + `portfolio_holdings`.
- **`ScenarioResult` is self-contained as of v3.** Always render holdings from `result.portfolio_holdings`, never from `get_portfolio(result.portfolio_key)` — the latter raises on `"custom"`. The new fields have defaults so cached v2 entries don't crash, but they'll show weight=0 for tickers; the PROMPT_VERSION bump invalidates them lazily.
- **Results-tab labels must keep `shock applied` vs `contrib to P&L` distinct.** "Shock applied" is the magnitude the LLM proposed for a factor; "contrib to P&L" is `(Σᵢ wᵢ · βᵢ,f) · shock[f]` — the weighted contribution to the total. Never collapse these into a single number.
- **`run_scenario` accepts EITHER `portfolio` (positional, `str | Portfolio`) OR `portfolio_key=` (kwarg, back-compat).** Passing both or neither raises `ValueError`. The UI passes a `Portfolio` object so custom holdings round-trip; existing tests still pass `portfolio_key="us_tech_growth"`.
- **CSV/custom portfolio rules** live in `app/api/portfolio_validation.py`: uppercase tickers (`.T` suffixes preserved); reject blanks / duplicates / negatives / non-finite; totals near 1.0 accepted as decimals OR near 100 as percentages (auto-normalized to decimals). Anything else is rejected.
- **`tests/test_live_evals.py` is network-gated on `RUN_NETWORK_TESTS=1`** and **stochastic over news drift** even with `temperature=0` — use semantic assertions only (tag membership, ordering, presence-of-citation), never magnitude bounds. `docs/backtest_results.md` is a DATED snapshot, not a permanent benchmark. Costs ~$0.001 per test.
- **Cloud Run GCP client auth uses ADC**, not JSON keys. `nami-sa` is attached via `--service-account=` in `cloudbuild.yaml`; the Vertex AI + GCS Python clients pick it up automatically. Do NOT set `GOOGLE_APPLICATION_CREDENTIALS` on Cloud Run — `app/config.py` tolerates its absence.
- **Cloud Run is publicly invokable, but the app has passcode admin mode.** `cloudbuild.yaml` uses `--allow-unauthenticated` so the React app is viewable without Google login. The `PASSCODE` value is injected from Secret Manager (`nami-passcode:latest`). Visitor mode is sample portfolios + sample scenarios only; admin mode unlocks free-text scenarios, custom/uploaded portfolios, and narrative decomposition.
- **FastAPI binds to `$PORT`** on Cloud Run via the Dockerfile CMD (`uvicorn app.api.main:api --host 0.0.0.0 --port ${PORT:-8080}`). Don't drop `--host 0.0.0.0` — Cloud Run's TCP health checks fail on default localhost binding.
- **Admin access is an HTTP-only signed cookie**, not frontend-only state. `app/api/security.py` signs the admin cookie with the configured passcode; changing the passcode invalidates existing admin cookies.
- **`--session-affinity` is still enabled** in `cloudbuild.yaml`. It is less load-bearing after moving off Streamlit session state, but harmless and useful for long-running requests.
- **Cloud Build 2nd-gen trigger** `nami-main-push` lives in `asia-northeast1`, uses the repository resource `projects/<PROJECT_ID>/locations/asia-northeast1/connections/nami-github-connection/repositories/ignitesplash101-nami`. Edit via Cloud Console → Triggers, or `gcloud builds triggers update`.
- **Cloud Build SA for this project is the compute-engine default** (`<PROJECT_NUMBER>-compute@developer.gserviceaccount.com`), NOT the legacy `<PROJECT_NUMBER>@cloudbuild.gserviceaccount.com`. `gcloud builds get-default-service-account` returns empty in some gcloud versions; derive reliably with `gcloud projects describe $PROJECT_ID --format="value(projectNumber)"` then construct `<NUMBER>-compute@developer.gserviceaccount.com`.
- **Dockerfile is multi-stage.** Node builds `frontend/dist`; Python runs FastAPI. The Python stage still uses `uv sync --frozen --no-dev --no-install-project` + `PYTHONPATH=/app`. Don't drop `--no-install-project` — without it, `uv sync` reads `pyproject.toml`'s `readme = README.md` field and fails because README isn't copied yet in the deps layer.
- **Gemini 3.5 Flash region:** `global` / `us` / `eu` only. NOT `us-central1`, NOT `asia-northeast1`. `VERTEX_AI_LOCATION` is independent of the Cloud Run / bucket region.
- **`PortfolioPnL.by_factor_naive` is the persisted naive attribution.** There is NO `by_factor` alias. Pydantic v2's `computed_field` is included in `model_dump()` but rejected by `model_validate()` under `extra="forbid"`, which would poison the JSON cache round-trip. Readers must pick a specific variant: `by_factor_naive` / `by_factor_conditional_shapley` / `by_factor_conditional_shapley_explicit` / `by_factor_conditional_shapley_grouped`.
- **Four attribution variants live in `app/factors/attribution.py`:** `naive_attribution`, `conditional_shapley_attribution` (full F-dim game), `conditional_shapley_attribution_explicit` (game restricted to LLM-shocked factors; unshocked factors stay at 0; sum ≤ factor P&L by design), and `conditional_shapley_attribution_grouped` (full game then within-group sum + redistribute by naive share; sum = factor P&L; collapses within-group leakage like SPY↔ACWI). The explicit-only and grouped variants address the UX confusion of correlated-peer cross-credit. `app/factors/shocks.py::portfolio_pnl` computes all three Shapley variants when factor history is available; each is independently best-effort.
- **The grouped Shapley implementation is "full Shapley + within-group sum-and-redistribute", NOT synthetic-feature aggregation.** Aggregating member coefs+shocks before running shap introduces within-group cross-product terms `c_f · s_{f'}` that don't exist in the linear model. Running full Shapley first then summing φ_f within each group preserves efficiency exactly.
- **`conditional_shapley_attribution_explicit` short-circuits the 1-feature case.** shap.LinearExplainer's covariance path crashes on a 1-D background; for a single explicit shock the trivial Shapley value `coef · shock` is returned directly.
- **Conditional Shapley ≠ causal attribution.** It is *data-dependent credit allocation* under the historical conditional distribution of factor returns. The **full** variant can attribute nonzero credit to factors with zero LLM shock (via correlation). The **explicit-only** and **grouped** variants suppress that behavior. `frontend/src/charts.ts::hasCorrelationCrossCredit` gates the "No explicit LLM shock; attributed via correlation" label to the full-Shapley view only.
- **Use `shap.maskers.Impute(background)`** with the non-deprecated `LinearExplainer((coefs, intercept), masker)` form (see `app/factors/attribution.py`). The `feature_perturbation=` kwarg is deprecated in current shap; new code must avoid it.
- **Factor-return background must NOT `fillna(0)`.** `fetch_factor_returns_history` does `dropna(how="any")` then demeans, requiring ≥52 complete rows. Zero-filling a missing ETF manufactures false correlation that contaminates the Conditional Shapley values. The strict dropna restricts the background to the post-XLC-launch window (mid-2018+), which is correct.
- **Narrative decomposition is experimental counterfactual pipeline attribution**, not a clean causal decomposition. Each subset re-runs analog selection + grounded narrative + shock extraction, so the result reflects pipeline behavior on the subset, not a "true" contribution. Frame this honestly in both UI (expander label says "Experimental:") and methodology doc.
- **Narrative Shapley lives in `app/llm/narrative_shapley.py::compute_narrative_shapley`, NOT inside `run_scenario`.** The UI calls `run_scenario` first, then `compute_narrative_shapley` if opted-in, which calls `decompose_scenario` + reruns the pipeline 2^N − 1 times and attaches the result via `model_copy(update={"narrative_shapley": ...})`. Putting it inside `run_scenario` would invite recursion and control-flow confusion.
- **`PROMPT_VERSION` covers cache invalidation for prompt OR schema changes.** v3 → v4 because `PortfolioPnL.by_factor` was renamed to `by_factor_naive` + new field added + `ScenarioResult.narrative_shapley` introduced. v4 → v5 added `by_factor_conditional_shapley_explicit` and `by_factor_conditional_shapley_grouped`. A future refactor may split this into `PROMPT_VERSION` + `SCENARIO_CACHE_VERSION`; for now one bump suffices.
- **N must be in [2, 4] for narrative Shapley.** Both `decompose_scenario` and `compute_narrative_shapley` raise `RuntimeError` if the decomposer returns out-of-range. N=5 would be 31 subset runs ≈ 8 min sync wall-clock and is cut off intentionally.
- **Narrative Shapley runs subsets in parallel.** `compute_narrative_shapley` submits all 2^N−1 non-empty subsets to a `ThreadPoolExecutor` (`config.narrative_shapley_max_workers`, default 4) and drains via `concurrent.futures.as_completed` so the progress callback fires from the main thread. `subset_pnls` is keyed by mask, not by completion order — the Shapley math is deterministic regardless of how the pool drained. If Gemini rate-limits show up in practice, drop `NARRATIVE_SHAPLEY_MAX_WORKERS=2`.
- **yfinance is cached at the `_fetch_prices` layer.** `app/data/market.py` consults a process-wide `CloudStorageCache` (prefix `market_data`, parquet, 24h TTL) keyed on `(sorted_tickers, interval, start, end)` before calling `yf.download`. Cache failures (no GCS creds, parquet schema mismatch) silently fall back to yfinance — both read and write paths are wrapped in `contextlib.suppress(Exception)`. The singleton is `app/data/market_cache.py::get_market_cache()` (lru_cache(maxsize=1)); tests pass `cache=None` explicitly to bypass.
- **`run_scenario` parallelizes portfolio-prices vs factor-history fetches.** Inside the cache-miss path, `fetch_weekly_prices(portfolio.tickers)` and `get_factor_returns_with_history(...)` are submitted to a 2-worker ThreadPoolExecutor and joined before `estimate_betas_for_portfolio` runs. The combined factor fetch returns `(raw_returns, demeaned_history_or_None)` — passes BOTH into the beta estimator AND the SHAP background, eliminating a duplicate yfinance round-trip that existed pre-Phase-9.
- **`compute_envelope` parallelizes per-event yfinance calls.** Up to 8 concurrent `fetch_event_returns` workers. Order-preserving via `executor.map`.
- **In-process warm cache lives in `app/factors/warm_cache.py`, NOT in `app/ui/`.** Originally planned as `@st.cache_resource`; corrected to `functools.lru_cache(maxsize=4)` so it survives the FastAPI rewrite. `app/factors/analogs.py::load_events`/`event_summaries`/`events_version` and `app/factors/universe.py::factor_universe_version` are also lru_cached. Call `warm_cache.warm()` from a FastAPI `lifespan` hook to pre-populate.
- **Mocks for `run_scenario` MUST stub THREE market-layer functions** in the scenario module's namespace (per the parallelized hot path): `app.llm.scenario.fetch_weekly_prices`, `app.llm.scenario.get_factor_returns_with_history`, and `app.llm.scenario.estimate_betas_for_portfolio`. See `tests/test_scenario.py::_patch_market_layer`. The beta-estimator mock must accept `**kwargs` because the orchestrator passes pre-fetched `factor_returns=` and `ticker_returns=` into it.
- **yfinance is hoisted above the Gemini chain in `run_scenario`** (Phase 10). The ThreadPoolExecutor that fetches portfolio prices ∥ factor history is opened immediately after the cache check and stays open across `select_analogs` → `compute_envelope` → `propose_shocks_with_retry`. yfinance becomes effectively free (~2-6s) by overlapping with the ~8-16s Gemini chain. Don't move it back below the Gemini calls "for clarity" — it's a deliberate parallelism win.
- **`run_scenario` accepts an optional `progress: Callable[[str, str], None]` callback** (Phase 10). It fires `progress(stage, status)` at stage boundaries: `cache_check`, `cache_hit`, `market`, `analogs`, `envelope`, `narrative`, `betas`, `attribution`. The SSE endpoint at `/api/scenarios/run-stream` wraps this — the worker thread runs `run_scenario(progress=...)` and a `queue.Queue` carries events to the FastAPI generator. `run_scenario` itself NEVER emits `"done"`; the SSE wrapper emits `{"stage":"done","result":...}` after the function returns.
- **The 3 Shapley fits in `portfolio_pnl` run in a 3-worker `ThreadPoolExecutor`** (Phase 10). `shap.LinearExplainer` drops into SciPy/NumPy linalg which releases the GIL, so threading buys real parallelism (~2-4s saved). Each variant still degrades independently to `None` on exception — the parallelism wraps the same `try/except` pattern, futures-style.
- **Iterative shock adjustment is structured editing, NOT free-form re-proposal.** `adjust_scenario_shocks` in `app/llm/scenario.py` takes a `cache_key` (NOT a client-supplied `prior_result`) and either `overrides: dict[str, float]` (manual sliders) or `adjustment_text: str` (LLM prompt). The server re-fetches the trusted canonical from cache. Narrative, citations, analogs_selected, periphery_shocks, and factor_envelope are guaranteed byte-for-byte unchanged by `model_copy`, not by prompt wording. Only `factor_shocks`, `portfolio_pnl`, and `adjustment_history` change. Derived results are NOT cached.
- **The LLM patch is a separate schema (`ShockEditPatch`), NOT `ShockProposalOutput`.** Reusing the proposal schema would let the model rewrite narrative/periphery, which violates the editing invariants. `ShockEditPatch` carries `scope: Literal["local", "rerun_required"]` + `edits: list[FactorEdit]` + `rejection_reason: str | None`. `scope="rerun_required"` surfaces via HTTP 422 with `rejection_reason` as the detail; the UI offers a "Rerun full scenario" CTA pre-filling the original text + adjustment. Semantic changes (new mechanism, new region, new factor) belong in a rerun, not an edit.
- **Zero-removal carve-out in `app/llm/adjust_validation.py::validate_factor_overrides`:** `new_shock == 0.0` is ALWAYS accepted regardless of envelope (explicit removal sentinel). Otherwise must be in `[p10, p90]`. This intentionally contradicts the looser `validate_shock_proposal` (which advisorily flags out-of-envelope on initial proposals) — adjustment is the surgical-edit path and has stricter rules encoded in code, not prompt wording. The validator also requires `set(overrides.keys()) == set(canonical_factor_names)`; missing or extra keys raise. UI guarantees this by rendering one slider per canonical factor.
- **`ScenarioRunResponse.cache_key` is the server's provenance handle.** The server computes it from `compute_scenario_cache_key(scenario_text, portfolio, market_date=...)` and returns it on both `/api/scenarios/run` and `/api/scenarios/run-stream`. The client echoes it back on `/api/scenarios/adjust-shocks`; the server re-fetches the canonical result and rejects with HTTP 410 if the cache TTL has expired. Don't trust client-supplied `prior_result` payloads — they're tamperable.
- **`ScenarioResult.adjustment_history: list[ShockAdjustment]` is a derived-only field with `default_factory=list`.** Canonical results round-tripped through the GCS cache always carry `[]`. Adjusted results carry a growing list, but adjusted results are never cached. Because the field has a default, the schema change did NOT require a `PROMPT_VERSION` bump — old v5 cached entries deserialize with `adjustment_history=[]`.
- **SSE client uses `fetch` + `ReadableStream`, not `EventSource`.** `frontend/src/api.ts::runScenarioStream` reads chunks and splits on `\n\n` frames manually. Reason: `EventSource` is GET-only and doesn't carry POST bodies; the chunked-reader approach also forwards cookies cleanly on same-origin requests. The terminal event is `{"stage":"done","result":...}`; the stream also handles `{"stage":"error","message":...}` by rejecting the promise.

---

## What NOT to do

- **Never commit `.env` or any `*.json` that looks like a service-account key.** `.gitignore` covers common patterns; the real mitigation is keeping keys outside the repo (e.g., `~/.gcp/nami-sa.json` or `C:/Users/<you>/.gcp/nami-sa.json`).
- **Never paste terminal output, shell prompts, or absolute filesystem paths into committed files** (README, CLAUDE.md, code comments, anywhere). Such pastes leak the user's Windows username, repo location, and project tree layout — and look unprofessional in a public repo. If you need to show example output, strip prompts (`PS C:\...>`, `$`) and replace paths with `<repo root>` / `~/path/`. The repo had a real incident where a 10-line yfinance session pasted into README's Tech Stack section; the `git grep -n 'PS C:\|OneDrive\|<your-username-pattern>' -- README.md CLAUDE.md` check below catches recurrences.
- **Before any `git push`, run the pre-commit content scan** (see Quality gates section). It catches accidental pastes, project-ID leaks, and embedded credentials by grepping the *staged diff*, not just filenames.
- **Never auto-commit on the user's behalf** unless explicitly asked. Stage explicit files (`git add file1 file2`), never `git add .` until ignores are verified.
- **Don't phase-jump.** README's Implementation Phases are ordered; each phase must be functional + tested before the next. Don't pull Phase 4 LLM work into a Phase 2 PR.
- **Don't preemptively migrate yfinance → Polygon.** The README has a deliberate one-file-change path in `app/data/market.py` when reliability demands it. Don't introduce abstractions for that swap until it's needed.
- **Don't add Shapley logic to `app/factors/shocks.py`.** Shapley lives in `app/factors/attribution.py::conditional_shapley_attribution`; `shocks.py` only orchestrates the call. Narrative-level Shapley lives in `app/llm/narrative_shapley.py`.
- **Don't widen the disclaimer surface or soften its language** — it's load-bearing for the regulatory framing ("scenario explorer" not "stress testing").

---

## Phase status

- [x] **Phase 0** — GCP setup (project, billing, APIs, service account, key, bucket)
- [x] **Phase 1** — Foundation (pyproject, config, market, cache, sample_portfolios, API/web shell)
- [x] **Phase 2** — Factor model (universe, regression, shocks)
- [x] **Phase 3** — Historical analog matcher (events YAML, analogs.py, COVID-verified)
- [x] **Phase 4** — LLM integration (Gemini + grounding + structured output + Scenario/Results UI)
- [x] **Phase 5** — UI build-out (editable Portfolio, Scenario form, Results dashboard with factor/periphery reasoning tables, Methodology rendering `docs/methodology.md`)
- [x] **Phase 6** — Live-LLM evaluation tests (3 network-gated semantic tests) + `docs/backtest_results.md` snapshot template + `docs/methodology.md`
- [x] **Phase 7** — Deploy (Cloud Run + Cloud Build 2nd-gen trigger; public `run.app` link with app-level passcode admin mode)
- [x] **Phase 8** — Advanced attribution: factor-level Conditional Shapley via `shap.LinearExplainer` + `shap.maskers.Impute` against demeaned historical factor returns; experimental narrative decomposition (2^N subset Shapley); Results-tab toggle + reasoning table; methodology section with axioms + framing
- [x] **Phase 9** — Streamlit → FastAPI + React/Vite/Plotly.js runtime; yfinance GCS cache + de-duped factor fetch + parallel I/O; in-process warm cache; narrative Shapley parallelization; explicit-only + grouped Shapley variants; React 4-mode attribution toggle; PROMPT_VERSION v4 → v5
- [x] **Phase 10** — Iterative shock-adjustment (sliders + LLM patch with scope classifier, server-side provenance via `cache_key`, zero-removal carve-out, `model_copy`-enforced invariants); scenario speedups (yfinance hoisted above the Gemini chain, parallel Shapley fits); SSE progress streaming via `/api/scenarios/run-stream` with a React stepper UI

Source of truth for phase scope: [README.md → Implementation Phases](README.md#implementation-phases).
