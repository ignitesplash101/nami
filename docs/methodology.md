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
- Factor shocks outside `[p10, p90]` — the validator checks all factors regardless of
  count. When `p10` or `p90` is NaN (happens naturally when `count < 2`, since quantile
  is degenerate on 0–1 values), the check is skipped.
- The shock extraction prompt separately instructs the LLM to "down-weight factors with
  `count < 3`" — this is **advisory guidance to the model**, not a hard code constraint.
  The validator enforces the envelope band; the LLM decides how aggressively to use
  low-count factors within it.

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

**Constraint**: periphery shocks may only reference tickers present in the portfolio.
Enforced at three layers: the shock extraction prompt instructs the LLM to limit periphery
to held tickers; `validate_shock_proposal` rejects violations; `portfolio_pnl` itself
raises `ValueError` for unknown tickers as a belt-and-braces check. Rationale: an
idiosyncratic shock to a ticker you don't hold has zero weight and therefore zero P&L
impact — accepting it silently would mislead users into thinking their portfolio has
exposure to that name.

---

## Factor attribution: Naive vs Conditional Shapley

The engine returns **two** per-factor attribution dictionaries on every scenario:
`by_factor_naive` (always) and `by_factor_conditional_shapley` (when the historical
factor-return background is available). The Results-tab toggle picks which one to
render.

### Why naive attribution misleads under correlation

Naive attribution is the direct algebra:

```
by_factor_naive[f] = (Σᵢ wᵢ · βᵢ,f) · shock[f]
```

This sums exactly to the factor-driven P&L and is dead simple to interpret — but it
**assumes factor independence**. In practice SPY and ACWI move together (ρ ≈ 0.95),
XLK is essentially SPY plus a tech-tilt, and sector ETFs co-move during stress. If
the LLM shocks SPY while leaving ACWI unshocked, naive attribution gives ACWI exactly
zero credit even though ACWI is what the SPY shock *implies* about global equities.
Conversely, two near-identical factors that are both shocked can have their credit
arbitrarily split based on which factor the LLM happened to name first.

### Conditional Shapley axioms

Shapley values are the unique axiom-compliant credit allocation among:
- **Efficiency** — `Σ_f shapley[f] == factor-driven P&L`
- **Symmetry** — factors with identical marginal effect get equal credit
- **Linearity** — composing two games linearly composes the Shapley values
- **Null player** — a factor with zero coefficient gets zero credit

### What Conditional Shapley is NOT

**It is not a causal "true" attribution.** Conditional Shapley is *data-dependent
credit allocation under the historical conditional joint distribution* of factor
returns. A factor with zero explicit LLM shock can receive nonzero Conditional
Shapley credit because it is correlated with one that *was* shocked — the model's
prediction at the conditional expectation differs from the prediction at the
marginal expectation. This is the price of axiomatic credit allocation, not a bug,
but it does mean Conditional Shapley should be read as "how much of the move is
*explained by* factor f under the historical co-movement structure" rather than "how
much would change if we toggled f in isolation."

The UI surfaces this honestly: rows labelled "No explicit LLM shock; attributed via
correlation" show up only under Conditional Shapley, for factors the LLM didn't name
but which received Shapley credit through correlation.

### Implementation

`app/factors/attribution.py::conditional_shapley_attribution` uses the
non-deprecated `shap` API:

```python
masker    = shap.maskers.Impute(background)
explainer = shap.LinearExplainer((aggregated_coefs, 0.0), masker)
shap_values = explainer.shap_values(shock_vec)
```

where `aggregated_coefs = (weights @ betas)` collapses the N × F beta matrix into the
portfolio-level F-vector of factor exposures. The background is the demeaned,
dropna'd historical weekly factor-return matrix supplied by
`fetch_factor_returns_history` (≥52 complete rows required — `RuntimeError` otherwise).
The 52-row floor is one year of weekly observations — the minimum for the 22-factor
covariance matrix to be well-conditioned. With fewer rows, the sample covariance is
rank-deficient or noise-dominated, and the `Impute` masker's conditional expectations
become numerically unreliable. In practice the strict `dropna(how='any')` across all
22 factors yields 300+ surviving rows (post-XLC 2018+), well above the floor.

