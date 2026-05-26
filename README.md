# nami

**波** — LLM-driven scenario explorer for equity portfolios.

Describe a forward-looking market scenario in natural language; the engine grounds it against current market context (via Gemini web search), matches it to historical analogs, derives core and periphery factor shocks, and computes the portfolio P&L impact with cited reasoning.

The name *nami* (波) is Japanese for "wave" — markets move in waves, factor shocks propagate in waves, and the engine decomposes portfolio impact into its constituent wave components.

📘 **[Methodology](docs/methodology.md)** — factor universe, beta estimation, LLM pipeline, reproducibility
📊 **[Backtest results](docs/backtest_results.md)** — live-LLM evaluation snapshot + semantic invariants

---

## ⚠️ Disclaimer

This is an **educational and research tool**. It is **not investment advice**, **not regulatory stress testing**, and **not a substitute for institutional risk management**. Scenario outputs are illustrative and probabilistic, not predictive. Do not use outputs for actual trading, risk capital, or compliance decisions.

---

## What It Does

User flow:

1. User loads a portfolio (sample provided or upload CSV: `ticker, weight`)
2. User describes a scenario in natural language ("60% US tariffs on China imports, prolonged trade war")
3. **Gemini 3.5 Flash** (with Google Search grounding) generates:
   - Scenario context with current-market citations
   - Historical analog windows (e.g. "2018 Q4 trade war, 2020 March COVID")
   - Proposed core factor shocks (equity index, sector, style, macro), constrained by analog empirical distributions
   - Proposed periphery shocks (name-specific idiosyncratic moves)
   - Natural language reasoning for each shock
4. Engine computes portfolio P&L via pre-estimated factor betas
5. Factor-level **Conditional Shapley** attribution (correlation-aware credit allocation, toggle-selectable against naive) and an opt-in **experimental narrative decomposition** that re-runs the engine across subsets of LLM-generated sub-narratives to assign per-narrative Shapley contributions
6. Results dashboard: P&L attribution, factor contributions, name-level breakdown, scenario narrative

---

## What It Is NOT

- Not a regulatory stress engine (no Basel SA/IMA, no FRTB, no CCAR/DFAST)
- Not a real-time risk system
- Not multi-asset (equity only in v1 — fixed income, FX, commodities deferred)
- Not a trading signal
- Not deterministic in scenario *narrative*; deterministic in shock *magnitudes* (cached by hash)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ Cloud Run (FastAPI + React container, min=0, max=2)             │
│ ├── Access: app-level visitor/admin controls                    │
│ └── App                                                          │
│     ├── UI: React + TypeScript + Plotly.js workbench            │
│     ├── API: FastAPI JSON endpoints                             │
│     ├── LLM: Vertex AI → gemini-3.5-flash (search grounding)    │
│     ├── Factor Engine: pandas + statsmodels regression          │
│     ├── Analog Matcher: historical event registry + windowing   │
│     └── Market Data: yfinance + Cloud Storage cache (parquet)   │
├─────────────────────────────────────────────────────────────────┤
│ Vertex AI · Cloud Storage · Secret Manager · Cloud Build        │
│ Cloud Billing (budget alert: $20/month — alert only)            │
└─────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack (pinned)

- **Python** 3.12
- **FastAPI** + **Uvicorn** (backend/API)
- **React**, **TypeScript**, **Vite**, **Plotly.js** (frontend/UI)
- **google-cloud-aiplatform** (Vertex AI SDK, `gemini-3.5-flash`)
- **yfinance** (market data, v1)
- **pandas**, **numpy**, **statsmodels** (factor regression)
- **pyarrow** (parquet caching)
- **google-cloud-storage** (cache backend)
- **pydantic** v2 (structured LLM output validation)
- **pytest** (unit tests)
- **ruff** + **black** (lint + format)

GCP services: Cloud Run, Vertex AI, Cloud Storage, Secret Manager, Cloud Build, Artifact Registry, Cloud Billing.

---

## Project Structure

