from __future__ import annotations

import pandas as pd
import pytest

from app.llm.risk_diagnostics import generate_risk_diagnostics
from app.llm.schemas import (
    AnalogReplay,
    AnalogReplayEntry,
    FactorShock,
    PeripheryShock,
    PortfolioPnL,
    RegressionQuality,
    TickerRegressionQuality,
)


def _pnl() -> PortfolioPnL:
    return PortfolioPnL(
        total_pnl=-0.1,
        by_factor_naive={"SPY": -0.08, "ACWI": 0.0, "VIX": 0.02},
        by_factor_conditional_shapley={"SPY": -0.05, "ACWI": 0.015, "VIX": -0.065},
        by_factor_conditional_shapley_explicit={"SPY": -0.08, "ACWI": 0.0, "VIX": 0.02},
        by_factor_conditional_shapley_grouped={"SPY": -0.08, "ACWI": 0.0, "VIX": 0.02},
        by_ticker_factor={"AAPL": -0.08},
        by_ticker_periphery={"AAPL": -0.02},
        by_ticker_total={"AAPL": -0.10},
    )


def test_risk_diagnostics_flags_positive_corr_opposite_signed_shocks():
    history = pd.DataFrame({"SPY": [-0.02, 0.01, 0.03], "ACWI": [-0.018, 0.012, 0.028]})
    envelope = pd.DataFrame(
        {"mean": [-0.02, -0.02], "p10": [-0.1, -0.1], "p90": [0.05, 0.05], "count": [3, 3]},
        index=["SPY", "ACWI"],
    )

    diagnostics = generate_risk_diagnostics(
        factor_shocks=[
            FactorShock(factor="SPY", shock=-0.05, reasoning="selloff"),
            FactorShock(factor="ACWI", shock=0.04, reasoning="rotation"),
        ],
        envelope=envelope,
        factor_returns_history=history,
        portfolio_pnl=_pnl(),
    )

    assert any(item.kind == "correlation_conflict" for item in diagnostics)


def test_risk_diagnostics_flags_envelope_direction_conflict():
    envelope = pd.DataFrame(
        {"mean": [-0.04], "p10": [-0.1], "p90": [0.02], "count": [4]},
        index=["SPY"],
    )

    diagnostics = generate_risk_diagnostics(
        factor_shocks=[FactorShock(factor="SPY", shock=0.03, reasoning="squeeze")],
        envelope=envelope,
        factor_returns_history=None,
        portfolio_pnl=_pnl(),
    )

    assert any(item.kind == "envelope_direction_conflict" for item in diagnostics)


def test_risk_diagnostics_flags_full_conditional_cross_credit():
    envelope = pd.DataFrame(
        {"mean": [-0.04], "p10": [-0.1], "p90": [0.02], "count": [4]},
        index=["SPY"],
    )

    diagnostics = generate_risk_diagnostics(
        factor_shocks=[FactorShock(factor="SPY", shock=-0.05, reasoning="selloff")],
        envelope=envelope,
        factor_returns_history=None,
        portfolio_pnl=_pnl(),
    )

    cross_credit = [item for item in diagnostics if item.kind == "conditional_cross_credit"]
    assert cross_credit
    assert {item.severity for item in cross_credit} == {"info"}
    assert any("ACWI" in item.factors for item in cross_credit)


def _empty_envelope() -> pd.DataFrame:
    return pd.DataFrame(columns=["mean", "p10", "p90", "count"])


def test_risk_diagnostics_flags_low_regression_r2_with_boundary():
    quality = RegressionQuality(
        estimator="ridge-std-v2",
        lookback_weeks=156,
        alpha=0.1,
        min_obs=40,
        by_ticker={
            "JUNK": TickerRegressionQuality(r2=0.21, n_obs=152, idio_vol_weekly=0.05),
            "OKAY": TickerRegressionQuality(r2=0.31, n_obs=152, idio_vol_weekly=0.01),
        },
    )
    diagnostics = generate_risk_diagnostics(
        factor_shocks=[FactorShock(factor="SPY", shock=-0.05, reasoning="selloff")],
        envelope=_empty_envelope(),
        factor_returns_history=None,
        portfolio_pnl=_pnl(),
        regression_quality=quality,
    )
    low = [d for d in diagnostics if d.kind == "low_regression_r2"]
    assert len(low) == 1  # 0.31 is above the 0.30 threshold — boundary non-fire
    assert low[0].severity == "warning"
    assert low[0].evidence["ticker"] == "JUNK"
    assert "understates" in low[0].message