**Critical:** the background must NOT be `fillna(0)`'d. Zero-filling a missing ETF's
returns manufactures false zero-correlation that contaminates the Shapley values.
Strict dropna across all 22 factors effectively restricts the background to the
post-XLC-launch window (mid-2018+); this is correct — older windows can't carry the
modern factor universe's correlation structure.

### Worked example

Two factors, ρ = 0.9, only F0 explicitly shocked:

| | F0 (shocked −5%) | F1 (no shock) |
|---|---|---|
| Naive | −5% × β = full credit | exactly 0 |
| Conditional Shapley | ~−2.5% credit | ~−2.5% credit (via correlation) |

Both attributions sum to the same factor-driven P&L. Conditional Shapley distributes
the credit across the correlated peer.

### When to use which

- **Naive** for quick intuition when factors are roughly independent or when the
  reader needs to see exactly which factors the LLM named.
- **Conditional Shapley** for axiom-compliant attribution when factors are known to
  be correlated — i.e. most of the time in equities. Default when available.

### Variants: full, explicit-only, grouped

Conditional Shapley ships in three flavors. All three are computed best-effort
whenever a sufficient factor-return background is available; the API/UI surfaces
all three under `PortfolioPnL.by_factor_conditional_shapley*` fields and the
frontend picks which to render.

| Variant | Players in the Shapley game | Sums to | When to read |
|---|---|---|---|
| **Full** (`by_factor_conditional_shapley`) | All F factors in the universe | Factor-driven P&L (efficiency axiom) | "How would credit flow under the full historical joint distribution?" |
| **Explicit-only** (`by_factor_conditional_shapley_explicit`) | Only the factors the LLM explicitly shocked; unshocked factors stay at exactly 0.0 | A sub-game total ≤ factor-driven P&L | "Restrict attribution to factors the model actually named." Matches the user's mental model when reading "what did the LLM shock?" |
| **Grouped** (`by_factor_conditional_shapley_grouped`) | G=4 factor groups (market / sector / style / macro); within-group credit redistributed to members by naive weight | Factor-driven P&L (efficiency preserved) | "Collapse within-group leakage (SPY ↔ ACWI, MTUM ↔ QUAL) and only Shapley-allocate cross-group correlation." |

**Within-group aggregation**: `conditional_shapley_attribution_grouped` aggregates
member returns and shocks within each group by **SUM**, not average. Sum preserves
`Σ aggregated_shock = Σ raw_shock` and so preserves the efficiency property at the
factor level. Average would distort correlation structure for groups with many
members and would break efficiency unless rescaled.

**Redistribution within a group**: each group's Shapley value is split among its
members proportionally to `(wᵀβ)_f · shock[f]` — the naive within-group share. The
practical effect: a group's credit lands on the factor the LLM actually shocked, not
on its correlated peers. If all member shocks are 0, the group's value (also
typically ~0) is split uniformly across members for transparency.

**Zero-group detail**: when no member of a group was explicitly shocked, `total_naive`
for that group is exactly 0.0 and the naive-share denominator would divide by zero. The
code falls back to `phi_f = phi_group / |group|` (uniform split). In practice `phi_group`
is near-zero for an all-unshocked group — the full Shapley game attributes most credit to
groups whose members were shocked — but it can be nonzero when cross-group correlation is
high. The uniform fallback is a transparency choice, not a mathematical necessity.

**Why explicit-only exists.** The full variant is mathematically clean but reads
strangely to users: a SPY-only shock can produce a noticeable ACWI/QUAL contribution
because `shap.maskers.Impute` measures the marginal effect of an *omitted* factor
against the conditional expectation given the shocked ones. With SPY/XLK/MTUM
heavily negative, the conditional expectation of ACWI/QUAL is also negative, so a
zero shock is "better than expected" and earns positive offsetting attribution.
That's correct under the axiomatic credit-allocation framing — but a user reading
"the model attributed P&L to a factor I didn't shock" sees a bug. Explicit-only is
the variant that matches the user's mental model.

