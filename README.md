# nami

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/ignitesplash101/nami/actions/workflows/ci.yml/badge.svg)](https://github.com/ignitesplash101/nami/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](pyproject.toml)
[![Vertex AI](https://img.shields.io/badge/Vertex_AI-Gemini_3.5_Flash-4285F4.svg)](docs/llm-system-design.md)

**波** — LLM-driven scenario explorer for equity portfolios.

**[🚀 Live demo →](https://nami-wy4mdlp7hq-an.a.run.app)** · Visitor mode runs sample scenarios against sample portfolios with no signup. Free-text scenarios, custom portfolios, backdating, and saved analytics require an admin passcode.

Describe a forward-looking market scenario in natural language; nami grounds it against current news, matches it to historical analogs, derives factor + idiosyncratic shocks, and computes the portfolio P&L impact with cited reasoning, four attribution variants, and full reproducibility metadata.

The name *nami* (波) is Japanese for "wave" — markets move in waves, factor shocks propagate in waves, and the engine decomposes portfolio impact into its constituent wave components.

<!-- Replace with actual screenshots/GIF once captured. See docs/img/README.md for capture guidance. -->
<!-- ![nami scenario run](docs/img/demo.gif) -->

📘 **[Methodology](docs/methodology.md)** — factor universe, beta estimation, conditional Shapley attribution, backdating semantics, references
🧠 **[LLM systems design](docs/llm-system-design.md)** — three-call pipeline, grounding/schema split, `PROMPT_VERSION` discipline, semantic evals
📊 **[Live-LLM eval snapshot](docs/backtest_results.md)** — dated snapshot + semantic invariants
🕰️ **[Backdated retrospective case studies](docs/backdated-case-studies.md)** — three known regimes replayed under no-look-ahead, with explicit leakage controls
💰 **[Cost controls](docs/cost-controls.md)** — auth audit + Console steps for billing budget + Vertex AI quota cap

---

## ⚠️ Disclaimer

This is an **educational and research tool**. It is **not investment advice**, **not regulatory stress testing**, and **not a substitute for institutional risk management**. Scenario outputs are illustrative and probabilistic, not predictive. Do not use outputs for actual trading, risk capital, or compliance decisions.

---

## What it does

Given a portfolio (sample or custom) and a natural-language scenario ("60% tariffs on China imports, prolonged trade war"), nami:

1. **Picks historical analogs.** Gemini selects 2–5 events from a curated registry of ~17 market-stress events whose mechanism matches the scenario.
2. **Computes an empirical envelope.** For each analog, nami pulls the realized factor returns over the event window from yfinance. Across the analogs it returns per-factor mean / p10 / p90 / count — the band the LLM's proposed shocks must stay inside.
3. **Grounds a narrative.** A second Gemini call runs with Google Search active and produces a 3–5 sentence forward-looking narrative, citing real recent news. Without citations, the pipeline refuses to return.
4. **Extracts structured shocks.** A schema-bound third call translates the narrative into a `FactorShock` list (for the 22-factor universe) and a `PeripheryShock` list (idiosyncratic, ticker-level).
5. **Computes portfolio P&L + attribution.** Mean-centered ridge OLS estimates the portfolio's factor betas on 3 years of weekly returns. The engine returns four attribution variants:
   - **Naive**: `(Σᵢ wᵢ·βᵢ,f) · shock[f]` — direct algebra, assumes factor independence.
   - **Conditional Shapley (full)**: axiom-compliant credit allocation under the historical conditional distribution; can attribute to factors the LLM didn't shock (via correlation).
   - **Explicit-only Shapley**: same axioms, restricted to the LLM-shocked factor set; unshocked factors stay at exactly zero.
   - **Grouped Shapley**: full Shapley then within-group sum + redistribution by naive share; collapses within-group leakage (SPY ↔ ACWI, MTUM ↔ QUAL).

Every saved result carries full reproducibility metadata (model id, prompt version, factor-universe version, events version, ridge α, lookback weeks, selected event ids, exact holdings, both requested and effective as-of dates) so any record can be re-rendered later without consulting live state.

## Key features

| | |
|---|---|
| **Realistic cap-weighted books** | Sample portfolios are **cap-weighted** from a frozen, dated snapshot (regenerated offline by `scripts/refresh_sample_weights.py`), not naive equal-weight — a real developed-world book is ~10% AAPL, not 2% of everything. The runtime never scrapes, so weights stay reproducible and cache-safe. |
| **Benchmark & active return** | Each book carries a benchmark (e.g. MSCI World→URTH, Tech→QQQ, Defensive→SPLV, Japan→EWJ; custom books optional). The benchmark is run through the same factor shocks and the result shows **active return** (portfolio − benchmark). |
| **Sector & country exposure** | Per-position sector/country tags (baked into the snapshot) drive a **weight + P&L breakdown** by sector or country under any result. |
| **Cash sleeve** | Add a zero-exposure **`CASH`** line to any custom book — it dilutes P&L (cash drag) and, in mark-to-market mode, is a USD amount marked at 1.0. |
| **Iterative shock adjustment** | Sliders or natural-language prompts ("make rates shock larger", "drop credit") edit the LLM's shocks in seconds without re-running analog selection or narrative grounding. |
| **Dollar view & mark-to-market** | Apply a **notional portfolio value** to any run (incl. visitors) for an instant dollar view — **original → stressed** position values, NAV→stressed NAV, and `$` P&L, recomputed live as you change the value (no re-run). Admins can instead enter **share quantities** for true **mark-to-market**: each position marked to the as-of raw close, FX-converted to USD (mixed-currency books like JPY/GBp handled; fails closed on a missing/stale mark). |
| **Backdated reports** | Run scenarios *as of* a historical date with strict no-look-ahead: events filtered by `end_date ≤ as_of`, yfinance fetches use `end=as_of`, analog-only narrative path (no Google Search, no current news). |
| **Dated portfolios** | Save named portfolios with time-series of immutable holding snapshots in Firestore. "Run a scenario against my 2024-06-30 book." |
| **Saved analytics library** | Persist any result with name, tags, notes, and full inline reproducibility metadata. Re-open via permalink (`?saved=<id>`) or browse a filterable library. |
| **SSE progress streaming** | Real-time stepper through the 7-step pipeline (cache_check → market → analogs → envelope → narrative → betas → attribution) while a scenario runs (~10-20s on cache miss). |
| **Methodology drawer** | Slide-in `docs/methodology.md` viewer with auto-parsed sections, deep-links from factor names + the attribution toggle, full academic citations. |
| **Mobile-friendly** | Off-canvas rail drawer, responsive grids, 44px touch targets, vertical SSE stepper on phones. Tested at 375 / 414 / 768 / 1024 / 1080 / 1920 widths. |
| **Design & accessibility** | A distinctive *Hokusai Deep* identity — Prussian-indigo ground, Fraunces display type, a wave-propagation SSE stepper and a 波 / seigaiha brand mark — over an accessible baseline: visible `:focus-visible` rings, focus-trapped modals, a keyboard-navigable radiogroup attribution control, labelled inputs, `aria-describedby` errors, and `prefers-reduced-motion` support. |

## Tech stack

- **Python 3.12** + **FastAPI** backend
- **React + TypeScript + Vite + Plotly.js** frontend (`frontend/`)
- **Vertex AI / Gemini 3.5 Flash** for the LLM calls (3 sub-calls per scenario)
- **yfinance** for historical price data, cached in **Google Cloud Storage** (parquet) with 24-hour TTL
- **GCS** also holds the scenario response cache (JSON, 7-day TTL — the de-dup layer)
- **Firestore** (added Phase 11) for saved scenarios, named portfolios, and dated snapshots
- **Cloud Run** for the deployed app, with **Secret Manager** for the admin passcode and **Cloud Build** (`nami-main-push` trigger) for CI/CD

Region split: Cloud Run + GCS + Firestore + Artifact Registry in `asia-northeast1`; Vertex AI (Gemini 3.5 Flash) in `global` (this model isn't available regionally).

## Visitor vs admin

The deployed app is publicly viewable. Visitor mode allows running the curated sample scenarios against the four sample portfolios — enough to demo the engine without exposing extra Gemini spend or custom inputs to the open internet.

Admin mode is unlocked by a passcode stored in Secret Manager (`nami-passcode:latest`). Admin enables: free-text scenarios, custom portfolio uploads, slider/prompt shock adjustments, narrative decomposition (experimental 2^N subset Shapley), backdated as-of dates, saved-scenario library, and dated-portfolio snapshots.

## Architecture overview

```
[user] ─┐
        ├─→ Cloud Run (FastAPI + React build)
        │       │
        │       ├─→ Vertex AI / Gemini  (analog selection, grounded narrative, shock extraction)
        │       │     └─ Google Search tool active for current-day; OFF for backdated runs
        │       ├─→ yfinance (via httpx)
        │       │     └─ Cached in GCS parquet, 24h TTL
        │       ├─→ GCS scenario cache (JSON, 7d TTL)  — de-dup of full ScenarioResult
        │       └─→ Firestore                          — saved scenarios + portfolios
        │            ├─ saved_scenarios/{id}             (inline result + analog events + reproducibility)
        │            └─ portfolios/{id}/snapshots/{id}   (named portfolio + dated holdings)
        │
[Cloud Build] ←── git push to main ── auto rebuilds + deploys Cloud Run revision
```

The engine code is structured for swappability: `app/data/market.py` is the one file that would change to migrate yfinance → Polygon; `app/data/cache.py` `CacheProtocol` lets tests inject an `InMemoryCache`; `app/data/firestore_store.py` exports an `InMemoryFirestoreStore` test double.

## Repository layout

```
app/
├── api/                   FastAPI endpoints, auth, schemas
├── data/                  market data + caches (GCS + Firestore)
├── factors/               factor universe, regression, shocks, attribution, analog matcher
├── llm/                   Gemini client, prompts, scenario orchestrator, narrative Shapley
└── utils/                 calendar, disclaimers, hashing
frontend/
└── src/                   React app — components, hooks (useOverlay, useMediaQuery), api client
tests/                     pytest suite — 120+ tests including invariant-only worked example
docs/
├── methodology.md         engine math, attribution variants, backdating, references
└── backtest_results.md    live-LLM eval snapshot
data/
└── historical_events.yaml curated event registry
```

## Local development

```bash
git clone https://github.com/ignitesplash101/nami
cd nami
uv sync                          # install Python deps
cp .env.example .env             # fill in GOOGLE_CLOUD_PROJECT, VERTEX_AI_LOCATION, GCS_BUCKET, PASSCODE

# Backend
uv run uvicorn app.api.main:api --reload --host 0.0.0.0 --port 8080

# Frontend (separate terminal)
cd frontend
npm install
npm run dev                      # Vite dev server on localhost:5173
```

The dev frontend proxies API calls to `localhost:8080`. To exercise the full pipeline including Firestore-backed saving you need a GCP project with Firestore enabled and the service account configured — see "Deploying to Cloud Run" below.

### Test suite

```bash
uv run pytest tests/ -v           # 120+ tests; live-LLM evals are network-gated
uv run ruff check .
uv run black --check .
cd frontend && npm test -- --run  # vitest + RTL
cd frontend && npm run build      # TypeScript + Vite production build
```

Live-LLM evaluation tests are gated on `RUN_NETWORK_TESTS=1` (cost ~$0.001 each).

## Deploying to Cloud Run

Cloud Build trigger `nami-main-push` rebuilds + redeploys on every push to `main`. One-time setup per GCP project:

```bash
# 1. Service account
gcloud iam service-accounts create nami-sa --display-name="nami runtime"
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:nami-sa@$PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/aiplatform.user"
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:nami-sa@$PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/storage.objectAdmin"
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:nami-sa@$PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"

# 2. Firestore (added Phase 11 — required for saved analytics)
gcloud firestore databases create --location=asia-northeast1 --type=firestore-native
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:nami-sa@$PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/datastore.user"

# Composite index for tag-filtered scenario listing
gcloud firestore indexes composite create \
    --collection-group=saved_scenarios \
    --field-config=field-path=tags,array-config=contains \
    --field-config=field-path=created_at,order=descending

# 3. Buckets + secrets
gsutil mb -l asia-northeast1 gs://nami-cache-$PROJECT_ID
echo -n 'your-passcode' | gcloud secrets create nami-passcode --data-file=-

# 4. Cloud Build trigger (one-time, via console or gcloud builds triggers create)
```

Then push to main and the trigger handles the rest.

## Design choices worth knowing

- **Conditional Shapley ≠ causal attribution.** It's data-dependent credit allocation under the historical conditional distribution. Janzing et al. (2020) and Aas et al. (2021) are the load-bearing citations; the methodology doc has a longer treatment.
- **Backdating is data-vintage-controlled, not model-vintage-controlled.** Events, factor history, and prices are strictly filtered to `≤ as_of`. The LLM's parametric knowledge is NOT — it still "knows" about COVID even when as_of is 2018. The UI banner makes this honest.
- **`temperature=0` everywhere.** Same scenario + same portfolio + same effective as-of date + same prompt version + same model = same shocks, byte-for-byte cached.
- **PROMPT_VERSION is the single cache-invalidation lever.** It bumps with any change to prompt semantics OR `ScenarioResult` shape. Currently v7. Post-cache overlays (mark-to-market, benchmark/active return) and display-only fields do NOT bump it — they're attached after retrieval and never persisted.
- **Sample portfolios are cap-weighted from a frozen, dated snapshot.** `app/data/sample_portfolio_weights.json` holds committed cap-weights + sector/country tags, regenerated offline by `scripts/refresh_sample_weights.py`. The runtime never scrapes, so weights can't drift and poison the cache.
- **Benchmark & active return are a non-cached overlay.** Each book carries a benchmark ticker (sample books built-in; custom books optional); the benchmark is run as a one-holding portfolio through the same factor shocks and `active_return = portfolio − benchmark` is attached post-cache.
- **`CASH` is a zero-exposure sentinel.** A cash sleeve is never fetched from yfinance, carries a zero-beta/zero-return row (its weight dilutes the rest), and in MTM mode a `CASH` quantity is a USD amount marked at 1.0. An all-cash book is rejected (nothing to shock).
- **Saved records are self-contained.** Inline holdings, inline analog event details, inline result, inline reproducibility metadata. A saved scenario doesn't depend on the live event registry or the GCS cache TTL.

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 ignitesplash101.

## Maintainer

Ryan Seet — Risk Implementation, Tokyo
Not affiliated with any employer; built independently as an educational portfolio piece.
