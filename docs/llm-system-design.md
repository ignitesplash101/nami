# LLM systems design — nami

The non-obvious decisions behind nami's Gemini integration, prompt versioning, eval discipline, and reproducibility contract. Intended for an ML engineer evaluating the codebase; a 5-minute read.

Source-of-truth for everything below is [`docs/methodology.md`](methodology.md), the code paths cited inline, and the test files. Where this doc and [`CLAUDE.md`](../CLAUDE.md) appear to disagree, the code and tests win.

---

## 1. Three-call Gemini pipeline (not one mega-prompt)

A scenario run executes three distinct Gemini calls in sequence, with different `(system_instruction, tools, response_schema)` configs per call. Orchestration is in [`app/llm/scenario.py::run_scenario`](../app/llm/scenario.py); the calls themselves in [`app/llm/gemini_client.py::GeminiClient`](../app/llm/gemini_client.py).

| call | tools | response_schema | purpose |
|---|---|---|---|
| `select_analogs` | none | `AnalogSelectionOutput` | Pick 2–5 events from the curated registry whose mechanism matches the scenario |
| `_grounded_narrative` (Call 2a) | `google_search` | **none** (free-form text) | Write a 3-5 sentence hypothetical stress narrative citing current news |
| `_extract_structured_shocks` (Call 2b) | none | `ShockProposalOutput` | Translate that narrative into a `FactorShock` list + `PeripheryShock` list |

Why split Call 2 in two? See section 2.

The orchestrator runs Call 1 with the pre-fetched event registry, then *parallelizes* (a) `yfinance` portfolio prices, (b) `yfinance` factor-history fetches, (c) the Calls 2a/2b chain — all inside one `ThreadPoolExecutor` opened immediately after the cache check. The market-data calls (~2–6s) overlap with the Gemini chain (~8–16s), so yfinance becomes effectively free. The 3 Shapley attribution fits at the end also run in a 3-worker pool because `shap.LinearExplainer` drops into NumPy/SciPy linalg that releases the GIL.

---

## 2. Why grounding and `response_schema` can't share a call

Documented in [`app/llm/gemini_client.py`](../app/llm/gemini_client.py) docstring lines 1–9: when Gemini 3.5 Flash receives both a `tools=[google_search]` config and a `response_schema=...` config, **it frequently honors the schema and skips the search tool**. The result is valid JSON with no `grounding_metadata` — i.e., the narrative looks current but isn't actually sourced.

The fix is the Call 2a / Call 2b split:
- **Call 2a** runs with `tools=[google_search]` and *no* schema → forces a real search → returns free text + citations
- **Call 2b** runs with the schema and *no* tools → forces structured extraction → returns the typed `ShockProposalOutput`

Both calls run with the same `temperature=0` and the orchestrator stitches them back together via `model_copy(update={"narrative": narrative})`. The pipeline raises `RuntimeError` if Call 2a returns empty citations — no fallback, no silent ungrounded path ([`gemini_client.py:132–136`](../app/llm/gemini_client.py)).

This is documented in code, not just docs. Reviewers can grep for the assertion.

---

## 3. `PROMPT_VERSION` as the cache-invalidation lever

Defined in [`app/llm/prompts.py::PROMPT_VERSION`](../app/llm/prompts.py) — currently `"v9"`. The version is mixed into the scenario cache key:

```python
# app/utils/hashing.py::scenario_cache_key
key_inputs = (
    scenario_text, portfolio_key, holdings, market_date, model_id,
    prompt_version,            # <-- here
    factor_universe_version, events_version,
    regression_spec,           # estimator id|lookback|alpha|min_obs — engine-math lever
    # + position_quantities / pinned_event_ids when present
)
```

The discipline: **bump `PROMPT_VERSION` for ANY change that affects `ScenarioResult`'s shape OR prompt semantics**. Schema changes invalidate the cache the same way prompt changes do — Pydantic v2 under `extra="forbid"` rejects unknown fields at `model_validate()` time, so a v5 cached payload couldn't safely deserialize against a v6 schema anyway.

The full version history is in the file header. Highlights:
- v3 → v4: `PortfolioPnL` renamed `by_factor → by_factor_naive`, added `by_factor_conditional_shapley`, `ScenarioResult` gained `narrative_shapley`
- v4 → v5: added `by_factor_conditional_shapley_explicit` and `_grouped` Shapley variants
- v5 → v6: backdating + analog-only narrative path; analog filter switched to `end_date <= as_of` (was implicitly unbounded). Same `(scenario_text, portfolio, market_date)` could have returned a different result under v5 if an event was still in progress on `market_date` — so the cache must be invalidated.
- v6 → v7: later prompt semantics update; see [`app/llm/prompts.py`](../app/llm/prompts.py) for the canonical changelog.
- v7 → v8: shock extraction is explicitly framed as hypothetical stress construction, overlapping factor divergence must be explained, and `ScenarioResult` gained warning-only `risk_diagnostics`.
- v8 → v9: shock-units/horizon contract in the extraction prompt (cumulative episode total returns, not weekly) + honest rule-4 wording (the reasoning-based envelope escape hatch never existed in code), per-event envelope payload + window lengths, 2–5 analog cardinality enforced post-hoc, periphery hard band ±0.75, horizon-neutral factor descriptions, `ScenarioResult` gained `regression_quality` + `analog_event_returns`, and `.T`-suffix ticker returns are USD-converted before beta estimation. Engine-math changes (standardized ridge, per-ticker masks) are keyed separately via the new `regression_spec` cache-key component — that lever, not `PROMPT_VERSION`, owns estimator/alpha/lookback changes from here on.