def test_risk_diagnostics_flags_position_loss_beyond_100pct():
    pnl = PortfolioPnL(
        total_pnl=-0.649,
        by_factor_naive={"SPY": -0.649},
        by_ticker_factor={"WIPE": -0.55, "FINE": -0.099},
        by_ticker_periphery={"WIPE": 0.0, "FINE": 0.0},
        by_ticker_total={"WIPE": -0.55, "FINE": -0.099},
    )
    diagnostics = generate_risk_diagnostics(
        factor_shocks=[],
        envelope=_empty_envelope(),
        factor_returns_history=None,
        portfolio_pnl=pnl,
        # WIPE: -0.55 / 0.5 = -110% modeled return (fires).
        # FINE: -0.099 / 0.1 = -99% (no fire — the floor is the position, not the book).
        portfolio_holdings={"WIPE": 0.5, "FINE": 0.1},
    )
    floor = [d for d in diagnostics if d.kind == "position_loss_exceeds_100pct"]
    assert len(floor) == 1
    assert floor[0].evidence["ticker"] == "WIPE"
    assert floor[0].evidence["modeled_return"] == pytest.approx(-1.1)
    assert "never clamped" in floor[0].message


def test_risk_diagnostics_band_coverage_lists_unbanded_material_shocks():
    envelope = pd.DataFrame(
        {
            "mean": [-0.05, 0.5, -0.2],
            "p10": [-0.10, 0.1, -0.4],
            "p90": [0.02, 0.9, 0.0],
            "count": [4, 2, 0],
        },
        index=["SPY", "VIX", "XLE"],
    )
    diagnostics = generate_risk_diagnostics(
        factor_shocks=[
            FactorShock(factor="SPY", shock=-0.05, reasoning="banded"),
            FactorShock(factor="VIX", shock=2.0, reasoning="count=2, unbanded"),
            FactorShock(factor="XLE", shock=-0.30, reasoning="count=0, unbanded"),
            FactorShock(factor="XLK", shock=0.0, reasoning="removed — not material"),
        ],
        envelope=envelope,
        factor_returns_history=None,
        portfolio_pnl=_pnl(),
    )

    coverage = [d for d in diagnostics if d.kind == "band_coverage"]
    assert len(coverage) == 1
    item = coverage[0]
    assert sorted(item.factors) == ["VIX", "XLE"]
    assert "2 of 3" in item.message
    assert item.severity == "warning"  # 2/3 > half of material shocks unbanded


def test_risk_diagnostics_band_coverage_info_when_minority_unbanded():
    envelope = pd.DataFrame(
        {
            "mean": [-0.05, -0.03, 0.5],
            "p10": [-0.1, -0.08, 0.1],
            "p90": [0.02, 0.01, 0.9],
            "count": [4, 3, 1],
        },
        index=["SPY", "ACWI", "VIX"],
    )
    diagnostics = generate_risk_diagnostics(
        factor_shocks=[
            FactorShock(factor="SPY", shock=-0.05, reasoning="banded"),
            FactorShock(factor="ACWI", shock=-0.04, reasoning="banded"),
            FactorShock(factor="VIX", shock=0.6, reasoning="unbanded"),
        ],
        envelope=envelope,
        factor_returns_history=None,
        portfolio_pnl=_pnl(),
    )
    coverage = [d for d in diagnostics if d.kind == "band_coverage"]
    assert len(coverage) == 1
    assert coverage[0].severity == "info"
    assert coverage[0].factors == ["VIX"]


def test_risk_diagnostics_band_coverage_absent_when_all_banded():
    envelope = pd.DataFrame(
        {"mean": [-0.05], "p10": [-0.1], "p90": [0.02], "count": [4]},
        index=["SPY"],
    )
    diagnostics = generate_risk_diagnostics(
        factor_shocks=[FactorShock(factor="SPY", shock=-0.05, reasoning="banded")],
        envelope=envelope,
        factor_returns_history=None,
        portfolio_pnl=_pnl(),
    )
    assert not [d for d in diagnostics if d.kind == "band_coverage"]


def _replay(min_pnl: float, max_pnl: float) -> AnalogReplay:
    return AnalogReplay(
        per_event=[
            AnalogReplayEntry(
                event_id="covid-crash-2020",
                replay_pnl=min_pnl,
                n_factors_covered=22,
                n_factors_total=22,
            ),
            AnalogReplayEntry(
                event_id="q4-trade-war-2018",
                replay_pnl=max_pnl,
                n_factors_covered=22,
                n_factors_total=22,
            ),
        ],
        min_pnl=min_pnl,
        median_pnl=(min_pnl + max_pnl) / 2,
        max_pnl=max_pnl,
    )


