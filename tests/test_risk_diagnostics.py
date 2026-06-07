from __future__ import annotations

import pandas as pd

from app.llm.risk_diagnostics import generate_risk_diagnostics
from app.llm.schemas import FactorShock, PortfolioPnL


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