```
nami/
├── README.md                    # this file
├── CLAUDE.md                    # AI agent dev notes (create separately)
├── pyproject.toml               # uv or poetry config
├── Dockerfile                   # Cloud Run container
├── .dockerignore
├── .gcloudignore
├── cloudbuild.yaml              # Cloud Build pipeline
├── app/
│   ├── __init__.py
│   ├── api/                     # FastAPI app + request/response schemas
│   ├── config.py                # env + secrets loading
│   ├── llm/
│   │   ├── gemini_client.py     # Vertex AI client wrapper
│   │   ├── prompts.py           # system prompts + templates
│   │   ├── schemas.py           # pydantic models for structured output
│   │   └── grounding.py         # Google Search grounding helpers
│   ├── factors/
│   │   ├── universe.py          # factor definitions (market/sector/style/macro)
│   │   ├── regression.py        # rolling beta estimation
│   │   ├── shocks.py            # apply factor shocks → P&L
│   │   └── analogs.py           # historical event registry + matcher
│   ├── data/
│   │   ├── market.py            # yfinance wrapper + cache
│   │   ├── cache.py             # Cloud Storage parquet I/O
│   │   └── sample_portfolios.py # pre-loaded sample portfolios
│   └── utils/
│       ├── hashing.py           # scenario → cache key
│       └── disclaimers.py       # disclaimer strings + footer
├── frontend/
│   ├── package.json             # React/Vite frontend deps
│   └── src/                     # workbench, Plotly charts, typed API client
├── tests/
│   ├── test_api.py
│   ├── test_factors.py
│   ├── test_analogs.py
│   └── test_live_evals.py       # network-gated live LLM semantic checks
├── data/
│   ├── historical_events.yaml   # event registry (date ranges + tags)
│   └── factor_universe.yaml     # factor definitions
└── docs/
    ├── methodology.md           # factor model documentation
    ├── disclaimers.md
    └── screenshots/
```

---

## Implementation Phases

Build in this order. Each phase must be functional and tested before moving to the next.

### Phase 0 — Prerequisites (manual, ~30min)
Done by the human before invoking the agent. Do **not** automate.
- [x] GCP project created, billing linked, budget alert set at $20/month
- [x] APIs enabled: Cloud Run, Vertex AI, Cloud Storage, Secret Manager, Cloud Build, Artifact Registry
- [x] Service account created with roles: `roles/aiplatform.user`, `roles/storage.objectAdmin`, `roles/secretmanager.secretAccessor`
- [x] Service account JSON downloaded to local machine
- [x] Cache bucket created: `gs://nami-cache-<project-id>`
- [ ] Artifact Registry repo created: `nami` in `asia-northeast1`
- [x] `.env.example` documented with all required env vars
- [ ] GitHub repo created (private until v1 ships, then flip public)

### Phase 1 — Foundation (≈8h)
- [x] `pyproject.toml` with pinned deps
- [x] `app/config.py` reads from env vars (Secret Manager integration deferred to Phase 7)
- [x] `app/data/market.py` wraps yfinance, returns adjusted weekly close prices
- [x] `app/data/cache.py` reads/writes parquet to Cloud Storage with 24h TTL
- [x] `app/data/sample_portfolios.py` provides 4 sample portfolios:
  - MSCI World approximation (~50 large caps, market-cap weighted)
  - US Tech Growth (FAANG+ heavy)
  - Defensive Mix (staples, utilities, healthcare)
  - Japan Equity (TOPIX Core 30 subset)
- [x] FastAPI + React/Vite app shell with portfolio, scenario, results, and methodology surfaces

### Phase 2 — Factor Model (≈10h)
- [ ] `app/factors/universe.py` defines factor universe:
  - **Market:** SPY, ACWI
  - **Sectors:** XLK, XLF, XLE, XLV, XLI, XLY, XLP, XLU, XLB, XLRE, XLC (GICS 11)
  - **Styles:** MTUM, QUAL, VLUE, SIZE, USMV
  - **Macro:** ^TNX (10Y yield), DX-Y.NYB (USD index), ^VIX, CL=F (oil)
- [ ] `app/factors/regression.py` estimates betas via OLS on 156 weeks of returns (3y), with ridge regularization to handle collinearity. Output: `{ticker: {factor: beta, ...}}`.
- [ ] `app/factors/shocks.py` applies factor shock vector to beta matrix → expected return per stock → portfolio P&L.
- [ ] Unit tests: known portfolio → known shock → expected P&L within tolerance.

### Phase 3 — Historical Analog Matcher (≈8h)
- [x] `data/historical_events.yaml` registry of historical events with:
  - Event name, start/end dates, tags (trade-war, pandemic, inflation, geopolitical, banking, energy, central-bank)
  - Brief description
  - At least 15 events covering 2007–2025 (GFC, Euro crisis, 2013 taper tantrum, 2015 China devaluation, 2016 Brexit, 2018 Q4 trade war, 2020 COVID, 2022 inflation/Ukraine, 2023 SVB, 2024 yen carry unwind, etc.)
