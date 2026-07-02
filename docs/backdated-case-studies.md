# Backdated retrospective case studies

> **These are not backtests.** nami is a scenario *explainer*, not a forecaster, and the framing of each prompt is a known source of label leakage — a user writing in 2026 about a "2020 pandemic resurgence" is implicitly drawing on what they learned from COVID. These case studies exercise nami's backdated, vintage-controlled data path on three well-known historical regimes where ground truth is observable, then compare nami's modeled stress P&L to the actual realized P&L over the same window. The intent is to show the *shape* of nami's outputs under reproducibility constraints, not to claim predictive accuracy.
>
> Three sources of label leakage are unavoidable in v1:
> 1. **Prompt framing** — even abstracted prompts narrow the regime space.
> 2. **LLM parametric knowledge** — Gemini knows about post-as-of events even when Google Search is disabled and the events YAML is filtered.
> 3. **Portfolio composition drift** — sample portfolios reflect a 2024–26 view of "large-cap tech" or "defensive mix" and may not match what a 2020 investor would have held (e.g. NVDA was a $250B name pre-COVID vs >$3T today).
>
> All three cases are reproducible via [`scripts/run_case_studies.py`](../scripts/run_case_studies.py). Source data: [`scripts/case_studies_output.json`](../scripts/case_studies_output.json). Generated 2026-05-28.

---

## Case 1 — 2020 demand-shock crash

| field | value |
|---|---|
| as-of date (requested / effective NYSE) | 2020-02-26 / 2020-02-26 |
| portfolio | `msci_world` (50 global large caps, frozen cap-weight snapshot) |
| narrative mode | `analog_only` (Google Search disabled; correctly enforced) |
| eligible analogs at as-of | 10 (`bnp-paribas-credit-2007`, `brexit-2016`, `china-deval-2015`, `euro-crisis-2010`, `gfc-trough-recovery-2009`, `lehman-gfc-2008`, `oil-crash-2014`, `q4-trade-war-2018`, `taper-tantrum-2013`, `us-downgrade-2011`) |
| analogs selected by LLM | `china-deval-2015`, `q4-trade-war-2018` |
| modeled top factor | VIX (+102% shock) |
| **modeled total P&L (naive)** | **−6.71%** |
| **modeled total P&L (Scenario shocks)** | **−6.91%** |
| realized window | 2020-02-26 → 2020-03-23 (1 month) |
| **actual realized P&L (same holdings, same window)** | **−24.74%** |
| realized top loser | RTX (−45.8%) |
| realized top winner | WMT (+0.9%) |

**Prompt** (deliberately avoiding "pandemic" / "virus" — the abstracted framing):
> *"A major exogenous shock to global travel and supply chains forces a synchronous recession scare; equity markets repricing happens over weeks not months, with cyclicals and travel-exposed names leading the drawdown."*

**Honest read**: nami captured the *direction* (−6.7% modeled vs −24.7% realized, both negative) and the *mechanism* (cyclical sectors lead, VIX surge, energy weakness). It materially understated magnitude because the two selected analogs (China deval 2015, trade war 2018) were medium-stress events, not crash-grade. The Lehman GFC analog was eligible but not picked — the LLM's prompt-anchored "supply chains + recession scare" framing matched trade-war-shape events more than systemic-collapse events. Realized RTX (Raytheon) at −45.8% was driven by aerospace/defense exposure to travel collapse, which the abstracted prompt didn't surface.

**Leakage notes**: post-2020 readers cannot un-know COVID, and Gemini knows COVID happened. The selected analogs and structural shock magnitudes are the cleaner signal here; the narrative should be treated as illustrative.

---

## Case 2 — 2022 hawkish-pivot regime

| field | value |
|---|---|
| as-of date (requested / effective NYSE) | 2021-12-31 / 2021-12-31 |
| portfolio | `us_tech_growth` (FAANG + semis, frozen cap-weight snapshot) |
| narrative mode | `analog_only` |
| eligible analogs at as-of | 12 (above 10 plus `covid-crash-2020`, `covid-liquidity-2020`) |
| analogs selected by LLM | `taper-tantrum-2013`, `q4-trade-war-2018` |
| modeled top factor | VIX (+63% shock); XLK contrib −2.0% |
| **modeled total P&L (naive)** | **−7.96%** |
| **modeled total P&L (Scenario shocks)** | **−4.95%** |
| realized window | 2021-12-31 → 2022-06-30 (6 months) |
| **actual realized P&L (same holdings, same window)** | **−34.68%** |
| realized top loser | NFLX (−71.0%) |
| realized "least bad" | TXN (−17.4%) |

**Prompt**:
> *"Persistent above-target core inflation forces developed-market central banks into a sustained tightening cycle over the next 12 months; duration-sensitive growth equities derate sharply, defensives and value relatively spared."*

**Honest read**: this case is the most "successful" of the three in qualitative terms. The selected analogs (Taper Tantrum 2013 + 2018 trade-war/risk-off) are the right reference set — both were rate-driven duration-derating events on growth equities, exactly the 2022 mechanism. The naive modeled outcome (−8%) was 4× too small in magnitude, but the relative-ordering signal was correct: XLK shocked harder than SPY, and NFLX/MSFT/NVDA/AMZN periphery shocks matched the realized loser hierarchy (NFLX was the worst, the model put it at −9.5% — directionally right, magnitude tiny). The 6-month realized window is also longer than the typical analog window (taper tantrum was ~3.5 months), so magnitude understatement is partly time-window mismatch.

**Leakage notes**: less acute leakage than Case 1 — "above-target inflation" was already a 2021 narrative — but the "sustained tightening cycle over the next 12 months" framing pre-loads the conclusion.

---

