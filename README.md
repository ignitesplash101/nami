# nami

**波** — LLM-driven scenario explorer for equity portfolios.

Describe a forward-looking market scenario in natural language; the engine grounds it against current market context (via Gemini web search), matches it to historical analogs, derives core and periphery factor shocks, and computes the portfolio P&L impact with cited reasoning.

The name *nami* (波) is Japanese for "wave" — markets move in waves, factor shocks propagate in waves, and the engine decomposes portfolio impact into its constituent wave components.

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
5. Results dashboard: P&L attribution, factor contributions, name-level breakdown, scenario narrative

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
│ Cloud Run (Streamlit container, min=0, max=2)                   │
│ ├── Auth: Identity-Aware Proxy (whitelist of Google accounts)   │
│ └── App                                                          │
│     ├── UI: Streamlit (Portfolio | Scenario | Results | Method) │
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
- **Streamlit** 1.40+ (UI)
- **google-cloud-aiplatform** (Vertex AI SDK, `gemini-3.5-flash`)
- **yfinance** (market data, v1)
- **pandas**, **numpy**, **statsmodels** (factor regression)
- **pyarrow** (parquet caching)
- **google-cloud-storage** (cache backend)
- **pydantic** v2 (structured LLM output validation)
- **pytest** (unit tests)
- **ruff** + **black** (lint + format)

GCP services: Cloud Run, Vertex AI, Cloud Storage, Secret Manager, Cloud Build, Artifact Registry, IAP, Cloud Billing.

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
│   ├── main.py                  # Streamlit entry point
│   ├── config.py                # env + secrets loading
│   ├── ui/
│   │   ├── portfolio_tab.py
│   │   ├── scenario_tab.py
│   │   ├── results_tab.py
│   │   └── methodology_tab.py
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
├── tests/
│   ├── test_factors.py
│   ├── test_analogs.py
│   ├── test_shocks.py
│   └── test_backtest.py         # 2008/2020/2022 sanity backtests
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
- [x] APIs enabled: Cloud Run, Vertex AI, Cloud Storage, Secret Manager, Cloud Build, Artifact Registry, IAP
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
- [x] Basic Streamlit app shell with 4 empty tabs

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
- [ ] `portfolio_tab.py`: load sample / upload CSV / display weights table
- [ ] `scenario_tab.py`: free-text scenario input + "Run Scenario" button
- [ ] `results_tab.py`:
  - P&L summary at top (portfolio %, $ if notionals given)
  - Factor contribution waterfall chart
  - Name-level breakdown table
  - LLM narrative below with citations as expandable footnotes
  - Analog windows visualization
- [ ] `methodology_tab.py`: static markdown explaining the factor model + analog approach + disclaimers
- [ ] Footer disclaimer on every page

### Phase 6 — Backtests + Validation (≈6h)
- [ ] `tests/test_backtest.py`:
  - Feed engine the scenario "March 2020 COVID" with portfolio = MSCI World
  - Engine should generate shocks within empirical 2020 range
  - Run all sample portfolios against 3 historical events and document outputs in `docs/backtest_results.md`
- [ ] Visible in README and methodology tab — the credibility piece.

### Phase 7 — Deploy (≈6h)
- [x] `Dockerfile` for Cloud Run (single-stage slim Python 3.12; uv + `--no-install-project` + `PYTHONPATH=/app`)
- [x] `cloudbuild.yaml`: build → push to Artifact Registry → deploy to Cloud Run (with `dynamicSubstitutions`)
- [x] Cloud Run config: `min-instances=0`, `max-instances=2`, memory=2Gi, timeout=300s, `--session-affinity`, `--concurrency=20`
- [ ] IAP setup: enable on Cloud Run service, configure whitelist (deferred — we use `--no-allow-unauthenticated` + IAM role binding for personal-portfolio scale; full IAP requires a load balancer and isn't worth the complexity at v1)
- [x] Cloud Run runtime SA (`nami-sa`) attached via `--service-account`; Vertex AI + GCS clients use ADC (no JSON key file in container, Secret Manager NOT involved)
- [x] Cloud Billing budget alert at $20/month
- [x] Cloud Build 2nd-gen trigger on push to `main` (`nami-main-push` in `asia-northeast1`)

### Phase 8 — Advanced Attribution (≈8h, post-v1)
The differentiator that turns this from "LLM demo" to "quant-credible engine." Ship v1 first; add this once the engine is stable end-to-end.

- [ ] Add `shap` to dependencies
- [ ] `app/factors/attribution.py`:
  - `naive_attribution(betas, shocks)` → dict of per-factor contributions
  - `shapley_attribution(betas, shocks, factor_covariance)` → Shapley values via `shap.LinearExplainer` against the factor covariance matrix
  - Both functions return identical schema; UI toggle selects which
- [ ] `app/factors/narrative_shapley.py`:
  - Given an LLM-generated scenario with N sub-narratives, re-run engine with each combination of narratives included/excluded
  - Compute Shapley values across narrative components
  - For N=5 narratives → 32 scenario evaluations (cache aggressively by hash)
- [ ] UI: "Attribution Method" toggle in results tab (Naive | Shapley)
- [ ] UI: "Narrative Decomposition" expandable card showing per-narrative Shapley contribution
- [ ] Methodology tab: explain inflation under correlated factors, show worked example
- [ ] `tests/test_attribution.py`: verify Shapley values sum to total P&L (efficiency axiom); verify naive vs Shapley diverge meaningfully when factors are collinear

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

### Why IAP (not custom auth)?
Public repo + private deployed app. IAP lets anyone clone and run locally with their own Vertex API key, while gating the hosted instance to a whitelist of Google accounts. Zero auth code to write, fully managed by GCP.

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

# Run
streamlit run app/main.py

# Tests
pytest
ruff check .
black --check .
```

---

## Deployment

```bash
# One-time setup
gcloud config set project <PROJECT_ID>
gcloud services enable run.googleapis.com aiplatform.googleapis.com \
  artifactregistry.googleapis.com cloudbuild.googleapis.com iap.googleapis.com

# Create artifact registry repo
gcloud artifacts repositories create nami \
  --repository-format=docker --location=asia-northeast1

# Create cache bucket
gsutil mb -l asia-northeast1 gs://<your-cache-bucket>

# Deploy
gcloud builds submit --config cloudbuild.yaml

# Enable IAP on the deployed service
gcloud run services add-iam-policy-binding nami \
  --region=asia-northeast1 --member=user:<email> --role=roles/run.invoker

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