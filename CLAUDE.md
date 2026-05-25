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
- **Streamlit** UI — 4-tab shell at `app/main.py`
- **GCP** — Vertex AI (`gemini-3.5-flash`), Cloud Storage (cache), Cloud Run (deploy)
- **Region split** (this matters):
  - Cloud Run / GCS bucket / Artifact Registry → `asia-northeast1`
  - Vertex AI → `global` (gemini-3.5-flash is NOT on `asia-northeast1` or `us-central1`)

---

## Where things live

```
app/
├── config.py                # env-var loader; validates 3 REQUIRED keys
├── main.py                  # Streamlit entry: 4 tabs + disclaimer banner
├── data/
│   ├── market.py            # yfinance wrapper: fetch_weekly_prices, compute_weekly_returns
│   ├── cache.py             # CloudStorageCache: parquet I/O with TTL via blob.updated
│   └── sample_portfolios.py # 4 curated portfolios (Portfolio dataclass)
├── factors/                 # Phase 2 — factor model (universe, regression, shocks)
│                            # Phase 3 — historical analog matcher (analogs.py)
├── llm/                     # Phase 4 — Vertex AI / Gemini integration
│                            #   schemas.py · prompts.py · grounding.py · validation.py
│                            #   gemini_client.py · scenario.py (orchestrator)
├── ui/                      # tab modules (portfolio_tab, scenario_tab, ...)
└── utils/
    └── disclaimers.py       # disclaimer strings + footer

tests/                       # pytest unit tests, in sync with the implementation phase
```

---

## Commands you'll actually use

```powershell
# from <repo root>

uv sync                            # install/update deps from pyproject.toml
uv run streamlit run app/main.py   # start the UI on http://localhost:8501
uv run pytest tests/ -v            # run unit tests
uv run ruff check .                # lint
uv run black --check .             # format check
uv run black .                     # format fix
```

To exercise the GCS cache or Vertex AI, the local `.env` must have all 4 REQUIRED keys populated. Template: `.env.example`.

---

## Coding conventions (specific to this repo)

- **Type hints required** on every public function (params + return).
- **`from __future__ import annotations`** at the top of every new module — keeps type hints as strings so `dict[str, float]` / `X | None` work without runtime cost.
- **`@dataclass(frozen=True)`** for value objects (`Config`, `Portfolio`, `Factor`).
- **Validate at boundaries.** Raise `ValueError` / `RuntimeError` with specific messages when inputs violate invariants. See `Portfolio.__post_init__` (weight sum) for the pattern.
- **No `print()` in library code** — `print` is for `__main__` smoke checks or CLI scripts only. Streamlit code uses `st.write` / `st.info` / `st.warning`.
- **No commented-out code, no `# TODO:`** — if you're not implementing it now, raise `NotImplementedError` and open a separate scope.
- **Comments only when the WHY is non-obvious.** Names + types do the explaining. Comments document irreducible context (a workaround, a constraint).

---

## Quality gates before "done"

1. `uv run pytest tests/ -v` — all green
2. `uv run ruff check .` — clean
3. `uv run black --check .` — clean
4. For UI changes: **actually run** `streamlit run app/main.py` and verify in the browser. Type-checking passing ≠ feature working.

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
- **Portfolio-tab editor uses DYNAMIC widget keys** (`f"portfolio_editor::{source_id}"`) so switching sample/upload creates a fresh `st.data_editor` instead of mutating session_state — Streamlit is brittle with the latter. Trade-off: switching source mid-edit drops in-progress changes.
- **CSV upload rules** (`_parse_csv` in portfolio_tab.py): required columns `ticker,weight`; uppercase tickers (`.T` suffixes preserved); reject blanks / duplicates / negatives / non-finite; totals in `[0.95, 1.05]` accepted as decimals OR `[95, 105]` as percentages (auto-normalized to decimals). Anything else is rejected.
- **`tests/test_live_evals.py` is network-gated on `RUN_NETWORK_TESTS=1`** and **stochastic over news drift** even with `temperature=0` — use semantic assertions only (tag membership, ordering, presence-of-citation), never magnitude bounds. `docs/backtest_results.md` is a DATED snapshot, not a permanent benchmark. Costs ~$0.001 per test.
- **Cloud Run runtime auth uses ADC**, not Secret Manager. `nami-sa` is attached via `--service-account=` in `cloudbuild.yaml`; the Vertex AI + GCS Python clients pick it up automatically. Do NOT set `GOOGLE_APPLICATION_CREDENTIALS` on Cloud Run — `app/config.py` tolerates its absence.
- **Streamlit binds to `$PORT`** on Cloud Run via the Dockerfile CMD (`--server.port=${PORT:-8080} --server.address=0.0.0.0`). Locally it still defaults to 8501. Don't drop `--server.address=0.0.0.0` — Cloud Run's TCP health checks fail on default `localhost`.
- **`--session-affinity` is enabled** in `cloudbuild.yaml`. Required for Streamlit's per-instance `st.session_state` to persist for a returning user.
- **Cloud Build 2nd-gen trigger** `nami-main-push` lives in `asia-northeast1`, uses the repository resource `projects/<PROJECT_ID>/locations/asia-northeast1/connections/nami-github-connection/repositories/ignitesplash101-nami`. Edit via Cloud Console → Triggers, or `gcloud builds triggers update`.
- **Cloud Build SA for this project is the compute-engine default** (`<PROJECT_NUMBER>-compute@developer.gserviceaccount.com`), NOT the legacy `<PROJECT_NUMBER>@cloudbuild.gserviceaccount.com`. `gcloud builds get-default-service-account` returns empty in some gcloud versions; derive reliably with `gcloud projects describe $PROJECT_ID --format="value(projectNumber)"` then construct `<NUMBER>-compute@developer.gserviceaccount.com`.
- **Dockerfile uses `uv sync --frozen --no-dev --no-install-project` + `PYTHONPATH=/app`.** Don't drop `--no-install-project` — without it, `uv sync` reads `pyproject.toml`'s `readme = README.md` field and fails because README isn't copied yet in the deps layer (and copying it would break layer caching).
- **Gemini 3.5 Flash region:** `global` / `us` / `eu` only. NOT `us-central1`, NOT `asia-northeast1`. `VERTEX_AI_LOCATION` is independent of the Cloud Run / bucket region.