- [x] `app/factors/analogs.py`:
  - Given event date ranges, pull realized factor returns over those windows
  - Compute empirical distribution (mean, p10, p90) per factor across analogs
  - This is the constraint envelope passed to the LLM
- [x] Unit tests: hand-verify 2020 COVID returns match Wikipedia historical record within reason.

### Phase 4 — LLM Integration (≈10h)
- [x] `app/llm/schemas.py` pydantic models:
  - `ScenarioRequest` (user input + portfolio + factor universe + analog envelope)
  - `ScenarioResponse` (analogs_selected, factor_shocks, periphery_shocks, reasoning, citations)
- [x] `app/llm/prompts.py` system prompt that:
  - Embeds the disclaimer
  - Defines the factor universe with descriptions
  - Provides the analog empirical envelope as constraints
  - Instructs JSON-structured output (pydantic schema)
  - Requires citations for any current-market claims
- [x] `app/llm/gemini_client.py`:
  - Vertex AI client init with project + location from config
  - Model: `gemini-3.5-flash`
  - `temperature=0` (reproducibility)
  - Google Search grounding tool enabled
  - Structured output via response_schema
  - Returns parsed pydantic object + citation list
- [x] `app/utils/hashing.py` cache key: SHA256 of (scenario_text + portfolio_key + holdings + market_date + model_id + prompt_version + factor_universe_version + events_version)
- [x] Cache LLM responses to Cloud Storage (`scenario_cache/{hash}.json`, 7d TTL)

### Phase 5 — UI (≈10h)
- [x] React/Vite workbench: load sample / upload CSV / inline editable holdings
- [x] Scenario form: visitor sample mode + admin free-text scenario input
- [x] Results dashboard:
  - P&L summary at top with shock vs contribution distinction
  - Factor contribution waterfall chart via Plotly.js
  - Factor reasoning + Periphery reasoning tables (LLM rationale per shock)
  - Name-level breakdown table
  - LLM narrative below with citations as expandable footnotes
  - Analog windows table
- [x] Methodology panel renders `docs/methodology.md`
- [x] Disclaimer banner visible in the app shell

### Phase 6 — Backtests + Validation (≈6h)
- [x] `tests/test_live_evals.py` (renamed from `test_backtest.py` — these hit live Gemini + Google Search and are stochastic over news drift, not deterministic backtests):
  - Pandemic scenario → at least one pandemic-tagged analog selected + citations returned
  - Banking-stress scenario → XLF shock more negative than SPY (financials lead)
  - Taiwan scenario on US tech growth → periphery shock on ≥1 semi (NVDA/AMD/AAPL/AVGO/AMAT/QCOM)
  - Gated on `RUN_NETWORK_TESTS=1`; documented in [`docs/backtest_results.md`](docs/backtest_results.md)
- [x] Methodology + backtest links visible in README ([`docs/methodology.md`](docs/methodology.md), [`docs/backtest_results.md`](docs/backtest_results.md)) — the credibility piece

### Phase 7 — Deploy (≈6h)
- [x] `Dockerfile` for Cloud Run (single-stage slim Python 3.12; uv + `--no-install-project` + `PYTHONPATH=/app`)
- [x] `cloudbuild.yaml`: build → push to Artifact Registry → deploy to Cloud Run (with `dynamicSubstitutions`)
- [x] Cloud Run config: `min-instances=0`, `max-instances=2`, memory=2Gi, timeout=300s, `--session-affinity`, `--concurrency=20`
- [ ] IAP setup: deferred — hosted access uses lightweight app-level visitor/admin controls; full IAP requires a load balancer and remains optional hardening
- [x] Cloud Run runtime SA (`nami-sa`) attached via `--service-account`; Vertex AI + GCS clients use ADC (no JSON key file in container)
- [x] Cloud Billing budget alert at $20/month
- [x] Cloud Build 2nd-gen trigger on push to `main` (`nami-main-push` in `asia-northeast1`)

### Phase 8 — Advanced Attribution (≈8h, post-v1)
The differentiator that turns this from "LLM demo" to "quant-credible engine."

- [x] Add `shap` to dependencies (`shap>=0.46,<1.0`)
- [x] `app/factors/attribution.py`:
  - `naive_attribution(betas, shocks, weights)` → dict of per-factor contributions
  - `conditional_shapley_attribution(betas, shocks, weights, factor_returns_history)` → Conditional Shapley values via `shap.LinearExplainer` + `shap.maskers.Impute` against the demeaned, dropna'd historical factor-return matrix
  - Both functions return identical schema; UI toggle selects which. `PortfolioPnL` persists both as `by_factor_naive` (required) and `by_factor_conditional_shapley` (optional)
