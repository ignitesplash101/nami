"""Unit tests for app.factors.regression and app.factors.shocks. Synthetic data only — no network."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.data.sample_portfolios import Portfolio
from app.factors.regression import (
    InsufficientHistoryError,
    estimate_betas,
    estimate_betas_and_stats,
    regression_spec,
)
from app.factors.shocks import apply_shocks, portfolio_pnl


def _make_factor_returns(
    n_weeks: int,
    n_factors: int,
    mean: float = 0.0,
    seed: int = 42,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    data = rng.standard_normal((n_weeks, n_factors)) * 0.02 + mean
    idx = pd.date_range("2020-01-06", periods=n_weeks, freq="W")
    cols = [f"F{i}" for i in range(n_factors)]
    return pd.DataFrame(data, index=idx, columns=cols)


def _synth_ticker_returns(
    factors: pd.DataFrame,
    true_betas: np.ndarray,
    noise: float = 0.0001,
    seed: int = 7,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n_weeks = factors.shape[0]
    n_tickers = true_betas.shape[1]
    Y = factors.to_numpy() @ true_betas + rng.standard_normal((n_weeks, n_tickers)) * noise
    return pd.DataFrame(Y, index=factors.index, columns=[f"T{i}" for i in range(n_tickers)])


def test_estimate_betas_recovers_known_coefficients():
    factors = _make_factor_returns(n_weeks=200, n_factors=3, mean=0.0)
    true_betas = np.array(
        [
            [1.2, 0.5, -0.3],
            [0.0, 1.0, 0.4],
            [-0.5, 0.2, 0.8],
        ]
    )
    tickers = _synth_ticker_returns(factors, true_betas, noise=1e-4)

    estimated = estimate_betas(tickers, factors, alpha=0.001).to_numpy()
    np.testing.assert_allclose(estimated, true_betas.T, atol=0.05)


def test_estimate_betas_handles_nonzero_factor_means():
    # Mean-centering must absorb a strong drift; without it, betas would be biased.
    factors = _make_factor_returns(n_weeks=200, n_factors=3, mean=0.05)
    true_betas = np.array([[0.8, -0.4], [0.3, 0.9], [-0.6, 0.2]])
    tickers = _synth_ticker_returns(factors, true_betas, noise=1e-4)

    estimated = estimate_betas(tickers, factors, alpha=0.001).to_numpy()
    np.testing.assert_allclose(estimated, true_betas.T, atol=0.05)


def test_ridge_stabilizes_collinear_factors():
    rng = np.random.default_rng(123)
    n_weeks = 100
    f0 = rng.standard_normal(n_weeks) * 0.02
    f1 = f0.copy()  # perfectly correlated
    idx = pd.date_range("2020-01-06", periods=n_weeks, freq="W")
    factors = pd.DataFrame({"F0": f0, "F1": f1}, index=idx)
    tickers = pd.DataFrame({"T0": f0 * 1.5}, index=idx)

    betas = estimate_betas(tickers, factors, alpha=0.1).to_numpy()
    assert np.all(np.isfinite(betas))
    assert np.all(np.abs(betas) < 100)


def test_standardized_ridge_is_column_scale_invariant():
    # The property the standardized solve exists for: rescaling a factor column
    # rescales its beta exactly inversely (raw-unit output), leaving every other
    # beta unchanged. The pre-Phase-18 raw-units ridge fails this at alpha=0.1.
    factors = _make_factor_returns(n_weeks=200, n_factors=3, mean=0.0)
    true_betas = np.array(
        [
            [1.2, 0.5],
            [0.0, 1.0],
            [-0.5, 0.2],
        ]
    )
    tickers = _synth_ticker_returns(factors, true_betas, noise=1e-4)

    base = estimate_betas(tickers, factors, alpha=0.1)

    scaled_factors = factors.copy()
    scaled_factors["F1"] = scaled_factors["F1"] * 100.0
    scaled = estimate_betas(tickers, scaled_factors, alpha=0.1)

    np.testing.assert_allclose(
        scaled["F1"].to_numpy(), base["F1"].to_numpy() / 100.0, rtol=1e-9, atol=1e-12
    )
    for other in ("F0", "F2"):
        np.testing.assert_allclose(
            scaled[other].to_numpy(), base[other].to_numpy(), rtol=1e-9, atol=1e-12
        )


def test_alpha_shrinks_heterogeneous_vol_factors_homogeneously():
    # Independent factors with 5x different vol must shrink by the SAME ratio
    # under a visible alpha. The raw-units ridge would crush the low-vol factor.
    rng = np.random.default_rng(11)
    n_weeks = 200
    idx = pd.date_range("2020-01-06", periods=n_weeks, freq="W")
    factors = pd.DataFrame(
        {
            "LOW_VOL": rng.standard_normal(n_weeks) * 0.02,
            "HIGH_VOL": rng.standard_normal(n_weeks) * 0.10,
        },
        index=idx,
    )
    true_b = {"LOW_VOL": 1.0, "HIGH_VOL": 0.5}
    y = factors["LOW_VOL"] * true_b["LOW_VOL"] + factors["HIGH_VOL"] * true_b["HIGH_VOL"]
    tickers = pd.DataFrame({"T0": y + rng.standard_normal(n_weeks) * 1e-4}, index=idx)

    betas = estimate_betas(tickers, factors, alpha=25.0)
    ratio_low = betas.loc["T0", "LOW_VOL"] / true_b["LOW_VOL"]
    ratio_high = betas.loc["T0", "HIGH_VOL"] / true_b["HIGH_VOL"]

    assert 0.7 < ratio_low < 1.0
    assert 0.7 < ratio_high < 1.0
    assert abs(ratio_low - ratio_high) < 0.05


def test_zero_variance_factor_column_yields_zero_beta():
    factors = _make_factor_returns(n_weeks=120, n_factors=2, mean=0.0)
    factors["CONST"] = 0.0123  # zero variance after centering
    true_betas = np.array([[1.0], [0.5], [0.0]])
    tickers = _synth_ticker_returns(factors, true_betas, noise=1e-4)

    betas = estimate_betas(tickers, factors, alpha=0.1)
    assert betas.loc["T0", "CONST"] == 0.0
    np.testing.assert_allclose(betas.loc["T0", "F0"], 1.0, atol=0.05)


def test_per_ticker_mask_short_history_does_not_truncate_other_names():
    factors = _make_factor_returns(n_weeks=120, n_factors=3, mean=0.0)
    true_betas = np.array(
        [
            [1.2, 0.5],
            [0.0, 1.0],
            [-0.5, 0.2],
        ]
    )
    tickers = _synth_ticker_returns(factors, true_betas, noise=1e-4)
    tickers.iloc[:70, tickers.columns.get_loc("T1")] = np.nan  # T1: only 50 valid weeks

    betas_joint, stats_joint = estimate_betas_and_stats(tickers, factors, alpha=0.1)
    betas_solo, _ = estimate_betas_and_stats(tickers[["T0"]], factors, alpha=0.1)

    # T0's betas must be identical to a T0-only regression — the short-history
    # T1 no longer truncates the window for the rest of the book.
    np.testing.assert_allclose(
        betas_joint.loc["T0"].to_numpy(), betas_solo.loc["T0"].to_numpy(), atol=1e-12
    )
    assert np.all(np.isfinite(betas_joint.loc["T1"].to_numpy()))
    assert stats_joint["T0"].n_obs == 120
    assert stats_joint["T1"].n_obs == 50


def test_min_obs_floor_raises_naming_ticker():
    factors = _make_factor_returns(n_weeks=120, n_factors=2, mean=0.0)
    true_betas = np.array([[1.0, 0.8], [0.2, -0.1]])
    tickers = _synth_ticker_returns(factors, true_betas, noise=1e-4)
    tickers.iloc[:110, tickers.columns.get_loc("T1")] = np.nan  # T1: 10 valid weeks

    with pytest.raises(InsufficientHistoryError, match=r"T1 \(n=10\)"):
        estimate_betas_and_stats(tickers, factors, alpha=0.1)


def test_min_obs_floor_respects_override():
    factors = _make_factor_returns(n_weeks=120, n_factors=2, mean=0.0)
    true_betas = np.array([[1.0, 0.8], [0.2, -0.1]])
    tickers = _synth_ticker_returns(factors, true_betas, noise=1e-4)
    tickers.iloc[:110, tickers.columns.get_loc("T1")] = np.nan

    betas, stats = estimate_betas_and_stats(tickers, factors, alpha=0.1, min_obs=5)
    assert stats["T1"].n_obs == 10
    assert np.all(np.isfinite(betas.to_numpy()))


def test_estimate_betas_and_stats_fit_quality():
    factors = _make_factor_returns(n_weeks=200, n_factors=3, mean=0.0)
    true_betas = np.array([[1.2], [0.4], [-0.3]])
    clean = _synth_ticker_returns(factors, true_betas, noise=1e-4)
    rng = np.random.default_rng(99)
    noise_only = pd.DataFrame(
        {"NOISE": rng.standard_normal(len(factors)) * 0.03}, index=factors.index
    )
    tickers = pd.concat([clean, noise_only], axis=1)

    _, stats = estimate_betas_and_stats(tickers, factors, alpha=0.1)

    assert stats["T0"].r2 > 0.95
    assert stats["NOISE"].r2 < 0.2
    assert stats["T0"].n_obs == 200
    # Residual vol of the clean ticker is on the injected-noise scale, far below
    # the noise-only ticker's.
    assert stats["T0"].idio_vol_weekly < 0.001
    assert stats["NOISE"].idio_vol_weekly > 0.02
    for s in stats.values():
        assert 0.0 <= s.r2 <= 1.0


def test_regression_spec_format():
    spec = regression_spec(lookback_weeks=156, alpha=0.1)
    assert spec == "ridge-std-v2|lookback=156|alpha=0.1|min_obs=40"
    assert regression_spec(lookback_weeks=104, alpha=0.5, min_obs=30) == (
        "ridge-std-v2|lookback=104|alpha=0.5|min_obs=30"
    )


def test_apply_shocks_dot_product():
    betas = pd.DataFrame(
        [[1.0, 0.5], [0.2, -0.3]],
        index=["AAPL", "MSFT"],
        columns=["SPY", "VIX"],
    )
    shocks = {"SPY": -0.10, "VIX": 0.40}
    expected = pd.Series(
        [1.0 * -0.10 + 0.5 * 0.40, 0.2 * -0.10 + -0.3 * 0.40],
        index=["AAPL", "MSFT"],
        name="expected_return",
    )
    result = apply_shocks(betas, shocks)
    pd.testing.assert_series_equal(result, expected)


def test_apply_shocks_rejects_unknown_factor():
    betas = pd.DataFrame([[1.0]], index=["AAPL"], columns=["SPY"])
    with pytest.raises(ValueError, match="Unknown factors"):
        apply_shocks(betas, {"NOT_A_FACTOR": 0.5})


def test_portfolio_pnl_rejects_missing_ticker():
    betas = pd.DataFrame([[1.0]], index=["AAPL"], columns=["SPY"])
    portfolio = Portfolio(name="x", description="x", holdings={"AAPL": 0.5, "GHOST": 0.5})
    with pytest.raises(RuntimeError, match="missing rows"):
        portfolio_pnl(portfolio, betas, {"SPY": -0.05})


def test_portfolio_pnl_attribution_sums():
    betas = pd.DataFrame(
        [[1.0, 0.5], [0.2, -0.3], [-0.4, 0.8]],
        index=["AAPL", "MSFT", "NVDA"],
        columns=["SPY", "VIX"],
    )
    portfolio = Portfolio(
        name="test",
        description="test",
        holdings={"AAPL": 0.4, "MSFT": 0.3, "NVDA": 0.3},
    )
    shocks = {"SPY": -0.07, "VIX": 0.5}

    result = portfolio_pnl(portfolio, betas, shocks)

    assert isinstance(result["total_pnl"], float)
    np.testing.assert_allclose(
        sum(result["by_factor_naive"].values()),
        result["total_pnl"],
        atol=1e-10,
    )


def test_portfolio_pnl_returns_json_safe_dict():
    """Phase 4 invariant: every value must be a plain float or dict of floats — no pd.Series."""
    betas = pd.DataFrame([[1.0, 0.5]], index=["AAPL"], columns=["SPY", "VIX"])
    portfolio = Portfolio(name="x", description="x", holdings={"AAPL": 1.0})
    result = portfolio_pnl(portfolio, betas, {"SPY": -0.1, "VIX": 0.3})

    assert isinstance(result["total_pnl"], float)
    for key in ("by_factor_naive", "by_ticker_factor", "by_ticker_periphery", "by_ticker_total"):
        assert isinstance(result[key], dict), f"{key} should be a dict, got {type(result[key])}"
        for v in result[key].values():
            assert isinstance(v, float), f"{key} values must be float, got {type(v)}"


def test_portfolio_pnl_with_periphery_shocks():
    betas = pd.DataFrame(
        [[1.0, 0.0], [0.0, 1.0]],
        index=["AAPL", "MSFT"],
        columns=["SPY", "VIX"],
    )
    portfolio = Portfolio(
        name="x",
        description="x",
        holdings={"AAPL": 0.6, "MSFT": 0.4},
    )
    shocks = {"SPY": -0.10, "VIX": 0.50}
    periphery = {"AAPL": -0.15}

    result = portfolio_pnl(portfolio, betas, shocks, periphery_shocks=periphery)

    # AAPL: factor = 1.0 * -0.10 = -0.10; periphery = -0.15; total = -0.25; weighted = 0.6 * -0.25 = -0.15
    # MSFT: factor = 0.0 * -0.10 + 1.0 * 0.50 = 0.50; periphery = 0; total = 0.50; weighted = 0.4 * 0.50 = 0.20
    # total_pnl = -0.15 + 0.20 = 0.05
    np.testing.assert_allclose(result["total_pnl"], 0.05, atol=1e-10)
    np.testing.assert_allclose(result["by_ticker_total"]["AAPL"], -0.15, atol=1e-10)
    np.testing.assert_allclose(result["by_ticker_total"]["MSFT"], 0.20, atol=1e-10)
    np.testing.assert_allclose(
        result["by_ticker_periphery"]["AAPL"], -0.09, atol=1e-10
    )  # 0.6 * -0.15
    np.testing.assert_allclose(result["by_ticker_periphery"]["MSFT"], 0.0, atol=1e-10)


def test_portfolio_pnl_rejects_periphery_for_unknown_ticker():
    betas = pd.DataFrame([[1.0]], index=["AAPL"], columns=["SPY"])
    portfolio = Portfolio(name="x", description="x", holdings={"AAPL": 1.0})
    with pytest.raises(ValueError, match="Periphery shocks for tickers not in portfolio"):
        portfolio_pnl(portfolio, betas, {"SPY": -0.05}, periphery_shocks={"GHOST": -0.1})
