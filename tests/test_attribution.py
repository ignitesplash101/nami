"""Unit tests for app.factors.attribution — synthetic data only, no network.

Conditional Shapley uses shap.LinearExplainer + shap.maskers.Impute against a synthetic
historical factor-return background. We test the Shapley axioms (efficiency, symmetry)
and the correlation-redistribution behavior that motivates this attribution choice.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.factors.attribution import (
    conditional_shapley_attribution,
    conditional_shapley_attribution_explicit,
    conditional_shapley_attribution_grouped,
    naive_attribution,
)


def _synthetic_history(
    n_rows: int,
    n_factors: int,
    *,
    correlation: float = 0.0,
    seed: int = 0,
) -> pd.DataFrame:
    """T × F demeaned synthetic factor-return history with shared correlation `ρ`.

    Constructs `X = sqrt(1-ρ) · independent + sqrt(ρ) · common_factor`, then demeans.
    """
    rng = np.random.default_rng(seed)
    independent = rng.standard_normal((n_rows, n_factors))
    common = rng.standard_normal((n_rows, 1))
    X = np.sqrt(1 - correlation) * independent + np.sqrt(correlation) * common
    X = X - X.mean(axis=0, keepdims=True)
    return pd.DataFrame(X, columns=[f"F{i}" for i in range(n_factors)])


def test_naive_attribution_sums_to_total():
    betas = pd.DataFrame(
        [[1.0, 0.5], [0.2, -0.3], [-0.4, 0.8]],
        index=["AAPL", "MSFT", "NVDA"],
        columns=["F0", "F1"],
    )
    weights = pd.Series({"AAPL": 0.4, "MSFT": 0.3, "NVDA": 0.3})
    shocks = {"F0": -0.07, "F1": 0.5}

    contribs = naive_attribution(betas, shocks, weights)
    expected_total = float((weights @ betas) @ pd.Series(shocks))
    np.testing.assert_allclose(sum(contribs.values()), expected_total, atol=1e-12)


def test_shapley_efficiency():
    """Sum of Conditional Shapley values ≈ (wᵀβ)·shock within float tolerance."""
    n_factors = 5
    bg = _synthetic_history(n_rows=400, n_factors=n_factors, correlation=0.5, seed=1)

    factor_names = list(bg.columns)
    betas = pd.DataFrame(
        np.eye(n_factors) * 1.2,
        index=[f"T{i}" for i in range(n_factors)],
        columns=factor_names,
    )
    weights = pd.Series({f"T{i}": 1.0 / n_factors for i in range(n_factors)})
    shocks = {"F0": -0.05, "F2": 0.04}

    phi = conditional_shapley_attribution(betas, shocks, weights, bg)

    aggregated = (weights @ betas).to_numpy()
    shock_vec = np.array([shocks.get(f, 0.0) for f in factor_names])
    expected_total = float(aggregated @ shock_vec)
    np.testing.assert_allclose(sum(phi.values()), expected_total, atol=1e-6)


def test_shapley_symmetry():
    """Two factors with identical coefs AND identical column-realizations → identical Shapley.

    Using literally-identical columns (rather than i.i.d. samples from the same
    distribution) tests the algorithmic Shapley-symmetry axiom directly. Two
    independent draws would only converge in tolerance as n_rows → ∞.
    """
    rng = np.random.default_rng(42)
    n_rows = 400
    shared = rng.standard_normal(n_rows)
    f2 = rng.standard_normal(n_rows)
    bg = pd.DataFrame({"F0": shared, "F1": shared.copy(), "F2": f2})
    bg = bg - bg.mean(axis=0)

    betas = pd.DataFrame(
        [[1.0, 1.0, 0.5]],
        index=["T0"],
        columns=["F0", "F1", "F2"],
    )
    weights = pd.Series({"T0": 1.0})
    shocks = {"F0": -0.03, "F1": -0.03, "F2": 0.02}

    phi = conditional_shapley_attribution(betas, shocks, weights, bg)
    np.testing.assert_allclose(phi["F0"], phi["F1"], atol=5e-4)


def test_shapley_high_corr_redistributes():
    """ρ=0.95 between F0 and F1; only F0 shocked. F1 must receive nonzero Conditional Shapley
    while Naive(F1) is exactly 0."""
    rng = np.random.default_rng(7)
    n_rows = 400
    common = rng.standard_normal(n_rows)
    eps = rng.standard_normal((n_rows, 2)) * np.sqrt(1 - 0.95)
    f0 = np.sqrt(0.95) * common + eps[:, 0]
    f1 = np.sqrt(0.95) * common + eps[:, 1]
    f2 = rng.standard_normal(n_rows)
    bg = pd.DataFrame({"F0": f0, "F1": f1, "F2": f2})
    bg = bg - bg.mean(axis=0)

    betas = pd.DataFrame(
        [[1.0, 1.0, 0.5]],
        index=["T0"],
        columns=["F0", "F1", "F2"],
    )
    weights = pd.Series({"T0": 1.0})
    shocks = {"F0": -0.05}  # only F0 shocked

    naive = naive_attribution(betas, shocks, weights)
    phi = conditional_shapley_attribution(betas, shocks, weights, bg)

    assert naive["F1"] == 0.0, "Naive must give zero to a non-shocked factor"
    assert (
        abs(phi["F1"]) > 1e-4
    ), f"Conditional Shapley should redistribute credit to correlated F1; got {phi['F1']}"


def test_shapley_independent_approx_naive():
    """Diagonal covariance ⇒ Conditional Shapley ≈ Naive per factor."""
    bg = _synthetic_history(n_rows=600, n_factors=4, correlation=0.0, seed=3)

    factor_names = list(bg.columns)
    betas = pd.DataFrame(
        [[1.0, 0.5, -0.3, 0.2]],
        index=["T0"],
        columns=factor_names,
    )
    weights = pd.Series({"T0": 1.0})
    shocks = {"F0": -0.04, "F1": 0.03, "F2": -0.02, "F3": 0.01}

    naive = naive_attribution(betas, shocks, weights)
    phi = conditional_shapley_attribution(betas, shocks, weights, bg)

    for f in factor_names:
        assert abs(phi[f] - naive[f]) < 5e-3, (
            f"{f}: under independence, Shapley≈Naive expected; "
            f"got naive={naive[f]:.4f}, shapley={phi[f]:.4f}"
        )


def test_shapley_raises_on_too_few_background_rows():
    bg = _synthetic_history(n_rows=10, n_factors=3, correlation=0.2)
    betas = pd.DataFrame(
        [[1.0, 0.5, -0.3]],
        index=["T0"],
        columns=list(bg.columns),
    )
    weights = pd.Series({"T0": 1.0})
    with pytest.raises(RuntimeError, match="≥52 complete rows"):
        conditional_shapley_attribution(betas, {"F0": -0.05}, weights, bg)


# ─── Explicit-only Shapley ────────────────────────────────────────────────


def test_explicit_only_zero_for_unshocked_factors():
    """ρ=0.9 between F0 and F1; only F0 shocked. Full Shapley redistributes credit
    to F1; explicit-only must keep F1 at exactly 0.0."""
    rng = np.random.default_rng(11)
    n_rows = 400
    common = rng.standard_normal(n_rows)
    eps = rng.standard_normal((n_rows, 2)) * np.sqrt(1 - 0.9)
    f0 = np.sqrt(0.9) * common + eps[:, 0]
    f1 = np.sqrt(0.9) * common + eps[:, 1]
    f2 = rng.standard_normal(n_rows)
    bg = pd.DataFrame({"F0": f0, "F1": f1, "F2": f2})
    bg = bg - bg.mean(axis=0)

    betas = pd.DataFrame(
        [[1.0, 1.0, 0.5]],
        index=["T0"],
        columns=["F0", "F1", "F2"],
    )
    weights = pd.Series({"T0": 1.0})
    shocks = {"F0": -0.05}  # only F0 shocked

    full = conditional_shapley_attribution(betas, shocks, weights, bg)
    explicit_only = conditional_shapley_attribution_explicit(betas, shocks, weights, bg)

    assert abs(full["F1"]) > 1e-4, "sanity: full Shapley should give nonzero F1"
    assert explicit_only["F1"] == 0.0
    assert explicit_only["F2"] == 0.0


def test_explicit_only_matches_full_when_all_factors_shocked():
    """When every factor has a nonzero shock, explicit-only is the full game."""
    bg = _synthetic_history(n_rows=600, n_factors=4, correlation=0.4, seed=21)
    factor_names = list(bg.columns)
    betas = pd.DataFrame(
        [[1.0, 0.5, -0.3, 0.2]],
        index=["T0"],
        columns=factor_names,
    )
    weights = pd.Series({"T0": 1.0})
    shocks = {"F0": -0.04, "F1": 0.03, "F2": -0.02, "F3": 0.01}

    full = conditional_shapley_attribution(betas, shocks, weights, bg)
    explicit_only = conditional_shapley_attribution_explicit(betas, shocks, weights, bg)

    # Mathematically identical games, but shap.LinearExplainer's transform-estimation
    # pass uses random sampling; ~1e-4 cross-call noise is expected.
    for f in factor_names:
        np.testing.assert_allclose(full[f], explicit_only[f], atol=1e-3)


def test_explicit_only_no_shocks_returns_all_zero():
    bg = _synthetic_history(n_rows=400, n_factors=3, correlation=0.2)
    betas = pd.DataFrame([[1.0, 0.5, -0.3]], index=["T0"], columns=list(bg.columns))
    weights = pd.Series({"T0": 1.0})
    result = conditional_shapley_attribution_explicit(betas, {}, weights, bg)
    assert set(result) == set(bg.columns)
    assert all(v == 0.0 for v in result.values())


# ─── Grouped Shapley ──────────────────────────────────────────────────────


def test_grouped_shapley_sums_to_factor_pnl():
    """Efficiency: Σ grouped Shapley values = factor-driven P&L (after redistribution)."""
    bg = _synthetic_history(n_rows=400, n_factors=4, correlation=0.3, seed=31)
    factor_names = list(bg.columns)
    betas = pd.DataFrame(
        [[1.0, 0.4, -0.2, 0.5]],
        index=["T0"],
        columns=factor_names,
    )
    weights = pd.Series({"T0": 1.0})
    shocks = {"F0": -0.05, "F2": 0.03}
    factor_group_map = {"F0": "g_a", "F1": "g_a", "F2": "g_b", "F3": "g_b"}

    grouped = conditional_shapley_attribution_grouped(betas, shocks, weights, bg, factor_group_map)

    expected_total = float(
        (weights @ betas).to_numpy() @ np.array([shocks.get(f, 0.0) for f in factor_names])
    )
    np.testing.assert_allclose(sum(grouped.values()), expected_total, atol=1e-6)


def test_grouped_shapley_collapses_within_group_correlation():
    """SPY ↔ ACWI scenario: F0 and F1 perfectly correlated in same group, only F0 shocked.
    Grouped Shapley puts all the group's credit on F0 (the LLM-shocked one) — within-group
    leakage is suppressed because the group is treated as one synthetic factor and the
    naive-weight redistribution sends credit to the factor whose shock is nonzero."""
    rng = np.random.default_rng(41)
    n_rows = 400
    shared = rng.standard_normal(n_rows)
    f2 = rng.standard_normal(n_rows)
    f3 = rng.standard_normal(n_rows)
    bg = pd.DataFrame({"F0": shared, "F1": shared.copy(), "F2": f2, "F3": f3})
    bg = bg - bg.mean(axis=0)

    betas = pd.DataFrame(
        [[1.0, 1.0, 0.4, -0.3]],
        index=["T0"],
        columns=["F0", "F1", "F2", "F3"],
    )
    weights = pd.Series({"T0": 1.0})
    shocks = {"F0": -0.05}  # only F0 shocked

    factor_group_map = {"F0": "market", "F1": "market", "F2": "macro", "F3": "macro"}

    full = conditional_shapley_attribution(betas, shocks, weights, bg)
    grouped = conditional_shapley_attribution_grouped(betas, shocks, weights, bg, factor_group_map)

    assert abs(full["F1"]) > 1e-4, "sanity: full Shapley redistributes to F1"
    # Within the market group, only F0 has a nonzero shock, so naive-weight
    # redistribution sends all market-group credit to F0; F1 stays at 0.
    assert grouped["F1"] == 0.0


def test_grouped_shapley_unmapped_factor_raises():
    bg = _synthetic_history(n_rows=400, n_factors=3, correlation=0.2)
    betas = pd.DataFrame([[1.0, 0.5, -0.3]], index=["T0"], columns=list(bg.columns))
    weights = pd.Series({"T0": 1.0})
    incomplete_map = {"F0": "g", "F1": "g"}  # F2 unmapped
    with pytest.raises(ValueError, match="Factors not in factor_group_map"):
        conditional_shapley_attribution_grouped(betas, {"F0": -0.04}, weights, bg, incomplete_map)
