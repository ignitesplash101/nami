"""Manual-slider shock adjustment tests.

Covers the invariance contract: only the requested factors change. Narrative,
citations, analogs, periphery shocks, factor_envelope, and unrelated factor
shocks must remain byte-for-byte identical to the canonical result.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.llm.scenario import (
    adjust_scenario_shocks,
    compute_scenario_cache_key,
    run_scenario,
)
from tests.conftest import InMemoryCache
from tests.test_scenario import _config, _MockGeminiClient, _patch_market_layer


def _canonical_run(monkeypatch):
    _patch_market_layer(monkeypatch)
    cache = InMemoryCache()
    gemini = _MockGeminiClient()
    config = _config()
    market_date = date(2026, 5, 25)
    canonical = run_scenario(
        scenario_text="A pandemic-like risk-off",
        portfolio_key="us_tech_growth",
        config=config,
        gemini=gemini,
        cache=cache,
        market_date=market_date,
    )
    key = compute_scenario_cache_key(
        "A pandemic-like risk-off",
        "us_tech_growth",
        config=config,
        market_date=market_date,
    )

    # The mock event-returns are uniform (every analog -> -0.05) so the canonical
    # envelope collapses to p10 == p90 == -0.05. That degenerate envelope rejects
    # the canonical's own LLM shocks under the strict adjust validator. Widen the
    # envelope on the canonical cached payload so adjustment tests have a usable
    # band around the canonical shocks.
    wide_envelope = {
        fs.factor: {"mean": fs.shock, "p10": fs.shock - 0.05, "p90": fs.shock + 0.05, "count": 5}
        for fs in canonical.factor_shocks
    }
    canonical = canonical.model_copy(update={"factor_envelope": wide_envelope})
    cache.put_json(key, canonical.model_dump(mode="json"))

    return canonical, cache, gemini, key, config


def test_manual_only_changed_factors_differ(monkeypatch):
    canonical, cache, gemini, key, config = _canonical_run(monkeypatch)

    overrides = {fs.factor: fs.shock for fs in canonical.factor_shocks}
    target = canonical.factor_shocks[0]
    new_value = target.shock + 0.01
    overrides[target.factor] = new_value

    result = adjust_scenario_shocks(
        key,
        overrides=overrides,
        config=config,
        gemini=gemini,
        cache=cache,
    )

    # Invariance: only the targeted factor changed.
    for canonical_fs, new_fs in zip(canonical.factor_shocks, result.factor_shocks, strict=True):
        assert canonical_fs.factor == new_fs.factor
        if canonical_fs.factor == target.factor:
            assert new_fs.shock == new_value
            assert "Manual override" in new_fs.reasoning
        else:
            assert new_fs.shock == canonical_fs.shock
            assert new_fs.reasoning == canonical_fs.reasoning

    assert result.periphery_shocks == canonical.periphery_shocks
    assert result.narrative == canonical.narrative
    assert result.citations == canonical.citations
    assert result.analogs_selected == canonical.analogs_selected
    assert result.factor_envelope == canonical.factor_envelope

    assert len(result.adjustment_history) == 1
    entry = result.adjustment_history[0]
    assert entry.kind == "manual"
    assert entry.prompt_text is None
    assert target.factor in entry.changed_factors
    assert entry.changed_factors[target.factor] == [target.shock, new_value]


def test_manual_adjustment_preserves_analog_replay(monkeypatch):
    # Replay is shock-independent analog evidence: adjustments must carry the
    # canonical's block through unchanged, like analogs/envelope/narrative.
    canonical, cache, gemini, key, config = _canonical_run(monkeypatch)

    overrides = {fs.factor: fs.shock for fs in canonical.factor_shocks}
    target = canonical.factor_shocks[0]
    overrides[target.factor] = target.shock + 0.01

    result = adjust_scenario_shocks(
        key,
        overrides=overrides,
        config=config,
        gemini=gemini,
        cache=cache,
    )

    assert canonical.analog_replay is not None
    assert result.analog_replay == canonical.analog_replay


def test_manual_adjustment_recomputes_severity_ladder_from_new_shocks(monkeypatch):
    # The ladder is shock-DEPENDENT (unlike analog_replay): after an adjustment
    # it must reflect the new base and the (widened) envelope's band edges.
    canonical, cache, gemini, key, config = _canonical_run(monkeypatch)

    overrides = {fs.factor: fs.shock for fs in canonical.factor_shocks}
    target = canonical.factor_shocks[0]
    overrides[target.factor] = target.shock + 0.01

    result = adjust_scenario_shocks(
        key,
        overrides=overrides,
        config=config,
        gemini=gemini,
        cache=cache,
    )

    ladder = result.severity_ladder
    assert ladder is not None
    # _canonical_run widened every factor's envelope to count=5, so all three
    # shocked factors are banded now (the cached canonical's own ladder was
    # computed pre-widening, with everything held).
    assert ladder.n_banded == len(result.factor_shocks)
    assert ladder.n_held == 0
    assert ladder != canonical.severity_ladder

    # Mock betas: exposure 1.0 on the first factor, 0 elsewhere — so only the
    # first factor's band moves the rungs. Periphery rides along unchanged.
    periphery_total = sum(result.portfolio_pnl.by_ticker_periphery.values())
    p10 = canonical.factor_envelope[target.factor]["p10"]
    p90 = canonical.factor_envelope[target.factor]["p90"]
    assert ladder.base_pnl == pytest.approx(result.portfolio_pnl.total_pnl)
    assert ladder.worst_pnl == pytest.approx(min(p10, p90) + periphery_total)
    assert ladder.best_pnl == pytest.approx(max(p10, p90) + periphery_total)
    assert ladder.worst_pnl <= ladder.base_pnl <= ladder.best_pnl


def test_manual_adjustment_recomputes_identical_pnl_uncertainty(monkeypatch):
    # The band is shock-independent (stats + analog windows only); adjusting on
    # the same vintage must land on an identical block.
    canonical, cache, gemini, key, config = _canonical_run(monkeypatch)

    overrides = {fs.factor: fs.shock for fs in canonical.factor_shocks}
    target = canonical.factor_shocks[0]
    overrides[target.factor] = target.shock + 0.01

    result = adjust_scenario_shocks(
        key,
        overrides=overrides,
        config=config,
        gemini=gemini,
        cache=cache,
    )

    assert canonical.pnl_uncertainty is not None
    assert result.pnl_uncertainty == canonical.pnl_uncertainty


def test_manual_zero_removal_accepted_even_outside_envelope(monkeypatch):
    """0.0 is always allowed as the removal sentinel, even if outside [p10, p90]."""
    canonical, cache, gemini, key, config = _canonical_run(monkeypatch)

    overrides = {fs.factor: fs.shock for fs in canonical.factor_shocks}
    target = canonical.factor_shocks[0]
    overrides[target.factor] = 0.0

    # Force the envelope so 0.0 is OUTSIDE [p10, p90] for `target`.
    envelope_copy = {k: dict(v) for k, v in canonical.factor_envelope.items()}
    envelope_copy[target.factor] = {"mean": 0.1, "p10": 0.05, "p90": 0.15, "count": 5}
    canonical_with_tight_env = canonical.model_copy(update={"factor_envelope": envelope_copy})
    cache.put_json(key, canonical_with_tight_env.model_dump(mode="json"))

    result = adjust_scenario_shocks(
        key,
        overrides=overrides,
        config=config,
        gemini=gemini,
        cache=cache,
    )
    assert result.portfolio_pnl.by_factor_naive[target.factor] == 0.0


def test_manual_out_of_envelope_nonzero_rejected(monkeypatch):
    canonical, cache, gemini, key, config = _canonical_run(monkeypatch)

    overrides = {fs.factor: fs.shock for fs in canonical.factor_shocks}
    target = canonical.factor_shocks[0]

    # Force a tight envelope so any non-zero override outside is rejected.
    envelope_copy = {k: dict(v) for k, v in canonical.factor_envelope.items()}
    envelope_copy[target.factor] = {"mean": 0.0, "p10": -0.01, "p90": 0.01, "count": 5}
    canonical_tight = canonical.model_copy(update={"factor_envelope": envelope_copy})
    cache.put_json(key, canonical_tight.model_dump(mode="json"))

    overrides[target.factor] = 0.5  # way outside [-0.01, 0.01]

    with pytest.raises(ValueError, match="outside the envelope"):
        adjust_scenario_shocks(
            key,
            overrides=overrides,
            config=config,
            gemini=gemini,
            cache=cache,
        )


@pytest.mark.parametrize("count", [0, 1, 2])
def test_manual_low_evidence_factor_is_keep_or_remove(monkeypatch, count):
    """When a factor's envelope count < 3 the band is interpolation-shaped (a
    count=0 row is even serialized as 0/0/0), so re-tuning against it is
    meaningless: the only valid overrides are the canonical shock (keep) or
    0.0 (remove) — mirroring the proposal-side count gate."""
    canonical, cache, gemini, key, config = _canonical_run(monkeypatch)

    target = canonical.factor_shocks[0]
    envelope_copy = {k: dict(v) for k, v in canonical.factor_envelope.items()}
    if count == 0:
        envelope_copy[target.factor] = {"mean": 0.0, "p10": 0.0, "p90": 0.0, "count": 0}
    else:
        envelope_copy[target.factor] = {
            "mean": target.shock,
            "p10": target.shock,
            "p90": target.shock + 0.02,
            "count": count,
        }
    canonical_low = canonical.model_copy(update={"factor_envelope": envelope_copy})
    cache.put_json(key, canonical_low.model_dump(mode="json"))

    base_overrides = {fs.factor: fs.shock for fs in canonical.factor_shocks}

    # Keep (echo the canonical value) — accepted.
    kept = adjust_scenario_shocks(
        key, overrides=dict(base_overrides), config=config, gemini=gemini, cache=cache
    )
    assert kept.factor_shocks[0].shock == target.shock

    # Remove — accepted (0.0 sentinel works regardless of envelope).
    removed_overrides = dict(base_overrides)
    removed_overrides[target.factor] = 0.0
    removed = adjust_scenario_shocks(
        key, overrides=removed_overrides, config=config, gemini=gemini, cache=cache
    )
    assert removed.portfolio_pnl.by_factor_naive[target.factor] == 0.0

    # Re-tune — rejected with the keep-or-remove message.
    retuned_overrides = dict(base_overrides)
    retuned_overrides[target.factor] = target.shock + 0.01
    with pytest.raises(ValueError, match="analog observation"):
        adjust_scenario_shocks(
            key, overrides=retuned_overrides, config=config, gemini=gemini, cache=cache
        )


def test_manual_missing_factor_key_rejected(monkeypatch):
    canonical, cache, gemini, key, config = _canonical_run(monkeypatch)

    overrides = {fs.factor: fs.shock for fs in canonical.factor_shocks}
    del overrides[canonical.factor_shocks[0].factor]

    with pytest.raises(ValueError, match="missing factors"):
        adjust_scenario_shocks(
            key,
            overrides=overrides,
            config=config,
            gemini=gemini,
            cache=cache,
        )


def test_manual_extra_factor_key_rejected(monkeypatch):
    canonical, cache, gemini, key, config = _canonical_run(monkeypatch)

    overrides = {fs.factor: fs.shock for fs in canonical.factor_shocks}
    overrides["NOT_A_REAL_FACTOR"] = 0.05

    with pytest.raises(ValueError, match="not in the canonical scenario"):
        adjust_scenario_shocks(
            key,
            overrides=overrides,
            config=config,
            gemini=gemini,
            cache=cache,
        )


def test_expired_cache_key_raises_lookup_error(monkeypatch):
    _patch_market_layer(monkeypatch)
    cache = InMemoryCache()
    gemini = _MockGeminiClient()
    config = _config()

    with pytest.raises(LookupError, match="not found"):
        adjust_scenario_shocks(
            "nonexistent-cache-key",
            overrides={"SPY": 0.0},
            config=config,
            gemini=gemini,
            cache=cache,
        )


def test_both_overrides_and_adjustment_text_rejected(monkeypatch):
    canonical, cache, gemini, key, config = _canonical_run(monkeypatch)
    with pytest.raises(ValueError, match="Exactly one"):
        adjust_scenario_shocks(
            key,
            overrides={fs.factor: fs.shock for fs in canonical.factor_shocks},
            adjustment_text="something",
            config=config,
            gemini=gemini,
            cache=cache,
        )


def test_neither_overrides_nor_adjustment_text_rejected(monkeypatch):
    _, cache, gemini, key, config = _canonical_run(monkeypatch)
    with pytest.raises(ValueError, match="Exactly one"):
        adjust_scenario_shocks(
            key,
            config=config,
            gemini=gemini,
            cache=cache,
        )