**Why grouped exists.** The 21-factor view spreads correlated-peer leakage across
many factors (SPY/ACWI/XLK/MTUM/QUAL all moving together swamps the cross-group
signal). The grouped view collapses within-group leakage into naive and
Shapley-allocates only cross-group correlation, which is the more interesting
signal for a portfolio P&L story.

### Worked example: end-to-end with all four variants

A concrete walkthrough using 3 factors (SPY, XLK, VIX) and a 2-ticker portfolio
(AAPL 60%, MSFT 40%). All numbers below were generated by running the actual
`estimate_betas`, `apply_shocks`, and attribution functions on synthetic 60-week data
with known correlation structure (SPY/XLK ρ ≈ 0.84, SPY/VIX ρ ≈ −0.47).

**Step 1 — Beta estimation** (mean-centered ridge OLS, α = 0.1):

```
              SPY      XLK       VIX
  AAPL     0.2232   0.2910   -0.1550
  MSFT     0.1701   0.2252   -0.1498
```

Betas are ridge-shrunk from true generating values (SPY/XLK multicollinearity
shares load across the two) — this is expected behavior, not a defect.

**Step 2 — LLM shocks**: SPY = −5%, XLK = −8%, VIX = +40%

**Step 3 — Per-ticker expected return** (`β @ shock_vec`):

```
  AAPL: 0.2232 × (−0.05) + 0.2910 × (−0.08) + (−0.1550) × (+0.40) = −9.64%
  MSFT: 0.1701 × (−0.05) + 0.2252 × (−0.08) + (−0.1498) × (+0.40) = −8.64%
```

**Step 4 — Periphery**: AAPL gets −3% idiosyncratic (earnings miss); MSFT gets 0%.

**Step 5 — Portfolio P&L**:

```
  Ticker  Weight   Factor  Periphery    Total  Weighted
  AAPL     60%    −9.64%    −3.00%    −12.64%   −7.59%
  MSFT     40%    −8.64%     0.00%     −8.64%   −3.46%
  ──────────────────────────────────────────────────────
  Factor-driven P&L:  −9.24%
  Periphery P&L:      −1.80%
  Total portfolio:   −11.04%
```

**Step 6 — Naive attribution** (`(Σᵢ wᵢ · βᵢ,f) · shock[f]`):

```
  SPY:  (0.6 × 0.2232 + 0.4 × 0.1701) × (−0.05) = 0.2020 × (−0.05) = −1.010%
  XLK:  (0.6 × 0.2910 + 0.4 × 0.2252) × (−0.08) = 0.2647 × (−0.08) = −2.117%
  VIX:  (0.6 × −0.1550 + 0.4 × −0.1498) × (+0.40) = −0.1529 × (+0.40) = −6.115%
  Sum = −9.243% ✓ (matches factor-driven P&L)
```

VIX dominates because its shock is large (+40%) and the portfolio has meaningful
negative VIX betas (VIX up → equity down).

**Step 7 — All four attribution variants compared**:

| Factor | Naive | Full Conditional | Explicit-only | Grouped |
|---|---|---|---|---|
| SPY | −1.010% | −0.441% | −0.553% | −0.426% |
| XLK | −2.117% | −1.653% | −1.578% | −1.573% |
| VIX | −6.115% | −7.148% | −7.111% | −7.244% |
| **Sum** | **−9.243%** | **−9.243%** | **−9.243%** | **−9.243%** |

Observations:
- **Efficiency**: all four variants sum to the same −9.243% factor-driven P&L.
  (Explicit-only also sums to factor P&L here because all 3 factors are shocked; when
  some factors are unshocked, its sum ≤ factor P&L.)
- **SPY vs XLK redistribution**: under Naive, SPY gets −1.01% and XLK gets −2.12%.
  Under Conditional Shapley, SPY drops to −0.44% because its effect is partially
  captured by its correlated peer XLK. The credit isn't lost — it's redistributed.
- **VIX absorbs more**: Conditional Shapley pushes VIX from −6.12% to −7.15%. VIX is
  inversely correlated with SPY/XLK, so its Shapley value exceeds its naive share.

**Step 8 — What happens when VIX is unshocked** (same SPY/XLK shocks):

