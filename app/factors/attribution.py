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

    import shap  # local import: only paid when this code runs

    masker = shap.maskers.Impute(bg.to_numpy())
    explainer = shap.LinearExplainer((aggregated_coefs, 0.0), masker)

    shock_vec = np.array([[shocks.get(f, 0.0) for f in factor_names]])
    shap_values = explainer.shap_values(shock_vec)
    # shap may return either np.ndarray or Explanation; .shap_values is always an ndarray
    values = np.asarray(shap_values).reshape(-1)
    return {f: float(values[i]) for i, f in enumerate(factor_names)}