- [x] `app/llm/narrative_shapley.py`:
  - Given a scenario, calls `decompose_scenario` to split into N ∈ [2, 4] sub-narratives
  - Re-runs the full pipeline on each of the 2^N subset combinations (capped at N=4 → 16 runs)
  - Computes exact Shapley values across narrative components; attaches `narrative_shapley` to the result via `model_copy(update=...)`. Lives OUTSIDE `run_scenario` — UI calls them in sequence
- [x] UI: "Attribution method" radio in Results tab (Naive | Conditional Shapley) — captions explicitly label Conditional Shapley as "NOT a causal attribution"
- [x] UI: "Experimental: narrative decomposition" expander on Results showing per-narrative Shapley + caption that this is counterfactual pipeline attribution, not a causal decomposition
- [x] Methodology tab: Conditional Shapley framing (axioms, what it is NOT, worked example, when to use which), narrative-decomposition section, all in [`docs/methodology.md`](docs/methodology.md)
- [x] `tests/test_attribution.py`: efficiency, symmetry, high-correlation redistribution, independence ⇒ Naive≈Shapley, insufficient-background guard
- [x] `tests/test_narrative_shapley.py`: efficiency + symmetry with mocked subset payoffs; decomposition count validation (raises on N∉[2,4])

### Phase 9 — JS frontend + scenario-generation speedups + attribution refinement
The runtime switches off Streamlit; the engine gets faster; Shapley attribution gains two user-friendlier variants.

- [x] **FastAPI + React/Vite/Plotly.js runtime.** Streamlit (`app/main.py`, `app/ui/*`) replaced by `app/api/*` JSON endpoints serving a typed React workbench under `frontend/`. Multi-stage Dockerfile (Node→Python). All access controls (visitor vs admin, passcode-protected session cookie) preserved.
- [x] **yfinance cache layer.** `app/data/market_cache.py` wraps `_fetch_prices` with a process-wide `CloudStorageCache` parquet layer (24h TTL). Cache hits skip yfinance entirely for the same (sorted_tickers, interval, start, end) window.
- [x] **De-duped factor-returns fetch.** `app/factors/regression.py::fetch_factor_returns_with_history` returns `(raw_returns, demeaned_history_or_None)` from a single yfinance call. `app/llm/scenario.py` previously fetched factor returns twice (once for betas, once for the SHAP background).
- [x] **Parallel yfinance fetches.** `compute_envelope` and `run_scenario` now use `concurrent.futures.ThreadPoolExecutor` to overlap independent yfinance calls.
- [x] **In-process warm cache.** `app/factors/warm_cache.py::get_factor_returns_with_history` is `functools.lru_cache`d for process-lifetime hits across scenarios in the same Cloud Run instance. `load_events`, `event_summaries`, `events_version`, and `factor_universe_version` are also lru_cached. Portable across Streamlit/FastAPI (no `@st.cache_resource` dependency).
- [x] **Parallel narrative Shapley.** `compute_narrative_shapley` runs the 2^N−1 subset re-runs through a `ThreadPoolExecutor` (`max_workers=4` default, drained via `as_completed` so the progress callback fires from the main thread). N=4 path goes from ~3–4 min sequential to ~30–45s.
- [x] **Explicit-shocks-only Shapley.** `conditional_shapley_attribution_explicit` runs the Shapley game over only the factors the LLM actually shocked. Unshocked factors stay at exactly 0; sum ≤ factor-driven P&L. Addresses the "model attributed credit to a factor I didn't shock" UX concern.
- [x] **Grouped Shapley.** `conditional_shapley_attribution_grouped` runs full Shapley then sums φ_f within each factor group (market / sector / style / macro), then redistributes by within-group naive share. Sum = factor P&L; within-group leakage collapses.
- [x] **React attribution toggle.** Results pane offers four modes: Naive | Conditional (full) | Explicit-only | Grouped — each disabled when the backing payload is None.
- [x] **`PROMPT_VERSION` v4 → v5** to invalidate cached scenarios under the new `PortfolioPnL` shape (`by_factor_conditional_shapley_explicit`, `by_factor_conditional_shapley_grouped`).
- [x] `tests/test_attribution.py`: explicit-only zero-on-unshocked, explicit-only ≈ full when all factors shocked, grouped sum = factor P&L, grouped collapses within-group correlation, unmapped-factor guard.
- [x] `frontend/src/charts.test.ts`: explicit-only and grouped attribution selectors + the correlation-label suppression.