| Factor | Naive | Full Conditional | Explicit-only |
|---|---|---|---|
| SPY | −1.010% | −1.445% | −1.118% |
| XLK | −2.117% | −2.173% | −2.010% |
| VIX | 0.000% | **+0.491%** | **0.000%** |
| **Sum** | **−3.127%** | **−3.127%** | **−3.127%** |

This is where the variants diverge meaningfully:
- **Naive** gives VIX exactly 0 — it was not shocked.
- **Full Conditional** gives VIX **+0.49%** (positive!) — because SPY/XLK are down,
  the conditional expectation of VIX is *up*; a zero VIX shock is "better than the
  model expected," so VIX earns positive offsetting credit.
- **Explicit-only** keeps VIX at exactly 0 — it restricts the Shapley game to
  {SPY, XLK} only. This matches the user's mental model: "I didn't shock VIX, so
  VIX shouldn't appear in my attribution."

### Choosing the right attribution method

| Question | Naive | Full Conditional | Explicit-only | Grouped |
|---|---|---|---|---|
| **What does it show?** | Credit proportional to `(wᵀβ)_f · shock[f]` | Axiom-compliant credit under historical co-movement | Shapley restricted to LLM-shocked factors; unshocked = 0 | Cross-group Shapley + within-group naive redistribution |
| **Sums to factor P&L?** | Yes (exact) | Yes (efficiency axiom) | No (sub-game ≤ factor P&L) | Yes (efficiency preserved) |
| **Unshocked factor credit?** | Always zero | Can be nonzero via correlation | Always zero | Zero within-group; possible via cross-group correlation |
| **Best when...** | Quick sanity check; factors roughly independent | Axiom-compliant full allocation; correlated equities | User wants attribution only on factors the LLM named | Suppress within-group leakage (SPY ↔ ACWI, MTUM ↔ QUAL) |
| **Confusing when...** | Correlated factors split credit arbitrarily | Credit appears on factors nobody shocked | Gap between sub-game total and factor P&L is large | Group definitions feel arbitrary |

**Rule of thumb**: start with **Grouped** for presentation-quality factor stories — it
collapses the noisy within-group leakage that makes full Conditional hard to narrate.
Use **Naive** for a fast sanity check or when the audience needs to see exactly which
factors the LLM proposed. Use **Full Conditional** when you need every cent accounted
for under the historical joint distribution. Use **Explicit-only** when the audience
objects to seeing credit on factors the model didn't name.

---

## Experimental: narrative decomposition

The opt-in "Also compute experimental narrative decomposition" checkbox in the
Scenario tab triggers a different kind of Shapley analysis: it splits the scenario
text itself into N ∈ {2, 3, 4} self-contained sub-narratives, re-runs the **full
pipeline** on each of the 2^N subset combinations, and assigns each sub-narrative its
exact Shapley value over the pipeline payoff function `v(S) = total_pnl(run_scenario(
" ".join(S)))`.

The empty-subset payoff is hardcoded to `v(∅) := 0` — no narrative → no pipeline run
→ no P&L move. This is defensible but not the only choice; documented here so an
advanced reader doesn't expect a market-drift baseline.

**Framing**: this is *counterfactual pipeline attribution*, NOT a clean causal
decomposition. Each subset reruns analog selection + grounded narrative + shock
extraction, so the values reflect pipeline behavior on the subset, not a true causal
contribution of the named sub-narrative. The UI label and methodology caption both say
"experimental" for that reason.

Cost: `2^N − 1` full scenario runs (the empty subset is the hardcoded zero). For N=4
that's 15 runs ≈ $0.015 and ~3-4 min sequential wall-clock. N is capped at 4 because
N=5 takes 31 runs and ~8 min — too long for a synchronous request/response UX.

Both Shapley sums (factor-level and narrative-level) satisfy the **efficiency axiom**
exactly modulo float-point noise (factor) or float-point + LLM-variance drift
(narrative). The methodology doc and UI both flag narrative-level drift as expected.

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
- API: `app/api/main.py`
- UI: `frontend/src/` (React + TypeScript + Plotly.js)

For implementation conventions, see [`CLAUDE.md`](../CLAUDE.md).
