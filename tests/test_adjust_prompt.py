"""Prompt-driven shock adjustment tests with mocked Gemini patch responses."""

from __future__ import annotations

import pytest

from app.llm.scenario import adjust_scenario_shocks
from app.llm.schemas import FactorEdit, ShockEditPatch
from tests.conftest import InMemoryCache
from tests.test_adjust_manual import _canonical_run
from tests.test_scenario import _MockGeminiClient


class _MockGeminiWithPatch(_MockGeminiClient):
    """Extends the canonical mock with a `propose_shock_edit` that returns a canned patch."""

    def __init__(self, patch: ShockEditPatch) -> None:
        super().__init__()
        self._patch = patch
        self.edit_calls = 0

    def propose_shock_edit(
        self,
        *,
        prior_factor_shocks,
        adjustment_text,
        envelope,
        factor_universe_descriptions,
    ) -> ShockEditPatch:
        self.edit_calls += 1
        return self._patch


def test_prompt_patch_low_evidence_factor_rejected(monkeypatch):
    """The count<3 keep-or-remove rule binds the LLM patch path too — a direct
    API call cannot re-tune a low-evidence factor just because the UI slider
    is disabled."""
    canonical, cache, _gemini, key, config = _canonical_run(monkeypatch)
    target = canonical.factor_shocks[0]

    envelope_copy = {k: dict(v) for k, v in canonical.factor_envelope.items()}
    envelope_copy[target.factor] = {
        "mean": target.shock,
        "p10": target.shock,
        "p90": target.shock + 0.02,
        "count": 2,
    }
    cache.put_json(
        key,
        canonical.model_copy(update={"factor_envelope": envelope_copy}).model_dump(mode="json"),
    )

    gemini = _MockGeminiWithPatch(
        ShockEditPatch(
            scope="local",
            edits=[
                FactorEdit(
                    factor=target.factor,
                    new_shock=target.shock + 0.01,
                    reasoning="Magnified per user request.",
                )
            ],
        )
    )
    with pytest.raises(ValueError, match="analog observation"):
        adjust_scenario_shocks(
            key,
            adjustment_text="make the first factor larger",
            config=config,
            gemini=gemini,
            cache=cache,
        )


def test_prompt_local_scope_applies_edit_and_preserves_invariants(monkeypatch):
    canonical, cache, _gemini, key, config = _canonical_run(monkeypatch)
    target = canonical.factor_shocks[0]
    new_value = target.shock + 0.01

    gemini = _MockGeminiWithPatch(
        ShockEditPatch(
            scope="local",
            edits=[
                FactorEdit(
                    factor=target.factor,
                    new_shock=new_value,
                    reasoning="Magnified per user request.",
                )
            ],
        )
    )

    result = adjust_scenario_shocks(
        key,
        adjustment_text="make the first factor larger",
        config=config,
        gemini=gemini,
        cache=cache,
    )
    assert gemini.edit_calls == 1

    # Only target factor changed; all other invariants hold.
    for canonical_fs, new_fs in zip(canonical.factor_shocks, result.factor_shocks, strict=True):
        if canonical_fs.factor == target.factor:
            assert new_fs.shock == new_value
            assert new_fs.reasoning == "Magnified per user request."
        else:
            assert new_fs == canonical_fs
    assert result.periphery_shocks == canonical.periphery_shocks
    assert result.narrative == canonical.narrative
    assert result.citations == canonical.citations
    assert result.analogs_selected == canonical.analogs_selected
    assert result.factor_envelope == canonical.factor_envelope

    assert len(result.adjustment_history) == 1
    entry = result.adjustment_history[0]
    assert entry.kind == "prompt"
    assert entry.prompt_text == "make the first factor larger"
    assert entry.changed_factors == {target.factor: [target.shock, new_value]}


