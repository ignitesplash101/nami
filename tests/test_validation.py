"""Validation tests for the semantic checks `validate_shock_proposal` runs on LLM output."""

from __future__ import annotations

import pandas as pd
import pytest

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


@pytest.mark.parametrize("count", [1, 2])
def test_validate_skips_band_check_when_count_below_3(count):
    """When an envelope row has count < 3 (e.g. MTUM with a pre-2013 analog
    picked), the [p10, p90] band collapses or nearly collapses and the band
    check is unenforceable. The validator must skip the band check for
    that factor, not reject the proposal.

    Parametrized over count=1 (single observation, p10 == p90 exactly) and
    count=2 (two observations, p10 != p90 but band is shaped by 2 points)
    because the contract is `count < 3`, not "count == 1 only".

    Regression: prior to this fix, `validate_shock_proposal` rejected any
    shock that wasn't bit-for-bit equal to the degenerate envelope value,
    which the LLM cannot reliably produce at the displayed precision.
    """
    envelope = pd.DataFrame(
        {
            "mean": [-0.3408],
            "p10": [-0.3408],
            "p90": [-0.3408 if count == 1 else -0.30],
            "count": [count],
        },
        index=["MTUM"],
    )
    out = ShockProposalOutput(
        factor_shocks=[
            FactorShock(factor="MTUM", shock=-0.50, reasoning="extreme outside band"),
        ],
        periphery_shocks=[],
        narrative="ok",
    )
    # -0.50 would be outside [p10, p90] under either count, but the band
    # check is skipped because count < 3.
    assert validate_shock_proposal(out, envelope=envelope, portfolio=_portfolio()) == []


def test_validate_still_enforces_band_at_count_3():
    """count >= 3 is the threshold — at exactly 3, the band check still fires."""
    envelope = pd.DataFrame(
        {
            "mean": [-0.05],
            "p10": [-0.10],
            "p90": [0.00],
            "count": [3],
        },
        index=["SPY"],
    )
    out = ShockProposalOutput(
        factor_shocks=[FactorShock(factor="SPY", shock=-0.50, reasoning="extreme")],
        periphery_shocks=[],
        narrative="ok",
    )
    errs = validate_shock_proposal(out, envelope=envelope, portfolio=_portfolio())
    assert any("outside the empirical envelope" in e for e in errs)
    assert any("n=3" in e for e in errs)  # message now carries the count
    # No "justify going outside in reasoning" — that phrase was misleading
    # (validator never reads the reasoning field).
    assert not any("justify going outside" in e for e in errs)


@pytest.mark.parametrize("shock", [0.75, -0.75, 0.10])
def test_validate_accepts_periphery_within_hard_band(shock):
    out = ShockProposalOutput(
        factor_shocks=[],
        periphery_shocks=[PeripheryShock(ticker="AAPL", shock=shock, reasoning="x")],
        narrative="ok",
    )
    assert validate_shock_proposal(out, envelope=_envelope(), portfolio=_portfolio()) == []


@pytest.mark.parametrize("shock", [0.76, -0.9, -1.0])
def test_validate_rejects_periphery_beyond_hard_band(shock):
    out = ShockProposalOutput(
        factor_shocks=[],
        periphery_shocks=[PeripheryShock(ticker="AAPL", shock=shock, reasoning="x")],
        narrative="ok",
    )
    errs = validate_shock_proposal(out, envelope=_envelope(), portfolio=_portfolio())
    assert any("|shock| must be <= 0.75" in e for e in errs)


@pytest.mark.parametrize("shock", [float("nan"), float("inf"), float("-inf")])
def test_validate_rejects_non_finite_periphery(shock):
    out = ShockProposalOutput(
        factor_shocks=[],
        periphery_shocks=[PeripheryShock(ticker="AAPL", shock=shock, reasoning="x")],
        narrative="ok",
    )
    errs = validate_shock_proposal(out, envelope=_envelope(), portfolio=_portfolio())
    assert any("not finite" in e for e in errs)


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
