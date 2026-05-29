"""Mocked tests for the narrative-Shapley orchestrator. No network, no Gemini.

The pipeline payoff function `v(S) = total_pnl(run_scenario(" ".join(S)))` is mocked
so we can test the Shapley arithmetic (efficiency, symmetry) and input validation
without exercising the real LLM.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.config import Config
from app.llm.narrative_shapley import compute_narrative_shapley
from app.llm.schemas import (
    AnalogSelection,
    Citation,
    FactorShock,
    PeripheryShock,
    PortfolioPnL,
    ScenarioResult,
)
from tests.conftest import InMemoryCache


def _base_result() -> ScenarioResult:
    return ScenarioResult(
        scenario_text="combined scenario",
        market_date=date(2026, 5, 25),
        portfolio_key="us_tech_growth",
        portfolio_name="US Tech Growth",
        portfolio_holdings={"AAPL": 0.6, "MSFT": 0.4},
        analogs_selected=[AnalogSelection(event_id="covid-crash-2020", why_relevant="r")],
        factor_shocks=[FactorShock(factor="SPY", shock=-0.05, reasoning="r")],
        periphery_shocks=[PeripheryShock(ticker="AAPL", shock=-0.02, reasoning="r")],
        narrative="A combined narrative.",
        citations=[Citation(url="https://example.com")],
        factor_envelope={},
        portfolio_pnl=PortfolioPnL(
            total_pnl=-0.05,
            by_factor_naive={"SPY": -0.05},
            by_ticker_factor={"AAPL": -0.03, "MSFT": -0.02},
            by_ticker_periphery={"AAPL": -0.012, "MSFT": 0.0},
            by_ticker_total={"AAPL": -0.042, "MSFT": -0.02},
        ),
    )


def _config() -> Config:
    return Config(
        google_cloud_project="test",
        vertex_ai_location="global",
        gcs_bucket="test",
        vertex_model_id="gemini-3.5-flash",
        beta_lookback_weeks=104,
    )


def _install_mock_run_scenario(
    monkeypatch,
    pnl_for_text: dict[str, float],
) -> list[str]:
    """Monkeypatch `app.llm.narrative_shapley.run_scenario` to look up the joined
    sub-narrative text in `pnl_for_text` and synthesize a ScenarioResult."""
    calls: list[str] = []

    def _fake_run_scenario(text, portfolio, **_kwargs):  # noqa: ARG001
        calls.append(text)
        if text not in pnl_for_text:
            raise AssertionError(f"unexpected subset text in fake run_scenario: {text!r}")
        pnl_val = pnl_for_text[text]
        return ScenarioResult(
            scenario_text=text,
            market_date=date(2026, 5, 25),
            portfolio_key="custom",
            portfolio_name=portfolio.name,
            portfolio_holdings=dict(portfolio.holdings),
            analogs_selected=[],
            factor_shocks=[],
            periphery_shocks=[],
            narrative="mock",
            citations=[],
            factor_envelope={},
            portfolio_pnl=PortfolioPnL(
                total_pnl=pnl_val,
                by_factor_naive={},
                by_ticker_factor={},
                by_ticker_periphery={},
                by_ticker_total={},
            ),
        )

    monkeypatch.setattr("app.llm.narrative_shapley.run_scenario", _fake_run_scenario)
    return calls


def test_narrative_shapley_efficiency_with_mocked_runner(monkeypatch):
    """Sum of Shapley contributions equals v(full set) (efficiency axiom)."""
    subs = ["A.", "B.", "C."]

    def joined(mask: int) -> str:
        return " ".join(subs[i] for i in range(3) if mask & (1 << i))

    pnls = {
        joined(1): -0.01,
        joined(2): -0.02,
        joined(3): -0.04,  # A+B has interaction
        joined(4): -0.03,
        joined(5): -0.05,
        joined(6): -0.06,
        joined(7): -0.10,  # A+B+C full
    }
    calls = _install_mock_run_scenario(monkeypatch, pnls)

    base = _base_result()
    augmented = compute_narrative_shapley(
        base,
        config=_config(),
        gemini=None,
        cache=InMemoryCache(),
        decomposition_cache=InMemoryCache(),
        market_date=date(2026, 5, 25),
        sub_narratives_override=subs,
    )

    assert len(calls) == 7  # 2^3 - 1 (skip empty subset)
    nsr = augmented.narrative_shapley
    assert nsr is not None
    sum_phi = sum(c.shapley_value for c in nsr.contributions)
    assert abs(sum_phi - pnls[joined(7)]) < 1e-9
    assert nsr.total_pnl == pytest.approx(pnls[joined(7)])
    assert nsr.n_subsets_evaluated == 8


def test_narrative_shapley_symmetry_with_identical_subs(monkeypatch):
    """Two sub-narratives producing identical marginal payoffs across every subset
    must receive identical Shapley values."""
    subs = ["X.", "Y."]  # We construct payoffs so X and Y are interchangeable

    pnls = {
        "X.": -0.03,
        "Y.": -0.03,
        "X. Y.": -0.05,
    }
    _install_mock_run_scenario(monkeypatch, pnls)

    augmented = compute_narrative_shapley(
        _base_result(),
        config=_config(),
        gemini=None,
        cache=InMemoryCache(),
        decomposition_cache=InMemoryCache(),
        market_date=date(2026, 5, 25),
        sub_narratives_override=subs,
    )
    nsr = augmented.narrative_shapley
    assert nsr is not None
    phi_x = nsr.contributions[0].shapley_value
    phi_y = nsr.contributions[1].shapley_value
    assert abs(phi_x - phi_y) < 1e-12
    assert abs(phi_x + phi_y - pnls["X. Y."]) < 1e-12


def test_narrative_shapley_pins_source_analogs(monkeypatch):
    """Every subset run reuses the source scenario's analog set (fixed-context)."""
    seen_pinned: list = []

    def _fake(text, portfolio, **kwargs):  # noqa: ARG001
        seen_pinned.append(kwargs.get("pinned_event_ids"))
        return ScenarioResult(
            scenario_text=text,
            market_date=date(2026, 5, 25),
            portfolio_key="custom",
            portfolio_name=portfolio.name,
            portfolio_holdings=dict(portfolio.holdings),
            analogs_selected=[],
            factor_shocks=[],
            periphery_shocks=[],
            narrative="mock",
            citations=[],
            factor_envelope={},
            portfolio_pnl=PortfolioPnL(
                total_pnl=-0.01,
                by_factor_naive={},
                by_ticker_factor={},
                by_ticker_periphery={},
                by_ticker_total={},
            ),
        )

    monkeypatch.setattr("app.llm.narrative_shapley.run_scenario", _fake)
    base = _base_result().model_copy(
        update={"selected_event_ids": ["covid-crash-2020", "lehman-gfc-2008"]}
    )
    compute_narrative_shapley(
        base,
        config=_config(),
        gemini=None,
        cache=InMemoryCache(),
        decomposition_cache=InMemoryCache(),
        market_date=date(2026, 5, 25),
        sub_narratives_override=["A.", "B."],
    )
    assert len(seen_pinned) == 3  # 2^2 - 1 non-empty subsets
    assert all(p == ["covid-crash-2020", "lehman-gfc-2008"] for p in seen_pinned)