ML-systems framing: this is *experiment versioning*. Same prompt + same model + same data + same code → byte-for-byte same output (modulo Gemini's own non-determinism, which `temperature=0` reduces but doesn't eliminate). Bump the version when any input to that contract changes.

---

## 4. Semantic-only evals (no magnitude bounds)

Live-LLM tests live in [`tests/test_live_evals.py`](../tests/test_live_evals.py). Three tests, network-gated on `RUN_NETWORK_TESTS=1`, costs ~$0.003 total per run. The assertions are deliberately *semantic*, not numeric:

| test | assertion |
|---|---|
| `test_pandemic_picks_pandemic_tagged_analog` | At least one selected analog has the `pandemic` tag AND at least one citation returned |
| `test_banking_stress_hits_xlf_harder_than_spy` | If both XLF and SPY are shocked, `xlf_shock < spy_shock` (financials lead). `pytest.skip` if the LLM didn't shock both. |
| `test_taiwan_scenario_periphery_includes_semis` | The periphery-shock ticker set intersects `{NVDA, AMD, AAPL, AVGO, AMAT, QCOM}` |

Why no magnitude bounds? Three reasons:
1. **News drifts.** Same scenario text two months apart returns different grounded narratives because Google Search results have changed. The numbers ride that drift.
2. **Gemini is not bit-deterministic** even at `temperature=0`. Same input can produce slightly different floats across runs and across model patch versions.
3. **The deterministic invariants live elsewhere.** [`app/llm/validation.py::validate_shock_proposal`](../app/llm/validation.py) and the offline `tests/test_validation.py` suite enforce: every factor name is in `FACTORS`, no duplicates, no hallucinated tickers, factor shocks with envelope `count ≥ 3` stay inside `[p10, p90]`. The retry loop in `propose_shocks_with_retry` re-asks Gemini once with the violation list embedded; on second failure it raises.

