# Methodology

> ⚠️ **Educational/research tool only.** Outputs are hypothetical modeled stress
> outcomes, not forecasts, investment advice, or regulatory stress testing. Do not
> use for actual trading or capital allocation decisions.

---

## What nami does

A user describes a hypothetical market stress in natural language ("60% US tariffs on
China imports, prolonged trade war"). nami:

1. Asks Gemini to pick 2–5 **historical analog events** from a curated registry whose
   *mechanism* matches the scenario.
2. Pulls the **realized factor returns** over each analog's window from yfinance and
   computes an **empirical envelope** (mean / p10 / p90 / count) per factor.
3. Asks Gemini to write a **grounded hypothetical stress narrative** about the scenario (Google Search active
   → real news citations) and then, in a separate sub-call, **extract structured factor
   shocks + periphery shocks** that stay inside the empirical envelope.
4. Estimates the portfolio's **factor betas** via mean-centered ridge OLS on 3 years of
   weekly returns, applies the shocks, and returns a portfolio P&L with attribution.

Every market-context claim in the narrative is **cited** to a real source the LLM
retrieved during grounding. Without citations the pipeline refuses to return.

---

## Portfolio construction

**Holdings & weights.** A portfolio is a set of equity (or yfinance-supported) tickers with
weights summing to 1.0. The four sample books are **cap-weighted** — `weightᵢ = marketCapᵢ / Σ
marketCap` — from a **frozen, dated snapshot** (`app/data/sample_portfolio_weights.json`),
regenerated offline by `scripts/refresh_sample_weights.py`. Cap-weighting is a deliberate
approximation of true free-float index weights: it is reproducible, requires no paid feed, and
is a large step up in realism from equal-weighting (a developed-world book is ~10% Apple, not
2% of everything). The runtime **never scrapes** — drifting weights would silently change P&L
and poison the scenario cache — so refreshing the snapshot is an explicit, reviewable step.
Each book is asserted single-currency before weighting (the developed-world proxy uses US-listed
ADR lines so it is all-USD; the Japan book is all-JPY), because cap ratios are only meaningful
within one quote currency.

**Benchmark & active return.** Each book carries a benchmark ticker (sample books built-in —
MSCI World→URTH, US Tech→QQQ, Defensive→SPLV, Japan→EWJ; custom books optional). The benchmark
is evaluated as a **one-holding portfolio** run through the *same* factor shocks the scenario
produced, giving a benchmark return; **active return = portfolio return − benchmark return**.
This is computed as a post-pipeline overlay (never cached) so it always reflects the book's
current benchmark, and it shares the engine's linearity caveat — it is a *factor-model* estimate
of relative performance under the shock, not a realized tracking result.

**Sector & country exposure.** Each ticker carries a sector and country tag (baked into the
snapshot from yfinance classification). Exposure breakdowns sum portfolio weight and scenario
P&L contribution within each bucket. These are coarse Yahoo classifications (≈ GICS-lite), not
licensed GICS, and are display-only — they do not enter the factor model.

**Cash sleeve.** A reserved `CASH` line is a **zero-exposure** position: zero factor beta, zero
scenario return, no periphery shock. Its weight dilutes the rest of the book (cash drag) but it
never contributes to P&L and is never fetched from market data. In mark-to-market mode a `CASH`
quantity is a **USD amount** (marked at 1.0), not a share count. An all-cash book is rejected —
there is nothing to shock.

**Out of scope (v1).** Cost-basis / tax-lot accounting, multi-currency *reporting*, long/short
net-gross, blended benchmarks, and non-equity asset classes are intentionally excluded — they
require paid data or accounting machinery beyond an equity scenario explorer.

---

## Factor universe (22 factors)

All factors are tickers fetched via yfinance; each weekly "return" is the percent change in
the factor's adjusted-close price. These are **tradeable-ETF proxies** for systematic risk
factors, chosen for liquidity and observability rather than the canonical Fama-French
portfolio-sort construction ([Fama & French, 1993](https://www.sciencedirect.com/science/article/abs/pii/0304405X93900235);
[Fama & French, 2015](https://www.sciencedirect.com/science/article/abs/pii/S0304405X14002323);
the momentum style factor MTUM follows the [Carhart, 1997](https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.1997.tb03808.x)
construction at the ETF level).

| group | factors |
|---|---|
| **Market** (2) | US large-cap equities (`SPY`), Global equities (`ACWI`) |
| **Sectors** (11 GICS) | US technology (`XLK`), US financials (`XLF`), US energy (`XLE`), US health care (`XLV`), US industrials (`XLI`), US consumer discretionary (`XLY`), US consumer staples (`XLP`), US utilities (`XLU`), US materials (`XLB`), US real estate (`XLRE`), US communication services (`XLC`) |
| **Styles** (5 MSCI) | Momentum stocks (`MTUM`), Quality stocks (`QUAL`), Value stocks (`VLUE`), Small-cap tilt (`SIZE`), Low-volatility stocks (`USMV`) |
| **Macro** (4) | US 10Y yield (`TNX`, yfinance `^TNX`), US dollar (`DXY`, yfinance `DX-Y.NYB`), Equity volatility (`VIX`, yfinance `^VIX`), Oil price (`OIL`, yfinance `CL=F`) |

The app renders factors as `Human label (TICKER)` wherever space allows, while the
internal keys and model math stay ticker-based. Unit convention: percent change of the weekly close. For macro indices that means percent
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
  between SPY/ACWI/XLK and between sector ETFs ([Hoerl & Kennard, 1970](https://doi.org/10.1080/00401706.1970.10488634)).
- Mean-centering removes the through-origin bias when returns have nonzero historical
  means (equivalent to including an unpenalized intercept and discarding it). Why it
  works: the normal equations for `[X, 1] @ [beta; mu]` decouple — the intercept row
  gives `mu = mean(Y) - beta^T mean(X)`, and substituting back recovers the centered
  system. Mean-centering keeps the ridge penalty away from the intercept; penalizing
  the intercept would shrink portfolio alphas toward zero, which is a substantive
  modeling choice we don't want the regularizer to make.
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
- Factor shocks outside `[p10, p90]` **when `count >= 3`**. Below that threshold the
  band collapses (count=1: a single point; count=2: a 2-point span) and rejection on
  floating-point divergence between the LLM's emitted value and the envelope is
  unjustifiable, so the band check is skipped. The LLM is still shown the envelope in
  the prompt and is separately instructed to "down-weight factors with `count < 3`" —
  that prompt guidance remains the only constraint at low count.

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
independently to the total. Phase 8 added Conditional Shapley variants; Shapley redistributes credit *within* the factor
channel only, never across the factor/periphery boundary.

**Constraint**: periphery shocks may only reference tickers present in the portfolio.
Enforced at three layers: the shock extraction prompt instructs the LLM to limit periphery
to held tickers; `validate_shock_proposal` rejects violations; `portfolio_pnl` itself
raises `ValueError` for unknown tickers as a belt-and-braces check. Rationale: an
idiosyncratic shock to a ticker you don't hold has zero weight and therefore zero P&L
impact — accepting it silently would mislead users into thinking their portfolio has
exposure to that name.

---

## Factor attribution: production view and diagnostics

The app computes four attribution maps internally, but it no longer presents them as
equal choices. The main workbench uses the practical hedge-fund split:

| Surface | Backing field | Purpose |
|---|---|---|
| **Scenario shocks** | `by_factor_conditional_shapley_explicit` | Production risk view. Only factors explicitly shocked by the scenario receive factor attribution. |
| **Grouped shocks** | `by_factor_conditional_shapley_grouped` | Risk-committee view. Market / sector / style / macro groups collapse correlated-peer leakage. |
| **Naive algebra** | `by_factor_naive` | Advanced audit/debug view. Direct formula, assumes factor independence. |
| **Full conditional diagnostic** | `by_factor_conditional_shapley` | Advanced quant diagnostic. Correlation credit under the full historical joint distribution; non-causal. |

The impact summary and top-driver readout default to **Scenario shocks** whenever that
map is available. Full conditional diagnostic never drives the headline.

### Production risk view

Scenario shocks answer the operational question: "Given the factors explicitly shocked
by the stress narrative, what drove modeled P&L?" This matches how a PM or risk manager
usually reads a scenario. If the scenario did not explicitly shock `Global equities
(ACWI)`, then `Global equities (ACWI)` does not appear as a production driver.

The direct algebra underneath the model is still:

```text
by_factor_naive[f] = (sum_i weight_i * beta_i,f) * shock[f]
```

The production Shapley view restricts the player set to the explicitly shocked factors,
so unshocked factors stay exactly zero while the result still sums to the factor-driven
P&L under nami's demeaned-background contract.

### Grouped risk view

Grouped shocks are the secondary presentation view. The engine first computes the full
conditional game, sums credit within the four factor groups, then redistributes each
group's value to members by their within-group naive share. This preserves efficiency
while avoiding noisy peer leakage such as `US large-cap equities (SPY)` to `Global
equities (ACWI)` or `Momentum stocks (MTUM)` to `Quality stocks (QUAL)`.

### Advanced diagnostics

Naive algebra and full conditional diagnostic are useful for model validation, not for
the main risk story. Full conditional diagnostic uses SHAP's `LinearExplainer` with a
`maskers.Impute` background ([Lundberg & Lee, 2017](https://proceedings.neurips.cc/paper/2017/hash/8a20a8621978632d76c43dfd28b67767-Abstract.html)).
It is data-dependent credit allocation under the historical conditional distribution
of factor returns, not a causal decomposition. A factor with no explicit shock can
receive positive or negative credit because it is correlated with shocked factors.

That behavior follows the observational-feature framing discussed by
[Aas, Jullum, Loland (2021)](https://doi.org/10.1016/j.artint.2021.103502),
[Janzing, Minorics, Blobaum (2020)](https://proceedings.mlr.press/v108/janzing20a.html),
and [Chen, Janizek, Lundberg, Lee (2020)](https://arxiv.org/abs/2006.16234). It is
valid as a diagnostic, but it is basis-sensitive and should not be narrated as "the
scenario shocked this factor."

### ACWI example

In an AI-bubble crash, `Global equities (ACWI)` would usually be expected to move
negative as a direct broad-equity shock. If the **Full conditional diagnostic** shows
positive `Global equities (ACWI)` contribution, that is not a claim that global
equities rallied in the scenario. It means ACWI received correlation credit because
other overlapping factors such as `US large-cap equities (SPY)`, `US technology (XLK)`,
`Momentum stocks (MTUM)`, or `Quality stocks (QUAL)` were shocked. The production
view remains **Scenario shocks**.

### Worked example

Two factors, correlation = 0.9, only F0 explicitly shocked:

| View | F0 shocked -5% | F1 no explicit shock |
|---|---|---|
| Naive algebra | Full direct credit | 0 |
| Scenario shocks | Shapley credit within shocked set | 0 |
| Full conditional diagnostic | Partial credit | Partial correlation credit |

All maps can sum to the same factor-driven P&L, but they answer different questions.
For user-facing scenario interpretation, start with **Scenario shocks**, then use
**Grouped shocks** for committee-style reporting. Use the advanced diagnostics only to
audit the math or investigate correlation leakage.

---

## Risk diagnostics

`ScenarioResult.risk_diagnostics` is an optional warning list. It is deterministic
post-processing, not an LLM judgment and not a shock rewrite. Old cached or saved
results deserialize with an empty list.

V1 diagnostics flag review points when:

- Highly positively correlated factors receive opposite-signed material explicit shocks.
- Highly negatively correlated factors receive same-signed material explicit shocks.
- An explicit shock materially conflicts with the selected analog envelope mean.
- The full conditional diagnostic assigns material correlation credit to an unshocked factor.

Each warning includes factor labels plus tickers, the relevant correlation or envelope
statistic, and a short review message. The correct response is human review or a rerun
with clearer stress text, not an automatic sign hack or post-hoc clamp.

---

## Fixed-context shock attribution (narrative decomposition)

The opt-in "Run decomposition" action splits the scenario text into N ∈ {2, 3, 4}
self-contained sub-narratives and assigns each its exact Shapley value over the payoff
`v(S) = total_pnl(run_scenario(" ".join(S)))`, with `v(∅) := 0`.

**Fixed context.** Each subset run **pins the source scenario's analog set** and uses the
**analog-only narrative path (no Google re-grounding)** — so the only thing that varies
across subsets is the shock proposal for that fragment's text. This makes `v(S)`
deterministic and reproducible (modulo temperature + cache), versus the earlier design
that re-selected analogs and re-grounded per subset (noisy, news-dependent).

**What it measures — and doesn't.** This is *decomposition sensitivity*: the marginal
shock each theme adds **within the original analog context**. It is NOT a causal
decomposition (a fragment in isolation may still propose different shocks than it does in
context). The UI and this caption label it "experimental / illustrative" for that reason.
When a portfolio value is set, each contribution is also shown in dollars
(`shapley_value · NAV`).

**UX + cost.** Served over SSE (`/api/scenarios/decompose-stream`) so the UI shows
"X / Y subset runs". Cost: `2^N − 1` runs (empty subset is the hardcoded zero) — N=4 is
15 runs (~30–90s, ≈ $0.015). N is capped at 4 (N=5 = 31 runs, too long for a synchronous UX).

Both Shapley sums (factor-level and narrative-level) satisfy the **efficiency axiom**
exactly (modulo float noise); pinning analogs + skipping re-grounding removes the
news-drift variance the narrative-level sum previously carried.

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

## Mark-to-market valuation

By default nami works in **return space**: a portfolio is a set of weights and P&L is a percentage. There are two ways to see dollars:

- **Notional dollar view** (any run, including visitors): apply a **portfolio value (NAV)** as a post-run control. Because the engine is linear, every dollar figure is just `field × NAV`, recomputed **instantly in the browser** as you change the value — no re-run, no marking. Nothing is "marked"; it is a notional scaling of the weights. Per-position value here is `weight · NAV`.
- **Mark-to-market** (admin, share quantities): enter **share counts** and nami marks each position to the as-of close + FX (below), deriving an authoritative NAV and price-derived weights.

Both surface the same **original → stressed** view: `stressed_value = value + NAV·by_ticker_total[t]`, `stressed_NAV = NAV·(1 + total_pnl)`, and per-name `Δ% = delta / value` (the position's scenario return).

**Marking (share-quantity mode).** For each holding nami fetches the **raw** (un-split/dividend-adjusted) daily close on the as-of date — a dedicated fetch, distinct from the adjusted-close series used for return modelling, because valuing a share count needs the actual traded price. Each position is converted to USD:

```
position_value_usd[i] = shares[i] · raw_close[i] · pence_scale[i] · fx_to_usd[ccy(i)]
NAV                    = Σ position_value_usd[i]
weight[i]              = position_value_usd[i] / NAV        (price-derived; drifts from any target)
```

The quote currency is inferred from the Yahoo exchange suffix (e.g. `.T` → JPY; `.L` → GBP quoted in **pence**, so the price is divided by 100; no suffix → USD). FX uses explicit, direction-checked pairs (e.g. `USDJPY=X` inverted to USD-per-JPY) marked on the **same as-of date**, and the per-instrument close date and per-currency FX date are recorded.

**Dollars are a linear overlay.** Because the factor engine is linear in weights, the entire dollar view is the return-space result scaled by NAV — no separate dollar P&L is computed or stored:

```
total $ P&L         = total_pnl · NAV
position $ P&L[i]   = by_ticker_total[i] · NAV          (the weight cancels exactly)
post-shock value[i] = position_value_usd[i] + by_ticker_total[i] · NAV
```

**Vintage consistency.** A backdated MTM run marks at the as-of date's raw close and the as-of FX rate, so the valuation carries no look-ahead — consistent with the rest of the backdating contract.

**Fail-closed.** If any requested position cannot be marked (missing, stale, delisted) or an FX rate is unavailable, the run **fails with an error** rather than silently returning a percentage-only result — a requested valuation is never quietly degraded.

**Caching.** The scenario cache stores the **return-space** result only; NAV, marks, and FX are recomputed after retrieval and never persisted, so the same scenario at a different NAV can never serve stale dollars. The share-quantity *inputs* are cached (they are deterministic and part of the cache key) so a cache hit or a shock adjustment can re-mark.

**Limitations (v1).** USD reporting only; long positions only (no shorts); no cost basis or realised/unrealised split; currency is suffix-inferred (not security-master-grade); portfolio snapshots store weights, not share counts. The analog envelope and factor shocks are unaffected by MTM — it is a valuation layer over the same scenario engine.

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
- API: `app/api/main.py`
- UI: `frontend/src/` (React + TypeScript + Plotly.js)

For implementation conventions, see [`CLAUDE.md`](../CLAUDE.md).

---

## References

The following sources ground the attribution methodology, the factor-model conventions,
and the ridge-regression choice. Where a verified DOI / arXiv / publisher page is
available it is linked; otherwise the entry cites by name and venue and a maintainer can
swap in a verified link.

- **Shapley, L. S. (1953).** *A value for n-person games.* In Kuhn & Tucker (eds.),
  *Contributions to the Theory of Games II* (pp. 307–317). Princeton University Press.
  Reprint: <https://www.degruyter.com/document/doi/10.1515/9781400881970-018/html>.
  Origin of the Shapley value and the four axioms (efficiency, symmetry, linearity,
  null player) the engine uses for factor-level credit allocation.
- **Hoerl, A. E., & Kennard, R. W. (1970).** *Ridge regression: Biased estimation for
  nonorthogonal problems.* *Technometrics* 12(1), 55–67.
  DOI: [10.1080/00401706.1970.10488634](https://doi.org/10.1080/00401706.1970.10488634).
  Foundation of the ridge regularization the beta-estimation step relies on.
- **Fama, E. F., & French, K. R. (1993).** *Common risk factors in the returns on
  stocks and bonds.* *Journal of Financial Economics* 33(1), 3–56.
  <https://www.sciencedirect.com/science/article/abs/pii/0304405X93900235>.
- **Carhart, M. M. (1997).** *On persistence in mutual fund performance.*
  *Journal of Finance* 52(1), 57–82.
  <https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.1997.tb03808.x>.
- **Fama, E. F., & French, K. R. (2015).** *A five-factor asset pricing model.*
  *Journal of Financial Economics* 116(1), 1–22.
  <https://www.sciencedirect.com/science/article/abs/pii/S0304405X14002323>.
- **Lundberg, S. M., & Lee, S.-I. (2017).** *A unified approach to interpreting model
  predictions.* In *Advances in Neural Information Processing Systems 30 (NeurIPS)*.
  <https://proceedings.neurips.cc/paper/2017/hash/8a20a8621978632d76c43dfd28b67767-Abstract.html>.
  Foundational SHAP paper; introduces `LinearExplainer` and the exact computation for
  linear models that nami's `conditional_shapley_attribution` builds on.
- **Janzing, D., Minorics, L., & Blöbaum, P. (2020).** *Feature relevance quantification
  in explainable AI: A causal problem.* In *AISTATS, PMLR 108*.
  <https://proceedings.mlr.press/v108/janzing20a.html>. Frames the observational
  (conditional) vs interventional Shapley choice as a *modeling decision*, not a
  universal correctness claim — the load-bearing citation for nami's "Conditional
  Shapley ≠ causal attribution" disclaimer.
- **Sundararajan, M., & Najmi, A. (2020).** *The many Shapley values for model
  explanation.* In *ICML, PMLR 119*.
  <https://proceedings.mlr.press/v119/sundararajan20b.html>. Taxonomy of Shapley
  operationalizations relevant to the four-variants choice.
- **Frye, C., Rowat, C., & Feige, I. (2020).** *Asymmetric Shapley values: Incorporating
  causal knowledge into model-agnostic explainability.* In *NeurIPS 33*.
  <https://proceedings.neurips.cc/paper/2020/hash/0d770c496aa3da6d2c3f2bd19e7b9d6b-Abstract.html>.
  Related but distinct from nami's grouped variant.
- **Owen, G. (1977).** *Values of games with a priori unions.* In Henn & Moeschlin
  (eds.), *Mathematical Economics and Game Theory*. Springer.
  <https://link.springer.com/chapter/10.1007/978-3-642-45494-3_7>. Coalition-structure
  values; the lineage for "group-aware" credit allocations. nami's grouped variant is a
  full-Shapley-then-redistribute design, NOT Owen's recursive coalition value.
- **Aas, K., Jullum, M., & Løland, A. (2021).** *Explaining individual predictions when
  features are dependent: More accurate approximations to Shapley values.*
  *Artificial Intelligence* 298, 103502.
  DOI: [10.1016/j.artint.2021.103502](https://doi.org/10.1016/j.artint.2021.103502).
  Motivates dependent-feature SHAP approximations (which nami's `maskers.Impute` use).
- **Chen, H., Janizek, J. D., Lundberg, S., & Lee, S.-I. (2020).** *True to the model
  or true to the data?* arXiv:[2006.16234](https://arxiv.org/abs/2006.16234).
  Develops the observational-vs-interventional choice as a modeling question in depth;
  complements Janzing et al. (2020).
