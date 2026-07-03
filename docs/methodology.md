# Methodology

> ⚠️ **Educational/research tool only.** Outputs are hypothetical modeled stress
> outcomes, not forecasts, investment advice, or regulatory stress testing. Do not
> use for actual trading or capital allocation decisions.

---

## What nami does

A user describes a hypothetical market stress in natural language ("60% US tariffs on
China imports, prolonged trade war"). nami:

1. Asks Gemini to pick 2–5 **historical analog events** from a curated registry whose
   *mechanism* matches the scenario (the 2–5 cardinality is enforced in code — an
   out-of-range selection fails the run with a 422).
2. Pulls the **realized factor returns** over each analog's window from yfinance and
   computes an **empirical envelope** (mean / p10 / p90 / count) per factor, plus the
   per-event return rows behind it.
3. Asks Gemini to write a **grounded hypothetical stress narrative** about the scenario (Google Search active
   → real news citations) and then, in a separate sub-call, **extract structured factor
   shocks** (validated against the empirical envelope for factors with `count >= 3`)
   plus **periphery shocks** (idiosyncratic; hard-banded to ±0.75, no envelope).
4. Estimates the portfolio's **factor betas** via standardized (unit-variance) ridge OLS
   on 3 years of weekly returns, applies the shocks, and returns a portfolio P&L with
   attribution and per-name regression fit quality.

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

## Book profile (free, engine-only)

"What am I holding?" should not cost an LLM call. The **book profile** runs the exact market
path a scenario would — weekly adjusted closes, USD conversion for non-USD listings, the same
cash-aware standardized ridge — and stops before any narrative work. It reports:

- **Portfolio factor exposures**: the portfolio-level beta per factor, `Σᵢ wᵢ·βᵢ,f`. This is
  precisely the number a factor shock is multiplied by in a scenario (`contribution =
  exposure × shock`), so the profile doubles as a preview of where scenario P&L would come from.
- **Per-name fit quality**: weight, adjusted R², weeks of usable history, and weekly
  idiosyncratic vol for every holding — the same `regression_quality` surfaced after a run,
  available before one.
- **The 1-week ±1σ idio dispersion floor**: `√(Σᵢ (wᵢ·σᵢ,idio)²)` — the same independence-based
  floor as the post-run band, at the one-week horizon (a scenario's band is scaled to the
  median selected-analog horizon instead).

The profile is computed fresh on every request (nothing cached beyond the market-data layers),
is available to visitors on sample books (admins may profile custom weight books), and involves
zero Gemini calls — it is rate-limited like the paid endpoints only because it fans out to the
market-data provider.

---

## Factor universe (26 factors)

All factors are tickers fetched via yfinance; each weekly "return" is the percent change in
the factor's adjusted-close price. These are **tradeable-ETF proxies** for systematic risk
factors, chosen for liquidity and observability rather than the canonical Fama-French
portfolio-sort construction ([Fama & French, 1993](https://www.sciencedirect.com/science/article/abs/pii/0304405X93900235);
[Fama & French, 2015](https://www.sciencedirect.com/science/article/abs/pii/S0304405X14002323);
the momentum style factor MTUM follows the [Carhart, 1997](https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.1997.tb03808.x)
construction at the ETF level).

| group | factors |
|---|---|
| **Market** (3) | US large-cap equities (`SPY`), Global equities (`ACWI`), Developed ex-US equities (`EFA`) |
| **Sectors** (11 GICS) | US technology (`XLK`), US financials (`XLF`), US energy (`XLE`), US health care (`XLV`), US industrials (`XLI`), US consumer discretionary (`XLY`), US consumer staples (`XLP`), US utilities (`XLU`), US materials (`XLB`), US real estate (`XLRE`), US communication services (`XLC`) |
| **Styles** (5 MSCI) | Momentum stocks (`MTUM`), Quality stocks (`QUAL`), Value stocks (`VLUE`), Small-cap tilt (`SIZE`), Low-volatility stocks (`USMV`) |
| **Macro** (7) | US 10Y yield (`TNX`, yfinance `^TNX`), US dollar (`DXY`, yfinance `DX-Y.NYB`), Equity volatility (`VIX`, yfinance `^VIX`), Oil price (`OIL`, yfinance `CL=F`), High-yield credit (`HYG`), Gold (`GLD`), Short-duration Treasuries (`SHY`) |

The app renders factors as `Human label (TICKER)` wherever space allows, while the
internal keys and model math stay ticker-based. Unit convention: decimal price returns
for equity factors and for the ETF-based macro factors (`HYG`/`GLD`/`SHY`); decimal
change in the *level* for the index-based macro factors (`TNX`/`DXY`/`VIX`/`OIL` — so a
VIX shock of `+0.50` = the VIX index spiking by 50%, e.g. 15 → 22.5). Betas are estimated
on weekly returns while shocks are episode total moves — see the "Shock horizon and
units" section for the full contract. The full description per factor is in
[`app/factors/universe.py`](../app/factors/universe.py). The Phase-22 additions close
the review's coverage gaps: `HYG` is the credit-stress lever (the registry is
banking/credit-heavy), `GLD` the flight-to-quality leg, `SHY` the front-end-rates lever,
and `EFA` gives non-US developed equities their own dimension — on the replay harness,
adding `EFA` cut the Japan book's bias from +2.2% to +0.7% and its MAE from 5.9% to 5.1%.

**Pre-launch dates** matter for the analog matcher — events before a factor's ETF launch
return NaN for that factor and are excluded from its envelope count:

| factor | first available |
|---|---|
| Style ETFs (MTUM/QUAL/VLUE/SIZE/USMV) | 2013 |
| XLRE | 2015 |
| XLC | 2018 |
| ACWI | mid-2008 |
| HYG | Apr 2007 |
| GLD | Nov 2004 |
| SHY | Jul 2002 |
| EFA | Aug 2001 |

---

## Beta estimation

`app/factors/regression.py::estimate_betas_and_stats` runs **standardized
(unit-variance) ridge OLS** on weekly returns:

```
X̃ = X − mean(X, axis=0)             # T × F factor returns, centered
Ỹ = Y − mean(Y, axis=0)             # T × N ticker returns, centered
σ̂ = std(X̃, axis=0, ddof=1)         # per-factor weekly vol
β̂_std = solve((X̃/σ̂)ᵀ(X̃/σ̂) + αI, (X̃/σ̂)ᵀỸ)
β̂ = β̂_std / σ̂                      # rescaled to RAW units — β̂ · raw_shock is unchanged in meaning
```

- Default lookback: 156 weeks (3 years) per `Config.beta_lookback_weeks`.
- Default ridge `α = 0.1` per `Config.ridge_alpha` — stabilizes against the collinearity
  between SPY/ACWI/XLK and between sector ETFs ([Hoerl & Kennard, 1970](https://doi.org/10.1080/00401706.1970.10488634)).
- **Why standardize:** in standardized units every factor column's Gram diagonal is
  `T − 1 ≈ 155`, so `α = 0.1` shrinks each eigendirection by `λ/(λ + 0.1)` — near-zero
  bias on well-identified directions and a meaningful floor only on near-degenerate
  (collinear) ones. Without standardization the same `α` in raw weekly-return² units
  shrank low-vol equity-factor directions ~50% while barely touching high-vol macro
  factors like VIX — heterogeneous shrinkage that depended silently on each factor's
  variance. Coefficients are rescaled back to raw units after the solve, so the output
  betas apply to raw decimal shocks exactly as before.
- Mean-centering removes the through-origin bias when returns have nonzero historical
  means (equivalent to including an unpenalized intercept and discarding it). Why it
  works: the normal equations for `[X, 1] @ [beta; mu]` decouple — the intercept row
  gives `mu = mean(Y) - beta^T mean(X)`, and substituting back recovers the centered
  system. Mean-centering keeps the ridge penalty away from the intercept; penalizing
  the intercept would shrink portfolio alphas toward zero, which is a substantive
  modeling choice we don't want the regularizer to make.
- **Per-ticker masks + history floor:** rows where any *factor* is NaN drop globally,
  then each ticker is regressed on its own non-NaN weeks (grouped by identical mask
  pattern, one vectorized solve per group) — one short-history holding no longer
  truncates the estimation window for the whole book. Every ticker needs at least
  **40 non-NaN weeks** (`MIN_REGRESSION_WEEKS`) or the run fails with a 422 naming the
  offending ticker(s).
- **Fit quality is reported, not hidden.** Each result carries per-ticker
  `regression_quality`: in-sample `r2` (clipped to [0, 1]), `n_obs` (weeks surviving the
  mask), and `idio_vol_weekly` (ddof=1 weekly residual vol, not annualized). Names with
  `r2 < 0.30` get a warning diagnostic — the factor model explains little of their
  variance, so factor-implied scenario P&L likely understates their true risk.
- **Effective dof, adjusted R², and beta SEs (Phase 21).** With 26 regressors on as few
  as 40 weeks, in-sample R² is flattered exactly where the fit is weakest. The solver
  therefore also reports the ridge **effective degrees of freedom**
  `p_eff = Σ s/(s+α)` over the standardized Gram's eigenvalues, a **dof-honest
  adjusted R²** `1 − (1−R²)(n−1)/(n−p_eff−1)` (can be negative — worse than the mean),
  and per-factor **standard errors** from the ridge sandwich
  `σ̂²·A⁻¹GA⁻¹` on `n − p_eff − 1` residual dof (matching OLS-with-intercept SEs
  exactly as α → 0; verified against statsmodels). `r2_adj` and `p_eff` are persisted
  with the result; names with fewer than **3 observations per effective parameter**
  get a `low_regression_dof` warning.
- **Why α stays 0.1 (dated decision record, 2026-07-02).** A sweep of
  `α ∈ {0.1, 2, 8, 32}` over the LLM-free engine-replay harness (48 event×book pairs;
  see [Calibration evidence](#calibration-evidence)) showed tracking error is flat
  between 0.1 and 2 (MAE 3.97% vs 3.90%) and degrades monotonically beyond
  (MAE 4.26% at α=8, 5.03% at α=32, with bias worsening from −2.1% to −2.8%): this
  ridge shrinks toward **zero**, so heavier shrinkage systematically understates
  betas — the exact bias a stress engine must avoid. Under-determined fits are
  handled by *disclosure* (adjusted R², `p_eff`, the low-dof diagnostic) rather than
  by blanket shrinkage; shrinkage toward informative targets (market/sector priors,
  not zero) was subsequently evaluated and rejected — see the stressed-beta record
  below (2026-07-03).
- **Why betas stay unconditional — no downside weighting, no informative-target
  shrinkage (dated decision record, 2026-07-03).** The stressed-beta experiment ran
  both proposed variants against the engine-replay harness (124 pairs, 85 computed,
  identical pair set across every run; see
  [Calibration evidence](#calibration-evidence)), with the production estimator
  re-run the same day as the baseline (MAE 3.25%, bias −1.40%, sign 92.9%,
  r 0.976). **Downside-weighted WLS** (stress week = bottom-decile SPY week within
  the vintage window; stress rows weighted k×) degraded every aggregate
  monotonically in k: MAE 3.39% / 3.50% / 3.66% / 4.18% and bias −1.55% / −1.64% /
  −1.76% / −2.11% at k = 2 / 3 / 5 / 25, with r falling 0.976 → 0.955. Per book it
  traded a small Japan bias gain (+0.73% → −0.12% at k = 3) for degradation
  everywhere else (Japan MAE 5.14% → 5.86%; both US-heavy books worse on bias AND
  MAE) — the "betas blow up in stress" hypothesis does not survive contact with
  realized event returns through this estimator. **Informative-target ridge**
  (prior β = 1 on SPY — EFA for `.T` listings — via `min ‖y−Xb‖² + α‖b−b0‖²`) is a
  no-op at the production α = 0.1 and a noise-level wash at α = 2 (overall MAE
  3.23%, but three of four books worse on MAE, Japan bias worse at +0.83%, sign
  and r both slightly down); from α = 8 it degrades outright — informative targets
  do not rescue heavier shrinkage. No cell met the standing adoption bar
  (bias/MAE improvement without correlation degradation, robust per book), so the
  estimator stays `ridge-std-v2`, α = 0.1, unconditionally weighted and
  zero-targeted. Analog-window-only estimation was not separately implemented: it
  is the k→∞ limit of the WLS family, whose gradient is monotonically harmful.
  Revisit only with new harness evidence.
- **Currency:** non-USD listings (e.g. the Japan book's `.T` tickers) have their weekly
  returns converted to USD (`(1 + r_local)(1 + r_FX) − 1`, vintage-correct FX series)
  *before* the regression, so betas absorb FX exposure and active return vs a USD-quoted
  benchmark compares like with like.
- Uses `np.linalg.solve` instead of `inv` — more numerically stable, and vectorizes
  cleanly across tickers within each mask group.

The unit tests recover known coefficients within 0.05 of truth using a near-zero test
ridge (`α = 0.001`) so shrinkage bias does not dominate the tolerance; the production
default `α = 0.1` deliberately trades a small (now homogeneous) shrinkage bias for
collinearity stability. A dedicated column-scale-invariance test pins the
standardize-then-rescale property.

---

## Historical analog matcher

`app/factors/analogs.py` loads a curated registry of 31 historical market-stress events
from [`data/historical_events.yaml`](../data/historical_events.yaml), spanning 2007–2025.
Each event has:

- `id` — stable kebab-case identifier (e.g. `covid-crash-2020`)
- `start_date`, `end_date` — daily-precision window (inclusive on both ends)
- `tags` — subset of `{trade-war, pandemic, inflation, geopolitical, banking, energy, central-bank, currency, technology, volatility, credit, disaster}`
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

## Shock horizon and units

**A shock is an episode total return, not a weekly return.** Every factor shock the LLM
proposes — and every envelope statistic it is constrained by — is the cumulative decimal
change of that factor over the full hypothetical stress episode:
`price[end] / price[start] − 1` over an analog event's exact-day window. The selected
analogs set the implied horizon; registry windows range from 5 calendar days (the 2024
yen-carry unwind) to ~7.5 months (the 2014–15 oil crash), and two windows are deliberate
RECOVERY episodes (GFC trough 2009, COVID liquidity 2020). The extraction prompt states
this contract explicitly and shows the model each analog's **per-event factor returns and
window length**, not just the aggregated band — so it can reason about duration and see
which analog drives each band edge.

**Betas are weekly; shocks are episode-level — a deliberate horizon-invariance
assumption.** Betas are estimated on 156 weekly returns and applied linearly to
episode-horizon shocks. A linear factor model has no compounding, so this is exact only
if betas are horizon-invariant; empirically betas drift across horizons, and the linear
approximation of a geometric path understates compounding as |shock| grows (two −10%
weeks compound to −19%, not −20%). For the magnitudes the envelope permits this error is
second-order, but it grows with shock size — one reason outputs are illustrative, not
forecasts. A modeled name-level loss can mathematically breach −100% of the position;
nami never clamps (linearity is the engine contract behind attribution sums and the
client-side dollar view) — instead a `position_loss_exceeds_100pct` warning diagnostic
flags it.

**The envelope mixes window lengths by design.** It is an empirical distribution of
*episode* moves across mechanically similar analogs, not a fixed-horizon return
distribution. The p10–p90 band therefore blends short crashes and multi-month episodes;
the per-event table shows which analog drives each band edge. With only 2–5 events the
percentiles are linear interpolations over a handful of points — which is why the band
check is enforced only at `count >= 3` and why adjustments to lower-count factors are
restricted to keep-or-remove.

**Macro factors are level changes.** VIX, TNX, DXY, and OIL shocks are decimal changes
in the index level. They are level-dependent: +0.50 on VIX means 12 → 18 in a calm
regime but 35 → 52.5 in a stressed one. The %-change convention is kept deliberately —
it normalizes across volatility regimes, which is what makes a 2008 analog comparable to
a 2024 one inside a single envelope — at the cost that a shock does not pin an absolute
level.

**Periphery shocks are idiosyncratic episode returns with a hard band, not an
envelope.** They have no historical envelope; the validator enforces `|shock| <= 0.75`
(a single-episode idiosyncratic move beyond ±75% on top of factor effects is outside
this tool's plausible-stress scope, and anything ≤ −1.0 is economically impossible for a
long position), and a warning diagnostic flags `|shock| > 0.35` plus any name whose P&L
is dominated by its periphery shock rather than the factor model.

**Japan book currency handling.** Tokyo-listed (`.T`) weekly returns are converted to
USD (`(1 + r_local)(1 + r_FX) − 1`, using the as-of-consistent USDJPY series) before
beta estimation, so betas absorb FX exposure and active return vs the USD-quoted EWJ
benchmark compares like with like. Remaining limitation: Tokyo and US weekly bars close
at different times, so cross-market betas are attenuated by non-synchronous trading;
nami does not apply a lead/lag correction.

**Why no Dimson lag (dated decision record, 2026-07-02).** A lead/lag (Dimson-style
summed-beta) correction was evaluated against the engine-replay harness before
implementation. The attenuation hypothesis predicts the Japan book systematically
UNDERSTATES realized event moves; the harness showed the opposite sign — Japan bias was
**+2.2%** (overstatement) on the 22-factor baseline while all three US books sat at
−2.4% to −4.3% — so a correction that raises Japan's betas would have made its error
worse. Adding the `EFA` factor instead (a proper developed-ex-US dimension) cut Japan's
bias to +0.7% and its MAE from 5.9% to 5.1%. Revisit only if a future harness snapshot
shows the attenuation signature.

---

## Analog replay

Every scenario result carries a per-analog **replay range**: each selected analog
event's REALIZED factor returns (the same per-event rows that build the envelope) are
pushed through the run's betas —

    replay_pnl(e) = Σ_t w_t · Σ_f β_{t,f} · r_{e,f}

— answering *"if this scenario plays out like that analog did, what does this book's
factor model say?"* (`app/factors/shocks.py::analog_replay_pnl`, surfaced as
`ScenarioResult.analog_replay` and rendered directly under the Impact summary as
min / median / max plus one row per analog).

Three properties make the replay range the honest companion to the headline number:

- **No zero-holes.** The LLM's scenario shocks cover only the factors it names —
  unshocked factors enter the P&L at exactly zero. A realized event vector has no such
  holes: every factor's actual co-move is included (NaN only where an ETF predates the
  window; those contribute zero and the per-event coverage count, e.g. `20/26 factors`,
  discloses it).
- **No severity cap.** Proposed shocks are validated into the analog envelope's
  `[p10, p90]` band; the replay range shows each analog's FULL realized severity. A
  scenario whose banded shocks sit well inside its own replay range is visibly milder
  than its own evidence base.
- **Deterministic and LLM-free.** Replay is linear algebra over already-fetched data.
  It is cached with the canonical result (like `regression_quality`) and preserved
  byte-for-byte through shock adjustments; older cached/saved results simply omit it.

Replay is **factor-only**: it excludes periphery (single-name) shocks and idiosyncratic
effects, and it applies the run's current-vintage betas to a historical episode (beta
drift is part of the message, not a bug). It is a historical replay, not a forecast.

---

## Event replay screen (all events, free)

The per-result analog replay generalizes to the **full registry** as a free pre-scenario
screen: every historical event's realized factor returns pushed through the **current
book's** betas — the identical `analog_replay_pnl` math — sorted worst-first, with each
event's window length and factor coverage disclosed (a 2000 event covers fewer of the 26
factors than a 2020 one; NaN holes contribute zero and are excluded from the coverage
count). "Which historical episodes hurt this book most, through today's factor structure?"
answered with zero LLM calls, before any paid run.

The same honesty framing as the per-result strip applies, plus one distinction worth
naming: this screen uses **current** betas on historical windows (the question is about
today's book), whereas the engine-replay validation harness uses **vintage** betas (its
question is about engine accuracy). Factor-model only, no idiosyncratic or periphery
effects — a severity screen, not a backtest and not a forecast. Operationally, the
events × factors return matrix is cached in-process per registry version: historical
windows never change, and deep-vintage batches cannot live in the market-data cache
(pre-launch ETFs make them incomplete batches, which are never cached), so recomputing
the matrix on every request would re-fire dozens of live provider downloads.

---

## Idiosyncratic dispersion band

The headline P&L is a factor-driven point estimate; the same regression that produces
the betas also measures what the factor model does NOT explain — each name's weekly
residual vol. Every result now carries a **±1σ idiosyncratic dispersion band**
(`ScenarioResult.pnl_uncertainty`, rendered next to the Portfolio P&L metric):

    band = √( Σᵢ (wᵢ · σᵢ,idio)² ) · √h

where `σᵢ,idio` is the per-name weekly residual vol and `h` is the episode horizon in
weeks — the **median selected-analog window length**, so the dispersion is scaled to
the same implied horizon as the shocks themselves.

Two independence assumptions do real work here and both bias the band DOWN: residuals
are treated as uncorrelated across names (sector co-movement the 26-factor model
misses is ignored) and across weeks (stress autocorrelation is ignored). Read the band
as a **floor on dispersion around the point estimate, not a confidence interval on the
scenario** — the scenario itself (which analogs, which shocks) carries far more
uncertainty than the residual term, which is why the analog replay range above sits
next to it. The band is shock-independent (residual vols + analog windows only), is
cached with the canonical result, and is recomputed to the identical value on shock
adjustments. Periphery shocks are deterministic inputs, not draws from this residual
distribution; the band brackets the total either way.

---

## LLM pipeline

`app/llm/scenario.run_scenario` orchestrates two Gemini calls + one structured extraction.

### Call 1 — Analog selection (`select_analogs`)
- Input: scenario text + `event_summaries()` (JSON of all 31 events)
- No grounding tool, structured-output schema `AnalogSelectionOutput`
- Output: 2–5 event IDs the LLM thinks share the scenario's *mechanism*. The 2–5
  cardinality is enforced post-hoc in `run_scenario` (it also covers the
  pinned-decomposition path, which bypasses the LLM); out-of-range selections fail
  with a 422.

### Call 2a — Grounded narrative (`_grounded_narrative`)
- Input: scenario + envelope + factor universe + holdings
- **Google Search tool ON**, NO `response_schema` (free-form text)
- Output: 3-5 sentence narrative citing recent market news

### Call 2b — Structured extraction (`_extract_structured_shocks`)
- Input: the grounded narrative from 2a + envelope + **per-event factor returns with
  window lengths** + factor universe + holdings. The prompt defines the shock contract
  explicitly: a shock is the cumulative total move over the episode, not a weekly
  return, and the reasoning field cannot authorize an out-of-band value.
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
- Periphery shocks that are non-finite or outside the hard band `|shock| <= 0.75`
  (an advisory diagnostic separately flags `|shock| > 0.35`)
- Factor shocks outside `[p10, p90]` **when `count >= 3`**. Below that threshold the
  band collapses (count=1: a single point; count=2: a 2-point span) and rejection on
  floating-point divergence between the LLM's emitted value and the envelope is
  unjustifiable, so the band check is skipped. The LLM is still shown the envelope and
  the per-event rows in the prompt and is separately instructed to "down-weight factors
  with `count < 3`" — that prompt guidance remains the only constraint at low count on
  the proposal side.

On validation failure, 2b is re-asked once with the errors embedded in the user message.
A second failure raises — every validator string is blocking, not advisory.

### Iterative adjustment validation
Shock *adjustments* (sliders or LLM patch) are validated by the stricter
`app/llm/adjust_validation.validate_factor_overrides`: an override must be inside
`[p10, p90]`, or exactly `0.0` (the removal sentinel — always accepted), and for
low-evidence factors (`count < 3`, where the band is interpolation-shaped) the only
valid moves are **keep the canonical shock or remove it** — no re-tuning without
evidence. The UI disables those sliders; the server-side rule binds direct API calls
and LLM patches identically.

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

In the waterfall, zero or visually-zero non-material periphery is omitted rather
than shown as a `0.00%` bridge. Small but visible non-material periphery remains a
single net `Periphery` bridge. When gross idiosyncratic contribution is material,
the UI shows the largest ticker-level periphery contributors as signed bars and
rolls the rest into `Other periphery`, even if offsetting names make the net
contribution near zero. This prevents offsetting name shocks from disappearing
behind a near-zero net bar. The name-level table and CSV export always retain the
full per-ticker factor / periphery / total split.

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
| **Group totals** | `by_factor_conditional_shapley_grouped` summed by factor group | Risk-committee view. Waterfall bars show true Market / Sector / Style / Macro totals; the factor table keeps factor-level detail. |
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

Group totals are the secondary presentation view. The engine first computes the full
conditional game, sums credit within the four factor groups, then redistributes each
group's value to members by their within-group naive share. The UI then sums that
factor-level grouped map back into true `Market`, `Sector`, `Style`, and `Macro`
waterfall bars, while the factor table keeps the redistributed factor detail for drilldown.
This preserves efficiency while avoiding noisy peer leakage such as `US large-cap
equities (SPY)` to `Global equities (ACWI)` or `Momentum stocks (MTUM)` to `Quality
stocks (QUAL)`.

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
**Group totals** for committee-style reporting. Use the advanced diagnostics only to
audit the math or investigate correlation leakage.

---

## Risk diagnostics

`ScenarioResult.risk_diagnostics` is an optional warning list. It is deterministic
post-processing, not an LLM judgment and not a shock rewrite. Old cached or saved
results deserialize with an empty list.

Diagnostics flag review points when:

- Highly positively correlated factors receive opposite-signed material explicit shocks.
- Highly negatively correlated factors receive same-signed material explicit shocks.
- An explicit shock materially conflicts with the selected analog envelope mean.
- The full conditional diagnostic assigns material correlation credit to an unshocked factor.
- A name's regression `r2 < 0.30` — the factor model explains little of its weekly
  variance, so factor-implied P&L likely understates that name's scenario risk.
- A name's modeled scenario return breaches **−100% of the position** — the linear
  engine never clamps below −100%; linearity is the engine contract, so the breach is
  flagged honestly instead of being hidden by a floor.
- A periphery shock exceeds the ±35% advisory tier (the ±75% hard band is enforced by
  the validator, not here).
- A name's modeled P&L is dominated by its periphery shock rather than the factor
  model (the factor attribution views do not explain that name's result).
- **(Phase 21) Band coverage** — K of the N material factor shocks have NO enforced
  evidence band (envelope `count < 3`), so their magnitudes are LLM judgment rather
  than analog-anchored (info when a minority, warning when more than half).
- **(Phase 21) Scenario vs replay** — the scenario's total P&L lands OUTSIDE the
  selected analogs' replayed severity range (milder than every analog, or harsher
  than every analog). Threshold-free: the bounds are the scenario's own evidence base.
- **(Phase 21) Low regression dof** — a name has fewer than ~3 observations per ridge
  effective parameter (`(n−1)/(p_eff+1) < 3`); its betas are weakly determined and its
  in-sample R² flattered.

Each warning includes the relevant tickers/factors, the statistic that fired, and a
short review message. The correct response is human review or a rerun with clearer
stress text, not an automatic sign hack or post-hoc clamp.

---

## Fixed-context theme sensitivity (narrative Shapley)

The opt-in "Run theme sensitivity" action splits the scenario text into N ∈ {2, 3, 4}
self-contained sub-narratives and assigns each its exact Shapley value over the payoff
`v(S) = total_pnl(run_scenario(" ".join(S)))`, with `v(∅) := 0`.

**Fixed context.** Each subset run **pins the source scenario's analog set** and uses the
**analog-only narrative path (no Google re-grounding)** — so the only thing that varies
across subsets is the shock proposal for that fragment's text. This makes `v(S)`
deterministic and reproducible (modulo temperature + cache), versus the earlier design
that re-selected analogs and re-grounded per subset (noisy, news-dependent).

**What it measures — and doesn't.** This is *theme sensitivity*: the marginal
shock each theme adds **within the original analog context**. It is NOT a causal
decomposition or risk-factor attribution (a fragment in isolation may still propose
different shocks than it does in context). The UI and this caption label it
"experimental / illustrative" for that reason.
When a portfolio value is set, each contribution is also shown in dollars
(`shapley_value · NAV`).

**UX + cost.** Served over SSE (`/api/scenarios/decompose-stream`) so the UI shows
"X / Y subset runs". Cost: `2^N − 1` runs (empty subset is the hardcoded zero) — N=4 is
15 runs (~30–90s, ≈ $0.015). N is capped at 4 (N=5 = 31 runs, too long for a synchronous UX).

Both Shapley sums (factor-level and theme-level) satisfy the **efficiency axiom**
exactly (modulo float noise); pinning analogs + skipping re-grounding removes the
news-drift variance the theme-sensitivity sum previously carried.

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
  + regression_spec                # estimator id|lookback|alpha|min_obs — engine-math lever
  + position_quantities            # only when present (MTM share counts)
  + pinned_event_ids               # only when present (fixed-context theme-sensitivity subsets)
  ```
- TTL = 7 days (`LLM_CACHE_TTL_DAYS`) on cache reads.
- Cache backend: `CloudStorageCache` (GCS, prefix `scenario_cache/`), JSON serialized via
  `ScenarioResult.model_dump(mode="json")`. Tests inject `InMemoryCache` instead.

`PROMPT_VERSION` is the invalidation lever for prompt/schema semantics; the
`regression_spec` component is the lever for engine math — changing the estimator,
`RIDGE_ALPHA`, or `BETA_LOOKBACK_WEEKS` produces new keys automatically, so stale P&L is
never served after a regression change. Same-day re-runs of an unchanged scenario hit
cache in <500ms; the 7-day TTL forces eventual refresh against drifted news.

---

## Mark-to-market valuation

By default nami works in **return space**: a portfolio is a set of weights and P&L is a percentage. There are two ways to see dollars:

- **Notional dollar view** (any run, including visitors): apply a **portfolio value (NAV)** as a post-run control. Because the engine is linear, every dollar figure is just `field × NAV`, recomputed **instantly in the browser** as you change the value — no re-run, no marking. Nothing is "marked"; it is a notional scaling of the weights. Per-position value here is `weight · NAV`.
- **Mark-to-market** (admin, share quantities): enter **share counts** and nami marks each position to the as-of close + FX (below), deriving an authoritative NAV and price-derived weights.

Both surface the same **original → stressed** view: `stressed_value = value + NAV·by_ticker_total[t]`, `stressed_NAV = NAV·(1 + total_pnl)`, and per-name `Δ% = delta / value` (the position's scenario return).

**Marking (share-quantity mode).** For each holding nami fetches the **last valid raw** (un-split/dividend-adjusted) daily close **on or before the as-of date** — rejected as stale if more than 7 calendar days older (`MAX_STALENESS_DAYS`) — a dedicated fetch, distinct from the adjusted-close series used for return modelling, because valuing a share count needs the actual traded price. Each position is converted to USD:

```
position_value_usd[i] = shares[i] · raw_close[i] · pence_scale[i] · fx_to_usd[ccy(i)]
NAV                    = Σ position_value_usd[i]
weight[i]              = position_value_usd[i] / NAV        (price-derived; drifts from any target)
```

The quote currency is inferred from the Yahoo exchange suffix (e.g. `.T` → JPY; `.L` → GBP quoted in **pence**, so the price is divided by 100; no suffix → USD; an **unknown** suffix falls back to USD with a logged warning — currency inference is the one non-fail-closed input). FX uses explicit, direction-checked pairs (e.g. `USDJPY=X` inverted to USD-per-JPY) marked at the **last valid close on or before the as-of date** (same 7-day staleness rule), and the per-instrument close date and per-currency FX date are recorded independently.

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
guarantees factor shocks stay inside the empirical envelope **for factors with envelope
`count >= 3`** (below that the band is degenerate and unenforced) and hard-bands periphery
shocks to ±0.75; the live evals add mechanism-level smoke checks (pandemic →
pandemic-tagged analog selected; banking crisis → XLF beats SPY to the downside; Taiwan
scenario → semis appear in periphery).

**Engine-level tracking** is measured separately by the LLM-free replay harness
(`app/factors/engine_replay.py`): for every (registry event × sample book) pair it
estimates vintage betas as of the event start, pushes the event's realized factor
returns through them, and compares against the book's realized buy-and-hold USD return
over the same window. The regenerated snapshot — summary MAE / bias / sign hit-rate /
Pearson r plus every per-pair row and skip reason — lives in
[`docs/engine-replay-validation.md`](engine-replay-validation.md)
(`uv run python scripts/run_engine_replay.py` to refresh). Read together with
[`docs/backdated-case-studies.md`](backdated-case-studies.md), it decomposes full-run
error into its two layers: how much comes from the linear engine itself versus from the
severity of the LLM-proposed, envelope-banded shocks.

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
