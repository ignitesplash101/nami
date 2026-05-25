# Methodology

> ⚠️ **Educational/research tool only.** Outputs are illustrative and probabilistic, not
> investment advice and not regulatory stress testing. Do not use for actual trading or
> capital allocation decisions.

---

## What nami does

A user describes a forward-looking market scenario in natural language ("60% US tariffs on
China imports, prolonged trade war"). nami:

1. Asks Gemini to pick 2–5 **historical analog events** from a curated registry whose
   *mechanism* matches the scenario.
2. Pulls the **realized factor returns** over each analog's window from yfinance and
   computes an **empirical envelope** (mean / p10 / p90 / count) per factor.
3. Asks Gemini to write a **grounded narrative** about the scenario (Google Search active
   → real news citations) and then, in a separate sub-call, **extract structured factor
   shocks + periphery shocks** that stay inside the empirical envelope.
4. Estimates the portfolio's **factor betas** via mean-centered ridge OLS on 3 years of
   weekly returns, applies the shocks, and returns a portfolio P&L with attribution.

Every forward-looking claim in the narrative is **cited** to a real source the LLM
retrieved during grounding. Without citations the pipeline refuses to return.

---

## Factor universe (22 factors)

All factors are tickers fetched via yfinance; each weekly "return" is the percent change in
the factor's adjusted-close price.

| group | factors |
|---|---|
| **Market** (2) | SPY (`SPY`), ACWI (`ACWI`) |
| **Sectors** (11 GICS) | XLK, XLF, XLE, XLV, XLI, XLY, XLP, XLU, XLB, XLRE, XLC |
| **Styles** (5 MSCI) | MTUM, QUAL, VLUE, SIZE, USMV |
| **Macro** (4) | TNX (`^TNX`), DXY (`DX-Y.NYB`), VIX (`^VIX`), OIL (`CL=F`) |

Unit convention: percent change of the weekly close. For macro indices that means percent
change in the *level* (so a VIX shock of `+0.50` = the VIX index spiking by 50%, e.g.
15 → 22.5). The full description per factor is in [`app/factors/universe.py`](../app/factors/universe.py).

**Pre-launch dates** matter for the analog matcher — events before a factor's ETF launch
return NaN for that factor and are excluded from its envelope count:

| factor | first available |
|---|---|
| Style ETFs (MTUM/QUAL/VLUE/SIZE/USMV) | 2013 |
| XLRE | 2015 |
| XLC | 2018 |
| ACWI | mid-2008 |

---

## Beta estimation

`app/factors/regression.py::estimate_betas` runs **mean-centered ridge OLS** on weekly
returns:

```
X̃ = X − mean(X, axis=0)            # T × F factor returns, centered
Ỹ = Y − mean(Y, axis=0)            # T × N ticker returns, centered
β̂ = solve(X̃ᵀX̃ + αI_F, X̃ᵀỸ)      # F × N — vectorized over tickers
```

- Default lookback: 156 weeks (3 years) per `Config.beta_lookback_weeks`.
- Default ridge `α = 0.1` per `Config.ridge_alpha` — stabilizes against the collinearity
  between SPY/ACWI/XLK and between sector ETFs.
- Mean-centering removes the through-origin bias when returns have nonzero historical
  means (equivalent to including an unpenalized intercept and discarding it).
- Uses `np.linalg.solve` instead of `inv` — more numerically stable, and vectorizes
  cleanly across all tickers in one call.

The unit test `test_estimate_betas_recovers_known_coefficients` (with zero-mean factors)
and `test_estimate_betas_handles_nonzero_factor_means` (with drift) prove the
implementation recovers known coefficients within 0.05 of truth.

---

## Historical analog matcher

`app/factors/analogs.py` loads a curated registry of 17 historical market-stress events
from [`data/historical_events.yaml`](../data/historical_events.yaml), spanning 2007–2025.
Each event has:

- `id` — stable kebab-case identifier (e.g. `covid-crash-2020`)
- `start_date`, `end_date` — daily-precision window (inclusive on both ends)
- `tags` — subset of `{trade-war, pandemic, inflation, geopolitical, banking, energy, central-bank, currency}`
- `description` — what happened and why it's a useful analog

For a given subset of event IDs, `compute_envelope` returns a per-factor DataFrame with
`mean`, `p10`, `p90`, and `count`:

- **Total return over the event window** (not weekly average) — `price[end] / price[start] − 1`
  using daily bars from yfinance. Daily precision so short events like the Aug 2024 yen
  carry unwind (7/31 → 8/5) are captured accurately rather than rounding to the wrong week.
- **Mean / p10 / p90** computed nan-aware across the selected events.
- **`count`** lets the LLM down-weight low-coverage factors (XLC has only post-2018
  observations; for events before then it's missing).

The custom YAML loader (`_UniqueKeyLoader`) refuses duplicate event_ids — silent overwrite
would create hard-to-debug coverage gaps.

---

## LLM pipeline

`app/llm/scenario.run_scenario` orchestrates two Gemini calls + one structured extraction.

### Call 1 — Analog selection (`select_analogs`)
- Input: scenario text + `event_summaries()` (JSON of all 17 events)
- No grounding tool, structured-output schema `AnalogSelectionOutput`
- Output: 2–5 event IDs the LLM thinks share the scenario's *mechanism*

### Call 2a — Grounded narrative (`_grounded_narrative`)
- Input: scenario + envelope + factor universe + holdings
- **Google Search tool ON**, NO `response_schema` (free-form text)
- Output: 3-5 sentence narrative citing recent market news

### Call 2b — Structured extraction (`_extract_structured_shocks`)
- Input: the grounded narrative from 2a + envelope + factor universe + holdings
- NO tools, `response_schema=ShockProposalOutput`
- Output: structured `FactorShock` + `PeripheryShock` list

**Why the split?** Gemini 3.5 Flash on Vertex AI honors `response_schema` faithfully but
frequently skips invoking `google_search` when both are passed in one config. The result is
valid JSON with no grounding metadata — i.e., the narrative *looks* current but isn't
actually sourced. We refuse to return that. Splitting into two sub-calls guarantees the
narrative is grounded (2a) and the structured output is well-formed (2b).

The grounded narrative is generated **once** (outside the validation retry loop) — only 2b
retries on validation errors, so a schema fix doesn't trigger redundant web grounding.

### Validation + repair
`app/llm/validation.validate_shock_proposal` rejects:
- Factor shocks for factors not in `FACTORS`
- Periphery shocks for tickers not in the portfolio
- Duplicates
- Factor shocks outside the envelope `[p10, p90]` when `count ≥ 3`

On validation failure, 2b is re-asked once with the errors embedded in the user message.
A second failure raises.

---

## Periphery shock layer

In addition to factor-driven returns, the LLM may propose name-specific *idiosyncratic*
shocks. These are **additive** on top of `β · factor_shock`:

```
return[i]              = (β · factor_shock)[i] + periphery_shocks.get(i, 0)
by_ticker_factor[i]    = w[i] · (β · factor_shock)[i]
by_ticker_periphery[i] = w[i] · periphery_shocks.get(i, 0)
by_ticker_total[i]     = by_ticker_factor[i] + by_ticker_periphery[i]
by_factor[f]           = (Σᵢ w[i] · β[i,f]) · factor_shock[f]
total_pnl              = Σᵢ by_ticker_total[i] = Σ_f by_factor[f] + Σᵢ by_ticker_periphery[i]
```

The two channels are **orthogonal** under this attribution — factor and periphery sum
independently to the total. Phase 8 (post-v1) will revisit using Shapley values when
factors are correlated.

---

## Reproducibility & caching

- `temperature=0` on every Gemini call.
- The scenario response is keyed by SHA256 of:
  ```
  scenario_text.strip().lower()
  + sorted(portfolio_holdings)
  + portfolio_key                  # "us_tech_growth" / "custom" / ...
  + market_date.isoformat()
  + vertex_model_id                # gemini-3.5-flash
  + PROMPT_VERSION                 # bumped for any prompt OR schema change
  + factor_universe_version()      # 12-char hash of FACTORS dict
  + events_version()               # 12-char hash of historical_events.yaml
  ```
- TTL = 7 days (`LLM_CACHE_TTL_DAYS`) on cache reads.
- Cache backend: `CloudStorageCache` (GCS, prefix `scenario_cache/`), JSON serialized via
  `ScenarioResult.model_dump(mode="json")`. Tests inject `InMemoryCache` instead.

`PROMPT_VERSION` is the single invalidation lever: bumping it forces every cached scenario
to be re-derived against the new prompts / schema. Same-day re-runs of an unchanged scenario
hit cache in <500ms; the 7-day TTL forces eventual refresh against drifted news.

---

## Calibration evidence

See [`docs/backtest_results.md`](backtest_results.md) for the live-LLM evaluation snapshot
and the semantic invariants enforced by `tests/test_live_evals.py`. The in-pipeline validator
already guarantees factor shocks stay inside the empirical envelope; the live evals add
mechanism-level smoke checks (pandemic → pandemic-tagged analog selected; banking crisis →
XLF beats SPY to the downside; Taiwan scenario → semis appear in periphery).

---

## What this is NOT

- **Not a regulatory stress engine.** No Basel SA/IMA, no FRTB, no CCAR/DFAST. The phrase
  "scenario explorer" is deliberate to avoid the regulatory-stress framing.
- **Not real-time risk.** Designed for one-shot scenario evaluation, not live position
  monitoring.
- **Not multi-asset.** Equity-only in v1; fixed income, FX, and commodities are deferred.
- **Not deterministic in narrative wording.** Shocks are reproducible by cache hash;
  narrative text varies slightly across runs even at `temperature=0`.
- **Not investment advice.** Period.

---

## Where things live

- Engine math: `app/factors/{universe,regression,shocks,analogs}.py`
- LLM pipeline: `app/llm/{schemas,prompts,grounding,validation,gemini_client,scenario}.py`
- Caching: `app/data/cache.py` (GCS parquet + JSON), `app/utils/hashing.py`
- Sample portfolios: `app/data/sample_portfolios.py`
- UI: `app/ui/{portfolio,scenario,results,methodology}_tab.py`, `app/main.py`

For implementation conventions, see [`CLAUDE.md`](../CLAUDE.md).