### Phase 10 — Iterative shock adjustment + scenario speedups + SSE progress
Users can now iterate on the LLM-proposed shocks without re-running the full pipeline, and the wait on a cold scenario feels live.

- [x] **Iterative shock editing (admin-only).** New `/api/scenarios/adjust-shocks` endpoint accepts either `overrides: dict[str, float]` (manual sliders) or `adjustment_text: str` (LLM patch). `app/llm/scenario.py::adjust_scenario_shocks` re-fetches the canonical result from the GCS cache by `cache_key`, applies the edit, and recomputes P&L in ~1-4s without rerunning analog selection, grounded narrative, or beta estimation. Derived results are NOT cached.
- [x] **Structured-editing schema (`ShockEditPatch`).** Distinct from `ShockProposalOutput` so the LLM cannot rewrite narrative / citations / periphery. The patch carries `scope: Literal["local", "rerun_required"]` + `edits` + `rejection_reason`; semantic changes (new mechanism, new region, new factor) return HTTP 422 with a "Rerun full scenario" CTA in the UI.
- [x] **Zero-removal carve-out.** `app/llm/adjust_validation.py::validate_factor_overrides` always accepts `new_shock == 0.0` (explicit removal sentinel) regardless of envelope; otherwise enforces `[p10, p90]`. Also enforces exact factor-name-set match with the canonical so missing/extra keys are rejected.
- [x] **Provenance via `cache_key`.** The server includes `cache_key` on `/api/scenarios/run` responses; the client echoes it back on adjustments. The server re-fetches the trusted canonical and returns 410 if the cache TTL has expired. No client-supplied `prior_result` payload is ever trusted.
- [x] **Invariance enforced by code, not prompt.** `adjust_scenario_shocks` uses `model_copy(update={...})` so narrative, citations, analogs_selected, periphery_shocks, and factor_envelope come from the canonical reference byte-for-byte. Only `factor_shocks`, `portfolio_pnl`, and `adjustment_history` change. `tests/test_adjust_manual.py` and `tests/test_adjust_prompt.py` assert this invariance explicitly.
- [x] **yfinance hoisted above the Gemini chain.** `run_scenario` now opens its yfinance ThreadPoolExecutor immediately after the cache check, so portfolio prices ∥ factor history overlap the full ~8-16s Gemini chain (Call 1 → envelope → Call 2a → Call 2b). yfinance is effectively free on the critical path (~2-6s saved).
- [x] **Parallel Shapley fits.** `portfolio_pnl` runs the three `conditional_shapley_attribution*` variants in a 3-worker `ThreadPoolExecutor`. `shap.LinearExplainer` releases the GIL inside SciPy/NumPy, so threading buys real parallelism (~2-4s saved). Each variant still degrades independently to `None` on exception.
- [x] **SSE progress streaming.** New `/api/scenarios/run-stream` emits `data: {"stage":...,"status":...}` frames at each pipeline boundary, terminating with `{"stage":"done","result":...}`. `run_scenario(progress=callback)` powers it; the frontend reads via `fetch` + `ReadableStream` (so cookies + POST body work cleanly on same-origin). The React stepper component (`frontend/src/RunProgress.tsx`) renders an 8-stage indicator; cache hits flash a "Loaded from cache" badge.
- [x] **`AdjustmentPanel` React component.** Per-factor numeric input + range slider clamped to envelope p10/p90, per-factor "Remove" (→ 0.0), bulk "Reset to canonical", and a natural-language prompt box. Adjustment history rendered as a compact list (timestamp / kind / changed factors before→after).
- [x] **No `PROMPT_VERSION` bump needed.** New `adjustment_history` field on `ScenarioResult` uses `Field(default_factory=list)`, so cached v5 entries deserialize unchanged. Adjusted results are never cached, so the field never lands in the cache payload either.
- [x] `tests/test_adjust_manual.py`, `tests/test_adjust_prompt.py`, `tests/test_api_adjust.py` — invariance tests (periphery/narrative/citations/analogs byte-for-byte unchanged), validation tests (missing/extra/out-of-envelope rejected, zero-removal accepted), endpoint tests (403/400/410/422 paths), SSE TestClient tests (progress + cache-hit + exception event paths).