def test_compute_narrative_shapley_rejects_out_of_range_count():
    """N must be in [2, 4]."""
    base = _base_result()

    with pytest.raises(RuntimeError, match="2-4"):
        compute_narrative_shapley(
            base,
            config=_config(),
            gemini=None,
            cache=InMemoryCache(),
            decomposition_cache=InMemoryCache(),
            market_date=date(2026, 5, 25),
            sub_narratives_override=["only one"],
        )

    with pytest.raises(RuntimeError, match="2-4"):
        compute_narrative_shapley(
            base,
            config=_config(),
            gemini=None,
            cache=InMemoryCache(),
            decomposition_cache=InMemoryCache(),
            market_date=date(2026, 5, 25),
            sub_narratives_override=["a", "b", "c", "d", "e"],
        )


def test_decompose_scenario_validates_count(monkeypatch):
    """decompose_scenario() must raise on N<2 or N>4 returned by Gemini."""
    from app.llm.decomposition import decompose_scenario
    from app.llm.schemas import DecompositionOutput

    class _FakeClient:
        def __init__(self, count: int) -> None:
            self._count = count

        def decompose(self, scenario_text: str) -> DecompositionOutput:  # noqa: ARG002
            return DecompositionOutput(sub_narratives=[f"s{i}" for i in range(self._count)])

    # N=1 → raise
    with pytest.raises(RuntimeError, match=r"in \[2, 4\]"):
        decompose_scenario(
            "scenario",
            client=_FakeClient(1),
            cache=InMemoryCache(),
            market_date=date(2026, 5, 25),
            portfolio_key="us_tech_growth",
            model_id="gemini-3.5-flash",
        )

    # N=6 → raise
    with pytest.raises(RuntimeError, match=r"in \[2, 4\]"):
        decompose_scenario(
            "scenario",
            client=_FakeClient(6),
            cache=InMemoryCache(),
            market_date=date(2026, 5, 25),
            portfolio_key="us_tech_growth",
            model_id="gemini-3.5-flash",
        )