So the offline suite holds *structure* (codified contracts) while the network-gated suite holds *mechanism* (does the LLM's understanding of pandemics still link to pandemic analogs?). Together they let the snapshot in [`docs/backtest_results.md`](backtest_results.md) be an honest dated record rather than a stable benchmark.

---

## 5. Iterative adjustment is structured editing, not re-proposal

The sliders + "make rates shock larger" prompt path in the UI does **not** re-run the full pipeline. [`app/llm/scenario.py::adjust_scenario_shocks`](../app/llm/scenario.py) takes a server-side `cache_key` (NOT a client-supplied prior result) and produces a derived `ScenarioResult` with the narrative, citations, analogs, periphery shocks, and factor envelope **guaranteed byte-for-byte unchanged** via `model_copy`. Only `factor_shocks`, `portfolio_pnl`, and `adjustment_history` change.

Two adjustment modes:
- **Manual** (sliders): `overrides: dict[str, float]` keyed by factor name. Every factor must be present (use `0.0` to remove). Validated by [`app/llm/adjust_validation.py::validate_factor_overrides`](../app/llm/adjust_validation.py).
- **LLM** (free-text): `adjustment_text: str`. A 4th Gemini call (`propose_shock_edit`) returns a typed `ShockEditPatch` with `scope: Literal["local", "rerun_required"]`. `scope="local"` is applied; `scope="rerun_required"` is rejected with a 422 + `rejection_reason` so the UI can offer a "rerun full scenario" CTA.

Three non-obvious validation rules:
- **Zero-removal carve-out**: `new_shock == 0.0` is always accepted regardless of envelope. Otherwise must be in `[p10, p90]` when the factor's analog `count >= 3`. (`validate_shock_proposal` blocks out-of-envelope *initial* proposals too — but only after a one-retry repair loop and only at `count >= 3`; adjustment rejects immediately.)
- **Low-evidence keep-or-remove**: when a factor's envelope `count < 3` the band is interpolation-shaped, so the only valid overrides are the canonical shock itself or `0.0` — mirroring the proposal-side count gate. Binds sliders, LLM patches, and direct API calls identically.
- **No client-supplied prior**: clients echo back the `cache_key` from the original run; the server re-fetches the canonical result. Tamper-proof.

Why does this design matter? It means the LLM can't accidentally rewrite the narrative or citations while editing a single factor — the invariants are *structural*, enforced by `model_copy` and a separate `ShockEditPatch` schema. Reusing `ShockProposalOutput` for adjustments would have made every slider drag a potential narrative rewrite.

---

## 6. Vintage-controlled backdating (no look-ahead leakage)

`run_scenario(market_date=...)` switches the entire pipeline to as-of mode when `market_date < today`. Three coordinated changes flip atomically:

1. **Events filtered** by `event.end_date <= as_of` via [`app/factors/analogs.py::filter_events_as_of`](../app/factors/analogs.py). End-date, not start-date — a start-date filter would let in-progress events leak post-as-of returns through `fetch_event_returns`.
2. **yfinance fetches use `end=as_of + 1d`** (yfinance `end=` is exclusive). The same `end` is also threaded through the factor-history fetch and the adjustment-path refetch.
3. **Warm cache bypassed** — [`app/factors/warm_cache.py`](../app/factors/warm_cache.py) keys only on `lookback_weeks` and always returns current data; the backdated path calls `fetch_factor_returns_with_history(end=...)` directly.
4. **Narrative switches to `_analog_grounded_narrative`** ([`gemini_client.py:159`](../app/llm/gemini_client.py)) — Google Search is **not** invoked, the narrative is grounded in the selected analog events only, and `citations = []` is returned. `analogs_selected` becomes the audit trail instead of news URLs.

What is **not** vintage-controlled, honestly acknowledged: **Gemini's parametric knowledge.** The model still "knows" COVID happened even if `as_of = 2018`. The UI banner ([`frontend/src/AsOfDatePicker.tsx::BackdatedModeBanner`](../frontend/src/AsOfDatePicker.tsx)) makes this explicit. For reproducibility-grade work, treat the analog envelope and structural factor shocks as canonical; the narrative is illustrative.

Tests: [`tests/test_scenario_backdating.py`](../tests/test_scenario_backdating.py) (mocked end-to-end, asserts yfinance `end=` and grounding mode), [`tests/test_analogs_backdating.py`](../tests/test_analogs_backdating.py) (the events filter), [`tests/test_calendar.py`](../tests/test_calendar.py) (NYSE trading-day resolution).

---

## 7. Reproducibility metadata as experiment tracking

Every saved scenario (Firestore `saved_scenarios/{id}`) stores a full `ScenarioReproducibility` block inline ([`app/api/main.py::_build_reproducibility`](../app/api/main.py)):

- `model_id` (e.g. `gemini-3.5-flash`)
- `prompt_version` (current `PROMPT_VERSION`)
- `factor_universe_version` (hash of `FACTORS` dict)
- `events_version` (hash of `historical_events.yaml`)
- `requested_as_of_date` + `effective_as_of_date` (raw user date + NYSE-resolved date)
- `narrative_mode` (`grounded` | `analog_only`)
- `beta_lookback_weeks`, `ridge_alpha`, `regression_spec` (full estimator identity)
- `selected_event_ids`, full `portfolio_holdings` dict, `portfolio_key`
- `nami_engine_version`

Saved records also inline the *full* `ScenarioResult` and the *full* event details for selected analogs — no foreign-keys, no GCS-cache dereferences. The GCS scenario cache has a 7-day TTL; a Firestore saved record outlives that without breakage.

What this buys: a scenario saved today can be re-rendered a year later from the Firestore record alone, even if the live events YAML or the sample-portfolio definitions have drifted. The only thing that *can't* be reproduced bit-for-bit is the underlying Gemini model itself.

---

## Footnotes for ML reviewers

- **Attribution as ML interpretability.** The 4 attribution maps in [`app/factors/attribution.py`](../app/factors/attribution.py) treat the linear factor model `R_p = Σ β_i · w_i · F` as a multivariate function and apply Shapley credit allocation. The product split is deliberate: **Scenario shocks** is the production risk view, **Group totals** is the risk-committee view, and `Naive algebra` plus `Full conditional diagnostic` stay in advanced diagnostics. The backend grouped map remains factor-level after within-group redistribution; the UI waterfall sums it into true Market / Sector / Style / Macro totals and keeps factor detail in the table. The "Conditional Shapley" name follows Aas et al. (2021) and Janzing et al. (2020) — credit is allocated under the *historical conditional distribution* of factor returns, computed via `shap.LinearExplainer((coefs, intercept), masker=shap.maskers.Impute(background))`. This is not a causal decomposition. The full diagnostic can credit unshocked factors through correlation; it never drives the headline readout. Periphery remains outside factor Shapley and is surfaced as ticker-level idiosyncratic contribution when gross periphery is material.

- **Theme-sensitivity Shapley** ([`app/llm/narrative_shapley.py`](../app/llm/narrative_shapley.py)) is fixed-context scenario-theme sensitivity: a scenario is decomposed into N=2..4 sub-narratives, then re-run on 2^N − 1 subsets in parallel (4-worker `ThreadPoolExecutor`), then Shapley-aggregated. Each subset **pins the source scenario's analog set and uses the analog-only narrative path (no Google re-grounding)** — only the shock proposal varies per fragment, so `v(S)` is deterministic. It measures the marginal shock each theme adds *within the original analog context*; illustrative, not causal risk attribution. Framed honestly in the UI as "Experimental:".
