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

## Snapshot — YYYY-MM-DD (TO BE POPULATED)

Re-run the tests with `RUN_NETWORK_TESTS=1`, then paste the numeric outputs here as a
historical record. Suggested table shape:

```
| scenario | portfolio | total P&L | top factor (shock → contrib) | analogs picked | citations |
|---|---|---|---|---|---|
| pandemic resurgence | msci_world | -X.XX% | SPY (-X.X% → -X.XX% of P&L) | covid-crash-2020, ... | N |
| banking failures | msci_world | -X.XX% | XLF (-X.X% → -X.XX% of P&L) | lehman-gfc-2008, ... | N |
| Taiwan invasion | us_tech_growth | -X.XX% | XLK (-X.X% → -X.XX% of P&L) | china-deval-2015, ... | N |
```

---

## Findings on this date (TO BE WRITTEN AFTER FIRST POPULATION)

- Factor shocks were within envelope p10/p90 for all factors with count ≥ 3 (the validator
  enforces this; recorded here as confirmation)
- Periphery tickers were thematically relevant to the scenario (semis on Taiwan, banks on
  banking stress, etc.)
- Citation counts averaged X per scenario
- Total wall-clock: ~Xs per scenario (2 Gemini calls + grounding + factor model + cache write)

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