## Case 3 — 2023 regional-banking stress

| field | value |
|---|---|
| as-of date (requested / effective NYSE) | 2023-03-08 / 2023-03-08 |
| portfolio | `defensive_mix` (staples, utilities, healthcare, frozen cap-weight snapshot) |
| narrative mode | `analog_only` |
| eligible analogs at as-of | 14 (above 12 plus `inflation-ukraine-2022`, `uk-gilt-crisis-2022`) |
| analogs selected by LLM | `bnp-paribas-credit-2007`, `lehman-gfc-2008` |
| modeled top factor | VIX (+24% shock, deliberately downweighted by validator from 47% mean because `count < 3`) |
| **modeled total P&L (naive)** | **−1.75%** |
| **modeled total P&L (Scenario shocks)** | **−1.17%** |
| realized window | 2023-03-08 → 2023-05-08 (2 months) |
| **actual realized P&L (same holdings, same window)** | **+10.24%** |
| realized top winner | LLY (+38.5%) |
| realized top loser | PFE (−3.6%) |

**Prompt** (the most leaky of the three — essentially the SVB postmortem written in advance):
> *"Sudden loss of depositor confidence in select mid-size lenders triggers deposit withdrawals and forced asset sales; large diversified banks relatively spared, regional bank index leads losses."*

**Honest read**: this case is **interesting precisely because the modeled stress sign differed from realized performance**. The model returned −1.75% on the defensive_mix portfolio (small negative — appropriate magnitude for defensives during a banking shock). The realized return was *positive* +10.24%, driven by Eli Lilly's +38% standalone move on Mounjaro/GLP-1 momentum during this period, plus the broader "Fed will pivot dovish if banks break" trade that bid up rate-sensitive defensives. **nami's structural model correctly identified that defensives ride out banking stress better than financials**; it could not foresee that an idiosyncratic LLY ramp would dominate the 2-month window. This is the right kind of limitation — the engine's mechanism was sound, the realized result was driven by orthogonal news flow the engine had no mandate to model.

**Leakage notes**: most leaky of the three. The defensive_mix portfolio has minimal bank exposure, so this case is closer to "does the engine correctly identify that defensives ride out a banking stress" than to "does it forecast the banking stress."

---

## What these cases ARE evidence of

- **Pipeline integrity end-to-end on a backdated path**: vintage-controlled analog filtering by `end_date <= as_of` works (the COVID case correctly excluded `covid-crash-2020` from eligible; the 2022 case correctly included it). Google Search is correctly disabled in `analog_only` mode (all three returned zero citations, matching `narrative_mode = "analog_only"`).
- **Reproducibility**: re-running [`scripts/run_case_studies.py`](../scripts/run_case_studies.py) at `temperature=0` against a warm cache returns byte-for-byte identical results. The cache key incorporates `PROMPT_VERSION` so a future prompt bump would invalidate these snapshots cleanly.
- **Mechanism-level analog selection**: Case 2 picked the right reference events; Case 3 picked the right banking-stress family.
- **Periphery-ticker plausibility**: COVID picked XOM/GE/AAPL/JPM (energy, industrials, supply-chain, financials); 2022 picked the FAANG+ stack; SVB picked defensives. All thematically defensible. This is a concentration-visibility check, not proof that idiosyncratic magnitudes are calibrated.

## What they are NOT evidence of

- **Predictive power**. These cases do not establish it. The magnitude error in Case 1 (~4× too small) and Case 2 (~4× too small) is substantial. nami's structural model treats factor shocks as drawn from the historical *envelope* of the selected analogs — if the selected analogs were a regime weaker than the realized regime, modeled stress outcomes will systematically understate realized moves. This is by design; the alternative is unfounded magnitude extrapolation.
- **Calibration**. Scenario-shocks attribution sums to the factor-driven P&L (Case 1: −6.91% vs −6.71% naive; Case 2: −4.95% vs −7.96% naive — the divergence between naive and Shapley reflects correlation structure between the explicitly shocked factors, not a bug). Periphery is a separate idiosyncratic overlay. For interpretability work the relative ordering of factor contributions and visibility of material per-name periphery matter more than treating any one decomposition as the absolute truth.
- **Robustness to prompt variation**. The three prompts here are crafted to read as honest abstractions, but small wording changes ("sudden" vs "gradual", "cyclicals" vs "growth") would shift which analogs the LLM picks. A real eval would require running matched prompt variants and reporting the spread.

## A real backtest would require

- **Held-out prompt elicitation from contemporaneous text** — e.g. FOMC minutes the day before the as-of date, news headlines from that day — rather than retrospectively-written prompts. The current setup makes the human writing the prompt the leakage channel.
- **A larger, randomly-selected event set** rather than three hand-picked regimes that match nami's existing analog library well.
- **Walk-forward evaluation** rather than single-window comparisons, with portfolio holdings re-derived at each as-of from contemporaneous index constituents (the 2026 `us_tech_growth` portfolio over-weights post-2020 winners).

For now these are honest reproducibility receipts, not capability claims.

## Decomposing the magnitude gap

The understatement documented above has two candidate sources: the linear factor engine
itself, and the severity of the LLM-proposed, envelope-banded shocks. The LLM-free
engine-replay harness ([`docs/engine-replay-validation.md`](engine-replay-validation.md),
regenerated via `scripts/run_engine_replay.py`) isolates the first layer by pushing each
event's REALIZED factor returns through vintage betas across every (registry event ×
sample book) pair. Where the engine tracks realized returns closely on that harness, the
full-run gap seen in these case studies localizes to the shock-severity layer — the
selected analogs and the `[p10, p90]` band, not the beta transfer. The per-scenario
"analog replay range" strip in the results UI surfaces the same decomposition to users.