def test_prompt_rerun_required_scope_raises(monkeypatch):
    canonical, cache, _gemini, key, config = _canonical_run(monkeypatch)
    gemini = _MockGeminiWithPatch(
        ShockEditPatch(
            scope="rerun_required",
            edits=[],
            rejection_reason="That asks for a new mechanism not in the original analogs.",
        )
    )

    with pytest.raises(RuntimeError, match="new mechanism"):
        adjust_scenario_shocks(
            key,
            adjustment_text="add an oil supply shock",
            config=config,
            gemini=gemini,
            cache=cache,
        )

    # Canonical untouched in the cache.
    cached = cache.store[key]
    assert cached["factor_shocks"] == [fs.model_dump(mode="json") for fs in canonical.factor_shocks]


def test_prompt_local_with_new_factor_caught_by_validator(monkeypatch):
    """Belt-and-braces: even if the LLM mis-classifies scope=local with a factor
    not in the canonical set, the validator rejects."""
    _, cache, _gemini, key, config = _canonical_run(monkeypatch)
    gemini = _MockGeminiWithPatch(
        ShockEditPatch(
            scope="local",
            edits=[
                FactorEdit(
                    factor="DEFINITELY_NOT_A_REAL_FACTOR",
                    new_shock=0.05,
                    reasoning="The LLM mis-classified this.",
                )
            ],
        )
    )

    with pytest.raises(ValueError, match="not in the canonical scenario"):
        adjust_scenario_shocks(
            key,
            adjustment_text="introduce a new factor",
            config=config,
            gemini=gemini,
            cache=cache,
        )


def test_prompt_local_zero_removal_accepted_outside_envelope(monkeypatch):
    """Zero-removal carve-out applies to prompt-driven patches too."""
    canonical, cache, _gemini, key, config = _canonical_run(monkeypatch)
    target = canonical.factor_shocks[0]

    envelope_copy = {k: dict(v) for k, v in canonical.factor_envelope.items()}
    envelope_copy[target.factor] = {"mean": 0.1, "p10": 0.05, "p90": 0.15, "count": 5}
    canonical_tight = canonical.model_copy(update={"factor_envelope": envelope_copy})
    cache.put_json(key, canonical_tight.model_dump(mode="json"))

    gemini = _MockGeminiWithPatch(
        ShockEditPatch(
            scope="local",
            edits=[FactorEdit(factor=target.factor, new_shock=0.0, reasoning="Removed.")],
        )
    )

    result = adjust_scenario_shocks(
        key,
        adjustment_text=f"remove {target.factor}",
        config=config,
        gemini=gemini,
        cache=cache,
    )
    assert result.portfolio_pnl.by_factor_naive[target.factor] == 0.0


def test_adjustment_does_not_pollute_canonical_cache(monkeypatch):
    canonical, cache, _gemini, key, config = _canonical_run(monkeypatch)
    target = canonical.factor_shocks[0]

    gemini = _MockGeminiWithPatch(
        ShockEditPatch(
            scope="local",
            edits=[
                FactorEdit(
                    factor=target.factor,
                    new_shock=target.shock + 0.005,
                    reasoning="Slight bump.",
                )
            ],
        )
    )

    adjust_scenario_shocks(
        key,
        adjustment_text="bump first factor",
        config=config,
        gemini=gemini,
        cache=cache,
    )

    # Cache still holds the canonical (1 entry, unchanged shocks).
    assert len(cache.store) == 1
    cached_shocks = cache.store[key]["factor_shocks"]
    assert cached_shocks[0]["shock"] == target.shock


def test_canonical_cache_only_canonical_assumption_explicit(monkeypatch):
    """Just keep proving the contract: cache reads return canonical, not derived."""
    canonical, cache, _gemini, key, config = _canonical_run(monkeypatch)
    cached = InMemoryCache()
    cached.store = dict(cache.store)
    assert cached.store[key]["factor_shocks"][0]["shock"] == canonical.factor_shocks[0].shock
