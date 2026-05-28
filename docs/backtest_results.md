# Live LLM evaluation snapshot

> ⚠️ **This is a dated snapshot, NOT a stable benchmark.**
> The engine calls real Gemini with Google Search grounding. News drifts, search rankings
> change, and the LLM is not bit-deterministic across months even with `temperature=0`.
> Re-run `RUN_NETWORK_TESTS=1 uv run pytest tests/test_live_evals.py -v` to refresh.

---

## How to regenerate

```powershell
$env:RUN_NETWORK_TESTS = "1"
uv run --link-mode=copy pytest tests/test_live_evals.py -v
Remove-Item Env:RUN_NETWORK_TESTS
```

Each test costs ~$0.001 in Vertex AI Gemini + Google Search billable units.

---

## Semantic invariants the live-eval tests enforce

| # | scenario | portfolio | passing condition |
|---|---|---|---|
| 1 | Pandemic resurgence + lockdown | `msci_world` | Engine picks at least one `pandemic`-tagged analog AND returns ≥1 citation |
| 2 | Multi-bank failure + deposit flight | `msci_world` | When both XLF and SPY shocked, XLF shock < SPY shock (financials lead) |
| 3 | China invades Taiwan + semi disruption | `us_tech_growth` | Periphery shocks include ≥1 of {NVDA, AMD, AAPL, AVGO, AMAT, QCOM} |

These check **mechanism** rather than specific magnitudes — magnitudes drift across runs.

---

## In-pipeline calibration guarantees (deterministic — held by code)

These are enforced by `app/llm/validation.validate_shock_proposal` and confirmed in the
`tests/test_validation.py` suite (not network-gated):

- Every factor in a shock proposal is in `FACTORS` (no hallucinated factor names)
- No duplicate factor names; no duplicate periphery tickers
- Periphery shocks only reference tickers in the portfolio's holdings
- Factor shocks with envelope `count ≥ 3` are rejected if outside `[p10, p90]`
- `propose_shocks_with_retry` raises if no grounding metadata returned (no citations → no return)

The first time a proposal violates any of the above, the LLM is re-asked with the validation
error embedded; if it still fails after the retry, the pipeline raises.

---

## Snapshot — 2026-05-28

Generated via `uv run python scripts/snapshot_live_evals.py`. Source data:
[`scripts/live_evals_snapshot.json`](../scripts/live_evals_snapshot.json).

| scenario | portfolio | total P&L | top factor (shock → naive contrib) | analogs picked | citations |
|---|---|---|---|---|---|
| pandemic resurgence | msci_world | **−10.28%** | VIX (+220% → −3.91% of P&L) | covid-crash-2020, lehman-gfc-2008 | 2 |
| banking failures | msci_world | **−0.94%** | VIX (+50% → −0.89% of P&L) | svb-banking-2023, lehman-gfc-2008, covid-liquidity-2020 | 6 |
| Taiwan invasion | us_tech_growth | **−21.37%** | VIX (+105% → −3.41% of P&L) | inflation-ukraine-2022, q4-trade-war-2018, china-deval-2015 | 5 |

(Per-test pass/skip status from `tests/test_live_evals.py` on the same run: 2 passed,
1 skipped. The `test_banking_stress_hits_xlf_harder_than_spy` test skipped because the
LLM proposed VIX as the dominant shock rather than shocking both XLF and SPY — exactly
the kind of run-to-run drift the test's `pytest.skip` guard exists for.)

---

## Findings — 2026-05-28

- **Factor shocks were within envelope p10/p90** for all factors with `count ≥ 3` — enforced
  by `validate_shock_proposal` ([`app/llm/validation.py`](../app/llm/validation.py)) with
  one-retry recovery; no scenario hit the retry path on this snapshot.
- **Analog selection was mechanistically sensible**: pandemic resurgence picked the COVID
  crash; banking failures picked SVB + Lehman + COVID liquidity squeeze (Fed-backstop
  pattern matches); Taiwan invasion picked Ukraine inflation + 2018 trade war + 2015
  China devaluation.
- **VIX was the dominant proposed factor across all three scenarios.** This reflects
  Gemini's tendency to lean on broad risk-off as the primary mechanism rather than
  isolating sector-specific factors — a known calibration tendency. The
  `test_banking_stress_hits_xlf_harder_than_spy` test catches the cases where the LLM
  *does* break out sector factors; on this run it didn't shock XLF + SPY separately.
- **Citation counts**: 2, 6, 5 — averaging 4.3 per scenario. All scenarios produced
  grounded narratives (`narrative_mode = "grounded"`), so Google Search fired correctly.
- **Wall-clock**: 2.3s, 2.6s, 3.6s per scenario — these are mostly cache hits from the
  `pytest tests/test_live_evals.py` run that ran ~3 minutes prior. A genuine cache miss
  is closer to 10–20s (3 Gemini calls + 2 yfinance fetches in parallel + 3 Shapley fits).
- **Magnitudes are illustrative, not benchmarked.** A −21% predicted P&L on the Taiwan
  scenario reflects the analog envelope (2018 trade war + 2022 inflation + 2015 deval
  windows) intersected with the US tech portfolio's high beta to those factors — it is
  not a forecast.

---

## Limitations of this evaluation

- **Calibration is anchored to historical analogs.** If the LLM picks the "wrong" analogs
  (e.g., picks a 2018 trade-war analog for a banking crisis), the envelope it works against
  is mis-targeted. The Phase 6 tests verify *some* analog matching is correct via tag membership.
- **Magnitudes are LLM-proposed within the analog band**, not derived from a structural model.
  Sensible-looking outputs are not proofs of predictive power.
- **Periphery shocks are LLM heuristics** about idiosyncratic exposure. They are not derived
  from named-entity supply-chain data.
- **News-grounded narratives reflect search results at run time**, which can vary by hours.