def _pnl_total(total: float) -> PortfolioPnL:
    return PortfolioPnL(
        total_pnl=total,
        by_factor_naive={"SPY": total},
        by_ticker_factor={"AAPL": total},
        by_ticker_periphery={"AAPL": 0.0},
        by_ticker_total={"AAPL": total},
    )


@pytest.mark.parametrize(
    ("total", "direction"),
    [(-0.10, "milder"), (-0.50, "harsher")],
)
def test_risk_diagnostics_scenario_outside_replay_range(total, direction):
    diagnostics = generate_risk_diagnostics(
        factor_shocks=[FactorShock(factor="SPY", shock=total, reasoning="x")],
        envelope=_empty_envelope(),
        factor_returns_history=None,
        portfolio_pnl=_pnl_total(total),
        analog_replay=_replay(min_pnl=-0.35, max_pnl=-0.30),
    )
    flagged = [d for d in diagnostics if d.kind == "scenario_vs_replay"]
    assert len(flagged) == 1
    assert flagged[0].severity == "warning"
    assert flagged[0].evidence["direction"] == direction
    assert flagged[0].evidence["scenario_total_pnl"] == pytest.approx(total)


def test_risk_diagnostics_scenario_inside_replay_range_silent():
    diagnostics = generate_risk_diagnostics(
        factor_shocks=[FactorShock(factor="SPY", shock=-0.32, reasoning="x")],
        envelope=_empty_envelope(),
        factor_returns_history=None,
        portfolio_pnl=_pnl_total(-0.32),
        analog_replay=_replay(min_pnl=-0.35, max_pnl=-0.30),
    )
    assert not [d for d in diagnostics if d.kind == "scenario_vs_replay"]
    # And absent entirely without a replay block (old payloads).
    diagnostics = generate_risk_diagnostics(
        factor_shocks=[FactorShock(factor="SPY", shock=-0.32, reasoning="x")],
        envelope=_empty_envelope(),
        factor_returns_history=None,
        portfolio_pnl=_pnl_total(-0.32),
    )
    assert not [d for d in diagnostics if d.kind == "scenario_vs_replay"]


def test_risk_diagnostics_low_regression_dof():
    quality = RegressionQuality(
        estimator="ridge-std-v2",
        lookback_weeks=156,
        alpha=0.1,
        min_obs=40,
        by_ticker={
            # (40−1)/(22+1) ≈ 1.7 observations per effective parameter — fires.
            "THIN": TickerRegressionQuality(
                r2=0.9, n_obs=40, idio_vol_weekly=0.05, r2_adj=0.2, p_eff=22.0
            ),
            # (104−1)/(22+1) ≈ 4.5 — comfortably determined, no fire.
            "OK": TickerRegressionQuality(
                r2=0.9, n_obs=104, idio_vol_weekly=0.01, r2_adj=0.85, p_eff=22.0
            ),
            # Old cached payloads carry no p_eff — never fires.
            "LEGACY": TickerRegressionQuality(r2=0.9, n_obs=40, idio_vol_weekly=0.01),
        },
    )
    diagnostics = generate_risk_diagnostics(
        factor_shocks=[FactorShock(factor="SPY", shock=-0.05, reasoning="x")],
        envelope=_empty_envelope(),
        factor_returns_history=None,
        portfolio_pnl=_pnl(),
        regression_quality=quality,
    )
    low = [d for d in diagnostics if d.kind == "low_regression_dof"]
    assert len(low) == 1
    assert low[0].severity == "warning"
    assert low[0].evidence["ticker"] == "THIN"
    assert "effective parameter" in low[0].message


def test_risk_diagnostics_periphery_magnitude_and_dominance():
    pnl = PortfolioPnL(
        total_pnl=-0.05,
        by_factor_naive={"SPY": -0.01},
        by_ticker_factor={"AAPL": -0.01},
        by_ticker_periphery={"AAPL": -0.04},
        by_ticker_total={"AAPL": -0.05},
    )
    diagnostics = generate_risk_diagnostics(
        factor_shocks=[],
        envelope=_empty_envelope(),
        factor_returns_history=None,
        portfolio_pnl=pnl,
        periphery_shocks=[
            PeripheryShock(ticker="AAPL", shock=-0.40, reasoning="idio stress"),
            PeripheryShock(ticker="MSFT", shock=-0.34, reasoning="below advisory tier"),
        ],
    )
    mags = [d for d in diagnostics if d.kind == "periphery_magnitude"]
    assert [d.evidence["ticker"] for d in mags] == ["AAPL"]
    dom = [d for d in diagnostics if d.kind == "periphery_dominance"]
    assert len(dom) == 1
    assert dom[0].severity == "info"
    assert dom[0].evidence["ticker"] == "AAPL"