---

## Key Design Decisions

### Why historical analog grounding?
LLMs cannot reliably calibrate factor shock magnitudes from first principles. Without empirical grounding, "S&P -7%" is just plausible-sounding noise. The analog layer constrains the LLM to propose shocks *within the empirical envelope* of historically similar events. This is the difference between a defensible engine and a confident hallucination machine.

### Why `temperature=0`?
Risk people do not trust randomized outputs. Same scenario + same portfolio + same market date must produce the same shocks. Narrative wording may vary slightly across runs, but shock magnitudes are cached by scenario hash for full reproducibility.

### Why core + periphery split?
Core factors capture systematic risk that hits all stocks via beta exposure (~70% of cross-sectional variance for diversified portfolios). Periphery captures name-specific moves the LLM identifies from the scenario context (e.g., "TSMC down extra 15% on Taiwan-specific scenario"). This matches how institutional risk managers actually think.

### Why yfinance (not Polygon) in v1?
Lowest-friction start. yfinance is free, zero infra. Aggressive Cloud Storage caching mitigates rate-limit risk for portfolio-traffic levels. Migration path to Polygon ($29/mo) is one file change in `app/data/market.py` when reliability becomes a concern.

### Why lightweight hosted access controls first?
The v1 hosted app is intentionally low-friction: visitors can exercise the sample workflow, while unrestricted controls stay behind an app-level admin gate. Full IAP remains a later hardening option if the audience or threat model grows.

### Why "scenario explorer" framing?
The phrase "stress testing" is regulated under Basel and triggers compliance scrutiny. "Scenario explorer" or "scenario engine" describes the same functionality with no regulatory tripwire on a public-facing tool.

---

## Local Development

```bash
# Setup
git clone <repo>
cd nami
uv sync   # or: poetry install

# Configure (local)
cp .env.example .env
# Fill in:
#   GOOGLE_CLOUD_PROJECT=<your-project>
#   VERTEX_AI_LOCATION=global
#   GCS_BUCKET=<your-cache-bucket>
#   GOOGLE_APPLICATION_CREDENTIALS=<path-to-service-account-json>

# Run backend API
uv run uvicorn app.api.main:api --reload --host 0.0.0.0 --port 8080

# Run frontend in another terminal
cd frontend
npm install
npm run dev

# Tests
pytest
ruff check .
black --check .
cd frontend && npm test && npm run build
```

---

## Deployment

```bash
# One-time setup
gcloud config set project <PROJECT_ID>
gcloud services enable run.googleapis.com aiplatform.googleapis.com \
  artifactregistry.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com

# Create artifact registry repo
gcloud artifacts repositories create nami \
  --repository-format=docker --location=asia-northeast1

# Create cache bucket
gsutil mb -l asia-northeast1 gs://<your-cache-bucket>

# Deploy
gcloud builds submit --config cloudbuild.yaml

# Set budget alert
# (manually via Cloud Console → Billing → Budgets & alerts → $20/month alert. GCP budgets do NOT auto-cap spending.)
```

---

## Roadmap (post-v1)

- Migrate market data layer to Polygon if yfinance becomes unreliable
- Multi-asset support (rates, FX, commodities) — requires factor universe expansion
- Multi-currency portfolios (with FX hedging assumptions)
- Scenario library: pre-defined scenarios users can fork ("2008 GFC replay", "Taiwan invasion", "Sticky inflation")
- Conditional Value-at-Risk (CVaR) estimation under generated scenario
- Position-level Greek sensitivities for portfolios with options exposure
- Multi-language scenario input (Japanese / Chinese / Thai) — leverages existing Gemini multilingual capability

---

## Open Questions (decide during build)

1. **Notional handling:** support $ notional inputs or weight-only? (Recommend: weight-only in v1, notional optional)
2. **Beta estimation lookback:** 3y weekly (~156 obs) vs 5y weekly (~260 obs)? Trade-off between regime relevance and statistical robustness.
3. **Ridge alpha:** what value? (Recommend: cross-validate, default 0.1)
4. **Maximum portfolio size:** cap at 100 names in v1 to control yfinance and regression latency
5. **Analog window length:** fixed 4-week peri-event window, or event-specific? (Recommend: event-specific in YAML)

---

## License

MIT (recommended for portfolio repos). Add `LICENSE` file before first public push.

---

## Maintainer

Ryan Seet — Risk Implementation, Tokyo  
Not affiliated with any employer; built independently as an educational portfolio piece.
