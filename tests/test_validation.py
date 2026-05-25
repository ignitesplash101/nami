"""Validation tests for the semantic checks `validate_shock_proposal` runs on LLM output."""

from __future__ import annotations

import pandas as pd

from app.data.sample_portfolios import Portfolio
from app.llm.schemas import FactorShock, PeripheryShock, ShockProposalOutput
from app.llm.validation import validate_shock_proposal


def _portfolio() -> Portfolio:
    return Portfolio(
        name="test",
        description="test",
        holdings={"AAPL": 0.5, "MSFT": 0.5},
    )


def _envelope() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "mean": [-0.05, 0.20],
            "p10": [-0.10, 0.05],
            "p90": [0.00, 0.40],
            "count": [3, 3],
        },
        index=["SPY", "VIX"],
    )


def test_validate_shock_proposal_passes_clean_output():
    out = ShockProposalOutput(
        factor_shocks=[
            FactorShock(factor="SPY", shock=-0.05, reasoning="moderate selloff"),
            FactorShock(factor="VIX", shock=0.25, reasoning="vol spike"),
        ],
        periphery_shocks=[PeripheryShock(ticker="AAPL", shock=-0.03, reasoning="China")],
        narrative="ok",
    )
    assert validate_shock_proposal(out, envelope=_envelope(), portfolio=_portfolio()) == []


def test_validate_flags_unknown_factor():
    out = ShockProposalOutput(
        factor_shocks=[FactorShock(factor="NOT_A_FACTOR", shock=-0.05, reasoning="x")],
        periphery_shocks=[],
        narrative="ok",
    )
    errs = validate_shock_proposal(out, envelope=_envelope(), portfolio=_portfolio())
    assert any("Unknown factor 'NOT_A_FACTOR'" in e for e in errs)


def test_validate_flags_periphery_ticker_not_in_portfolio():
    out = ShockProposalOutput(
        factor_shocks=[],
        periphery_shocks=[PeripheryShock(ticker="GHOST", shock=-0.10, reasoning="x")],
        narrative="ok",
    )
    errs = validate_shock_proposal(out, envelope=_envelope(), portfolio=_portfolio())
    assert any("'GHOST'" in e and "NOT in the portfolio" in e for e in errs)


def test_validate_warns_on_out_of_envelope_shock():
    out = ShockProposalOutput(
        factor_shocks=[FactorShock(factor="SPY", shock=-0.50, reasoning="extreme")],
        periphery_shocks=[],
        narrative="ok",
    )
    errs = validate_shock_proposal(out, envelope=_envelope(), portfolio=_portfolio())
    assert any("outside the empirical envelope" in e for e in errs)


def test_validate_flags_duplicates():
    out = ShockProposalOutput(
        factor_shocks=[
            FactorShock(factor="SPY", shock=-0.05, reasoning="x"),
            FactorShock(factor="SPY", shock=-0.06, reasoning="dup"),
        ],
        periphery_shocks=[
            PeripheryShock(ticker="AAPL", shock=-0.01, reasoning="x"),
            PeripheryShock(ticker="AAPL", shock=-0.02, reasoning="dup"),
        ],
        narrative="ok",
    )
    errs = validate_shock_proposal(out, envelope=_envelope(), portfolio=_portfolio())
    assert any("Duplicate factor 'SPY'" in e for e in errs)
    assert any("Duplicate ticker 'AAPL'" in e for e in errs)
