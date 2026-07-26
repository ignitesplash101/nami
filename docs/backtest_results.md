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

Each test costs ~$0.08 in Vertex AI Gemini billable tokens (gemini-3.6-flash list prices
incl. thinking tokens, 2026-07-22); Google Search grounding stays within the free monthly tier.

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

## Snapshot — 2026-07-26

Generated via `uv run python scripts/snapshot_live_evals.py`. Source data:
[`scripts/live_evals_snapshot.json`](../scripts/live_evals_snapshot.json), which now
carries the provenance block below so a stale table can never read as current.

| field | value |
|---|---|
| model | `gemini-3.6-flash` (location `global`) |
| `PROMPT_VERSION` | v11 |
| `factor_universe_version` | `3d07434f1346` |
| `events_version` | `d0468e689f2d` |
| nami engine | 0.2.0 |
| temperature | 0.0 |
| `STRUCTURED_THINKING_LEVEL` | unset (server default) |
| effective market date | 2026-07-24 |

| scenario | portfolio | modeled P&L | top factor (shock → naive contrib) | analogs picked | citations |
|---|---|---|---|---|---|
| pandemic resurgence | msci_world | **−23.89%** | VIX (+269% → +1.43% of P&L) | covid-crash-2020, nine-eleven-2001, japan-earthquake-2011 | 6 |
| banking failures | msci_world | **−2.25%** | VIX (+25% → +0.13% of P&L) | svb-banking-2023, lehman-gfc-2008, bnp-paribas-credit-2007 | 2 |
| Taiwan invasion | us_tech_growth | **−28.00%** | VIX (+75% → +0.23% of P&L) | japan-earthquake-2011, q4-trade-war-2018, nine-eleven-2001 | 4 |

Citation source domains (the publisher, not the redirect — see the findings):

| scenario | domains |
|---|---|
| pandemic resurgence | `imf.org`, `nih.gov`, `harvard.edu`, `sifma.org`, `theguardian.com`, `forbes.com` |
| banking failures | `americanbar.org`, `wikipedia.org` |
| Taiwan invasion | `csis.org`, `globaltaiwan.org`, `laweconcenter.org`, `bisinfotech.com` |

---

## Findings — 2026-07-26

- **This is the first snapshot on `gemini-3.6-flash` and `PROMPT_VERSION` v11.** The
  previous table (2026-05-28) was produced on `gemini-3.5-flash` under an older prompt
  and carried no model stamp, so it silently read as current for two model/prompt
  changes. The provenance block above exists to stop that recurring.
- **v11's source hierarchy is directionally honored, but not enforced.** v11 asks for
  government/central-bank sources first, then research, then major news, and names
  Wikipedia as last resort. Two of three scenarios comply well: the pandemic run drew on
  `imf.org`, `nih.gov`, `harvard.edu` and `sifma.org`, and the Taiwan run on three
  research/institute domains. The banking run returned only two citations, one of which
  is `wikipedia.org` — the exact source v11 deprioritizes. Treat the hierarchy as a
  preference the model usually follows, not a guarantee. n=3 and stochastic over news
  drift: this is an observation, not a measurement.
- **Citation URLs are NOT publisher URLs.** Every `Citation.url` is a
  `vertexaisearch.cloud.google.com/grounding-api-redirect/...` link; the real domain
  lives in `Citation.title`. Any analysis (or UI copy) that reads the URL's host will
  report the redirector for 100% of citations. `scripts/snapshot_live_evals.py` now
  reads the title for exactly this reason.
- **Analog selection was mechanistically sensible**: pandemic resurgence picked the COVID
  crash plus two exogenous-shock analogs (9/11, Tōhoku); banking failures picked SVB +
  Lehman + the 2007 BNP Paribas credit freeze; Taiwan picked Tōhoku (supply-chain
  disruption) + the 2018 trade war + 9/11.
- **VIX remains the dominant proposed factor across all three scenarios** — unchanged
  from the 2026-05-28 snapshot and from 3.5 Flash. Gemini leans on broad risk-off as the
  primary mechanism rather than isolating sector factors. Note the naive contribution of
  the VIX shock is *positive* in all three (long-vol exposure offsets a small part of the
  loss); the headline P&L is driven by the equity-beta factors, not by VIX.
- **Wall-clock**: 46.1s, 42.9s, 42.4s on genuine cache misses (the re-run to correct the
  citation-domain extraction was served from cache in 2–4s). This is the honest
  cache-miss number for the current model: appreciably slower than the 10–20s recorded
  in the 3.5-Flash era, consistent with thinking-enabled generation.
- **Magnitudes are illustrative, not benchmarked.** The −28% modeled P&L on the Taiwan
  scenario reflects the analog envelope intersected with the US tech book's high beta to
  those factors — it is not a forecast.

---

## Limitations of this evaluation

- **Calibration is anchored to historical analogs.** If the LLM picks the "wrong" analogs
  (e.g., picks a 2018 trade-war analog for a banking crisis), the envelope it works against
  is mis-targeted. The Phase 6 tests verify *some* analog matching is correct via tag membership.
- **Magnitudes are LLM-proposed within the analog band**, not derived from a structural model.
  Sensible-looking outputs are not proofs of forecasting power.
- **Periphery shocks are LLM heuristics** about idiosyncratic exposure. They are not derived
  from named-entity supply-chain data. The UI now surfaces material gross periphery by
  ticker, but that improves concentration visibility, not statistical calibration.
- **News-grounded narratives reflect search results at run time**, which can vary by hours.
