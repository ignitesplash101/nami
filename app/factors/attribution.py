"""Factor-level attribution under independence (naive) and under the historical
conditional distribution (Conditional Shapley).

Conditional Shapley is NOT a causal "true" attribution. It is data-dependent credit
allocation under the conditional joint distribution of factor returns: a factor with
zero explicit LLM shock can still receive nonzero attribution because it is correlated
with one that WAS shocked. That's the price of axiomatic credit allocation, not a bug.

See `docs/methodology.md` for the framing.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def naive_attribution(
    betas: pd.DataFrame,
    shocks: dict[str, float],
    weights: pd.Series,
) -> dict[str, float]:
    """`by_factor` math: each factor's contribution is `(Σᵢ wᵢ · βᵢ,f) · shock[f]`.

    Sums exactly to the factor-driven portion of total P&L. Assumes factor independence —
    when factors are correlated (always, in practice), credit gets concentrated on the
    factor the LLM happened to name rather than distributed across its correlated peers.
    """
    factor_names = list(betas.columns)
    weighted_betas = betas.T @ weights.reindex(betas.index).fillna(0.0)
    return {f: float(weighted_betas[f] * shocks.get(f, 0.0)) for f in factor_names}


def conditional_shapley_attribution(
    betas: pd.DataFrame,
    shocks: dict[str, float],
    weights: pd.Series,
    factor_returns_history: pd.DataFrame,
    *,
    min_background_rows: int = 52,
) -> dict[str, float]:
    """Conditional Shapley values for the linear portfolio model under the historical
    factor-return distribution.

    NOT a causal/true contribution. A factor not explicitly shocked can receive nonzero
    attribution because the model's prediction at the conditional expectation differs
    from the prediction at the marginal expectation when factors are correlated.

    Uses shap's maskers API (the non-deprecated form):
        masker    = shap.maskers.Impute(background)
        explainer = shap.LinearExplainer((coefs, 0.0), masker)
    """
    factor_names = list(betas.columns)
    aggregated_coefs = (
        (weights.reindex(betas.index).fillna(0.0) @ betas)
        .reindex(factor_names)
        .fillna(0.0)
        .to_numpy()
    )  # F-vector: (wᵀβ) — the portfolio's exposure to each factor

    bg = factor_returns_history.reindex(columns=factor_names).dropna(how="any")
    if len(bg) < min_background_rows:
        raise RuntimeError(
            f"Conditional Shapley background needs ≥{min_background_rows} complete rows; "
            f"got {len(bg)}. Try a more recent date range or a smaller factor universe."
        )

    values = _shap_linear_values(
        coefs=aggregated_coefs,
        background=bg.to_numpy(),
        shock_vec=np.array([[shocks.get(f, 0.0) for f in factor_names]]),
    )
    return {f: float(values[i]) for i, f in enumerate(factor_names)}


def conditional_shapley_attribution_explicit(
    betas: pd.DataFrame,
    shocks: dict[str, float],
    weights: pd.Series,
    factor_returns_history: pd.DataFrame,
    *,
    min_background_rows: int = 52,
) -> dict[str, float]:
    """Conditional Shapley restricted to factors the LLM explicitly shocked.

    Unshocked factors stay at exactly 0.0 (matching naive's behavior for unshocked).
    Within the explicit sub-game, credit is allocated via Conditional Shapley using the
    historical conditional distribution among only the named factors.

    Under nami's demeaned-background contract (`fetch_factor_returns_history` demeans
    before this call), the sub-game's grand-coalition value equals
    `(wᵀβ_explicit) · shock_explicit`, which is the full factor-driven P&L: factors
    with shock=0 contribute 0 to factor-driven P&L by definition, so restricting the
    Shapley game to shocked factors preserves the total. The distinguishing property
    of this variant is **not** that the sum is smaller — it's that unshocked factors
    stay at **exactly zero** regardless of historical correlation. Full Conditional
    Shapley redistributes credit across correlated peers (including unshocked ones);
    explicit-only suppresses that redistribution for the unshocked side.

    Why this variant: matches the user mental model "what did the LLM shock?". The
    full-Shapley variant can credit ACWI/QUAL when only SPY was shocked, which reads
    as a bug to most users even though the math is consistent.
    """
    all_factor_names = list(betas.columns)
    zero_result = dict.fromkeys(all_factor_names, 0.0)

    explicit = [f for f in all_factor_names if shocks.get(f, 0.0) != 0.0]
    if not explicit:
        return zero_result

    weighted_betas_full = weights.reindex(betas.index).fillna(0.0) @ betas
    aggregated_coefs = (
        weighted_betas_full.reindex(explicit).fillna(0.0).to_numpy()
    )  # |explicit|-vector

    bg = factor_returns_history.reindex(columns=explicit).dropna(how="any")
    if len(bg) < min_background_rows:
        raise RuntimeError(
            f"Conditional Shapley background needs ≥{min_background_rows} complete rows; "
            f"got {len(bg)} after restricting to explicit factors. Try a more recent "
            "date range or pass a larger explicit shock set."
        )

    result = dict(zero_result)
    if len(explicit) == 1:
        # Trivial single-player Shapley: φ = v({1}) − v(∅) = coef · shock − 0.
        # shap.LinearExplainer's covariance path crashes on a 1-D background, so
        # short-circuit here. Also matches naive exactly for the singleton case.
        f = explicit[0]
        result[f] = float(aggregated_coefs[0] * shocks[f])
        return result

    shock_vec = np.array([[shocks[f] for f in explicit]])
    values = _shap_linear_values(
        coefs=aggregated_coefs,
        background=bg.to_numpy(),
        shock_vec=shock_vec,
    )
    for i, f in enumerate(explicit):
        result[f] = float(values[i])
    return result


def conditional_shapley_attribution_grouped(
    betas: pd.DataFrame,
    shocks: dict[str, float],
    weights: pd.Series,
    factor_returns_history: pd.DataFrame,
    factor_group_map: dict[str, str],
    *,
    min_background_rows: int = 52,
) -> dict[str, float]:
    """Group-flavored Conditional Shapley.

    Approach: run the full F-dim Conditional Shapley game (which preserves
    efficiency: Σ φ_f = factor-driven P&L), then sum φ_f within each group, then
    redistribute each group's sum to member factors proportionally to the
    within-group naive share `(wᵀβ)_f · shock[f]`. The aim is the SAME story but
    with within-group leakage collapsed onto whichever factor the LLM actually
    shocked.

    Why not aggregate features into a single synthetic factor per group? Because
    `(Σ_g c_f) · (Σ_g s_f)` introduces within-group cross-products `c_f · s_{f'}`
    that don't exist in the original linear model `Σ_f c_f · s_f`. The full-then-
    redistribute approach is mathematically clean.

    Properties:
        - Σ_f output[f] = factor-driven P&L (efficiency preserved).
        - Within each group, factors the LLM did not shock end up at 0 (they receive
          zero naive share, so zero redistributed share). The group's Shapley sum
          flows entirely to LLM-shocked members.
        - If a group has zero total naive share (no member was shocked), the sum
          φ_g is typically near zero too; we split it uniformly across members for
          transparency.
        - Cross-group leakage stays Shapley-allocated as in the full variant.

    `factor_group_map: factor_name -> group_name`. Every factor in `betas.columns`
    must be mapped — unmapped factors raise.
    """
    factor_names = list(betas.columns)
    unmapped = [f for f in factor_names if f not in factor_group_map]
    if unmapped:
        raise ValueError(f"Factors not in factor_group_map: {sorted(unmapped)}")

    full = conditional_shapley_attribution(
        betas,
        shocks,
        weights,
        factor_returns_history,
        min_background_rows=min_background_rows,
    )

    weighted_betas_full = weights.reindex(betas.index).fillna(0.0) @ betas

    groups: dict[str, list[str]] = {}
    for f in factor_names:
        groups.setdefault(factor_group_map[f], []).append(f)

    out: dict[str, float] = dict.fromkeys(factor_names, 0.0)
    for members in groups.values():
        group_shapley_sum = float(sum(full[f] for f in members))
        naive_shares = {
            f: float(weighted_betas_full.get(f, 0.0)) * float(shocks.get(f, 0.0)) for f in members
        }
        total_naive = float(sum(naive_shares.values()))
        if total_naive == 0.0:
            share = group_shapley_sum / len(members) if members else 0.0
            for f in members:
                out[f] = float(share)
        else:
            for f in members:
                out[f] = float(group_shapley_sum * naive_shares[f] / total_naive)
    return out


def _shap_linear_values(
    *,
    coefs: np.ndarray,
    background: np.ndarray,
    shock_vec: np.ndarray,
) -> np.ndarray:
    """Shared shap.LinearExplainer wrapper. Returns a 1-D ndarray of length F."""
    import shap  # local import: only paid when this code runs

    masker = shap.maskers.Impute(background)
    explainer = shap.LinearExplainer((coefs, 0.0), masker)
    raw = explainer.shap_values(shock_vec)
    return np.asarray(raw).reshape(-1)
