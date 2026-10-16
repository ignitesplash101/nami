"""Conditional-completion math: Ledoit–Wolf, Gaussian conditioning, relative basis."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from app.factors.completion import (
    complete_shocks,
    fit_relative_basis,
    ledoit_wolf_shrinkage,
    mahalanobis_distance,
    shrunk_covariance,
)
from app.factors.regression import estimate_betas_and_stats


def _cov(sd_a: float, sd_u: float, rho: float) -> pd.DataFrame:
    return pd.DataFrame(
        [[sd_a**2, rho * sd_a * sd_u], [rho * sd_a * sd_u, sd_u**2]],
        index=["A", "U"],
        columns=["A", "U"],
    )


def test_ledoit_wolf_matches_reference_implementation():
    sklearn_cov = pytest.importorskip("sklearn.covariance")
    rng = np.random.default_rng(7)
    X = rng.normal(size=(60, 8)) @ rng.normal(size=(8, 8))
    X = X - X.mean(axis=0)
    ours, delta = ledoit_wolf_shrinkage(X)
    ref, ref_delta = sklearn_cov.ledoit_wolf(X, assume_centered=True)
    np.testing.assert_allclose(ours, ref, rtol=1e-10, atol=1e-12)
    assert delta == pytest.approx(ref_delta, rel=1e-10)
    assert 0.0 <= delta <= 1.0


def test_shrunk_covariance_preserves_variances_and_shrinks_correlations():
    rng = np.random.default_rng(3)
    base = rng.normal(size=(40, 1))
    frame = pd.DataFrame(
        np.hstack([base + 0.3 * rng.normal(size=(40, 1)), 50.0 * base, rng.normal(size=(40, 1))]),
        columns=["a", "b", "c"],
    )
    cov, delta = shrunk_covariance(frame)
    sample = frame - frame.mean()
    np.testing.assert_allclose(np.diag(cov), (sample**2).mean().to_numpy(), rtol=1e-12)
    sample_corr = frame.corr().loc["a", "b"]
    shrunk_corr = cov.loc["a", "b"] / math.sqrt(cov.loc["a", "a"] * cov.loc["b", "b"])
    assert 0.0 < delta < 1.0
    assert abs(shrunk_corr) < abs(sample_corr)


def test_shrunk_covariance_rejects_flat_column():
    frame = pd.DataFrame({"a": [0.01, -0.02, 0.03], "flat": [0.0, 0.0, 0.0]})
    with pytest.raises(ValueError, match="flat"):
        shrunk_covariance(frame)


def test_identity_covariance_implies_zero_moves():
    cov = pd.DataFrame(np.eye(3), index=list("ABC"), columns=list("ABC"))
    out = complete_shocks(cov, {"A": -0.2})
    assert out.implied.to_dict() == {"B": 0.0, "C": 0.0}
    assert out.shocks["A"] == -0.2


def test_correlated_pair_recovers_regression_slope_and_residual_variance():
    out = complete_shocks(_cov(sd_a=0.02, sd_u=0.04, rho=0.8), {"A": -0.10})
    # E[U | A=a] = ρ σ_u/σ_a · a ; Var[U | A] = σ_u²(1−ρ²)
    assert out.implied["U"] == pytest.approx(0.8 * 0.04 / 0.02 * -0.10)
    assert out.conditional_cov.loc["U", "U"] == pytest.approx(0.04**2 * (1 - 0.8**2))


def test_conditional_mean_is_horizon_free():
    cov = _cov(0.02, 0.05, -0.6)
    weekly = complete_shocks(cov, {"A": 0.15})
    episode = complete_shocks(cov * 13.0, {"A": 0.15})
    assert episode.implied["U"] == pytest.approx(weekly.implied["U"])
    assert episode.conditional_cov.loc["U", "U"] == pytest.approx(
        13.0 * weekly.conditional_cov.loc["U", "U"]
    )


def test_no_anchors_and_all_anchors_edge_cases():
    cov = _cov(0.02, 0.03, 0.5)
    none = complete_shocks(cov, {})
    assert (none.implied == 0.0).all()
    pd.testing.assert_frame_equal(none.conditional_cov, cov)
    full = complete_shocks(cov, {"A": 0.1, "U": -0.2})
    assert full.implied.empty
    assert full.shocks.to_dict() == {"A": 0.1, "U": -0.2}


def test_unknown_anchor_raises():
    with pytest.raises(ValueError, match="ZZZ"):
        complete_shocks(_cov(0.02, 0.03, 0.5), {"ZZZ": 0.1})


def test_mahalanobis_one_dimensional_is_a_z_score():
    cov = _cov(0.02, 0.03, 0.5)
    assert mahalanobis_distance(cov, {"A": -0.12}, horizon_weeks=4.0) == pytest.approx(
        0.12 / (0.02 * 2.0)
    )
    with pytest.raises(ValueError):
        mahalanobis_distance(cov, {"A": 0.1}, horizon_weeks=0.0)


def _synthetic_factors(n: int = 200) -> pd.DataFrame:
    rng = np.random.default_rng(11)
    market = rng.normal(0.0, 0.02, n)
    return pd.DataFrame(
        {
            "SPY": market,
            "XLK": 1.2 * market + rng.normal(0.0, 0.01, n),
            "XLU": 0.5 * market + rng.normal(0.0, 0.012, n),
            "TNX": rng.normal(0.0, 0.03, n),
        },
        index=pd.date_range("2020-01-03", periods=n, freq="W-FRI"),
    )


def test_fit_relative_basis_recovers_market_loadings():
    frame = _synthetic_factors()
    basis = fit_relative_basis(frame, "SPY", ["XLK", "XLU"])
    for name in ("XLK", "XLU"):
        slope = np.polyfit(frame["SPY"], frame[name], 1)[0]
        assert basis.loadings[name] == pytest.approx(slope, rel=1e-10)
    rel = basis.returns(frame)
    assert abs(rel["XLK"].corr(rel["SPY"])) < 1e-10
    pd.testing.assert_series_equal(rel["TNX"], frame["TNX"])


def test_relative_basis_round_trip_and_market_requirement():
    basis = fit_relative_basis(_synthetic_factors(), "SPY", ["XLK", "XLU"])
    moves = {"SPY": -0.2, "XLK": -0.3, "TNX": 0.05}
    back = basis.to_absolute(basis.to_relative(moves))
    assert back == pytest.approx(moves)
    with pytest.raises(ValueError, match="SPY"):
        basis.to_relative({"XLK": -0.3})


def test_relative_basis_leaves_ols_pnl_invariant():
    frame = _synthetic_factors()
    rng = np.random.default_rng(5)
    tickers = pd.DataFrame(
        {
            "T1": 0.4 * frame["SPY"] + 0.9 * frame["XLK"] + rng.normal(0, 0.01, len(frame)),
            "T2": 0.7 * frame["XLU"] - 0.2 * frame["TNX"] + rng.normal(0, 0.01, len(frame)),
        },
        index=frame.index,
    )
    basis = fit_relative_basis(frame, "SPY", ["XLK", "XLU"])
    betas_raw, _ = estimate_betas_and_stats(tickers, frame, alpha=0.0)
    betas_rel, _ = estimate_betas_and_stats(tickers, basis.returns(frame), alpha=0.0)
    shock = {"SPY": -0.2, "XLK": -0.28, "XLU": -0.05, "TNX": -0.1}
    shock_rel = basis.to_relative(shock)
    pnl_raw = betas_raw @ pd.Series(shock)[betas_raw.columns]
    pnl_rel = betas_rel @ pd.Series(shock_rel)[betas_rel.columns]
    np.testing.assert_allclose(pnl_raw.to_numpy(), pnl_rel.to_numpy(), atol=1e-12)