---

## What NOT to do

- **Never commit `.env` or any `*.json` that looks like a service-account key.** `.gitignore` covers common patterns; the real mitigation is keeping keys outside the repo (e.g., `~/.gcp/nami-sa.json` or `C:/Users/<you>/.gcp/nami-sa.json`).
- **Never paste terminal output, shell prompts, or absolute filesystem paths into committed files** (README, CLAUDE.md, code comments, anywhere). Such pastes leak the user's Windows username, repo location, and project tree layout — and look unprofessional in a public repo. If you need to show example output, strip prompts (`PS C:\...>`, `$`) and replace paths with `<repo root>` / `~/path/`. The repo had a real incident where a 10-line yfinance session pasted into README's Tech Stack section; the `git grep -n 'PS C:\|OneDrive\|<your-username-pattern>' -- README.md CLAUDE.md` check below catches recurrences.
- **Before any `git push`, run the pre-commit content scan** (see Quality gates section). It catches accidental pastes, project-ID leaks, and embedded credentials by grepping the *staged diff*, not just filenames.
- **Never auto-commit on the user's behalf** unless explicitly asked. Stage explicit files (`git add file1 file2`), never `git add .` until ignores are verified.
- **Don't phase-jump.** README's Implementation Phases are ordered; each phase must be functional + tested before the next. Don't pull Phase 4 LLM work into a Phase 2 PR.
- **Don't preemptively migrate yfinance → Polygon.** The README has a deliberate one-file-change path in `app/data/market.py` when reliability demands it. Don't introduce abstractions for that swap until it's needed.
- **Don't add Shapley attribution to `app/factors/shocks.py`** — Phase 8, post-v1.
- **Don't widen the disclaimer surface or soften its language** — it's load-bearing for the regulatory framing ("scenario explorer" not "stress testing").

---

## Phase status

- [x] **Phase 0** — GCP setup (project, billing, APIs, service account, key, bucket)
- [x] **Phase 1** — Foundation (pyproject, config, market, cache, sample_portfolios, Streamlit shell)
- [x] **Phase 2** — Factor model (universe, regression, shocks)
- [x] **Phase 3** — Historical analog matcher (events YAML, analogs.py, COVID-verified)
- [x] **Phase 4** — LLM integration (Gemini + grounding + structured output + Scenario/Results UI)
- [x] **Phase 5** — UI build-out (editable Portfolio, Scenario form, Results dashboard with factor/periphery reasoning tables, Methodology rendering `docs/methodology.md`)
- [x] **Phase 6** — Live-LLM evaluation tests (3 network-gated semantic tests) + `docs/backtest_results.md` snapshot template + `docs/methodology.md`
- [x] **Phase 7** — Deploy (Cloud Run + Cloud Build 2nd-gen trigger; `--no-allow-unauthenticated` + IAM run.invoker instead of full IAP)
- [ ] Phase 8 — Advanced attribution (Shapley) — post-v1

Source of truth for phase scope: [README.md → Implementation Phases](README.md#implementation-phases).
