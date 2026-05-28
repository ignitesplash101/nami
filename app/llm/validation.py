"""Semantic validation of LLM shock proposals — checks pydantic can't.

Returns a list of human-readable error strings; the gemini_client formats them into
the retry prompt as bullets. An empty list means the proposal is acceptable.
"""

from __future__ import annotations

import pandas as pd

from app.data.sample_portfolios import Portfolio
from app.factors.universe import FACTORS
from app.llm.schemas import ShockProposalOutput

# Minimum analog-event count required to enforce the [p10, p90] band check.
# Below this, the band collapses (count=1: a single point; count=2: a 2-point
# span shaped entirely by interpolation) and rejecting on floating-point
# divergence between the LLM's displayed-precision output and the envelope
# is unjustifiable. Mirrored in docs/methodology.md and CLAUDE.md.
MIN_ENVELOPE_COUNT_FOR_BAND_CHECK = 3


def validate_shock_proposal(
    output: ShockProposalOutput,
    *,
    envelope: pd.DataFrame,
    portfolio: Portfolio,
) -> list[str]:
    """Validate a `ShockProposalOutput` against the factor universe, envelope, and
    portfolio. Hard errors (unknown factor / unknown ticker / duplicate keys) become
    fail strings; soft warnings (shock outside [p10, p90]) become advisory strings.

    Order is stable so retry prompts are deterministic.
    """
    errors: list[str] = []

    # --- Factor shocks: known factors, no duplicates ---
    valid_factors = set(FACTORS.keys())
    seen_factors: set[str] = set()
    for fs in output.factor_shocks:
        if fs.factor not in valid_factors:
            errors.append(
                f"Unknown factor '{fs.factor}' in factor_shocks. "
                f"Valid factors: {sorted(valid_factors)}"
            )
        if fs.factor in seen_factors:
            errors.append(f"Duplicate factor '{fs.factor}' in factor_shocks.")
        seen_factors.add(fs.factor)

    # --- Periphery shocks: tickers must be in the portfolio, no duplicates ---
    valid_tickers = set(portfolio.holdings.keys())
    seen_tickers: set[str] = set()
    for ps in output.periphery_shocks:
        if ps.ticker not in valid_tickers:
            errors.append(
                f"Periphery shock for '{ps.ticker}' but that ticker is NOT in the "
                f"portfolio holdings. Valid tickers: {sorted(valid_tickers)}"
            )
        if ps.ticker in seen_tickers:
            errors.append(f"Duplicate ticker '{ps.ticker}' in periphery_shocks.")
        seen_tickers.add(ps.ticker)

    # --- Soft check: factor shocks within [p10, p90] of envelope ---
    for fs in output.factor_shocks:
        if fs.factor not in envelope.index:
            continue
        row = envelope.loc[fs.factor]
        p10, p90, count = row.get("p10"), row.get("p90"), row.get("count")
        if pd.isna(p10) or pd.isna(p90) or pd.isna(count):
            continue
        if count < MIN_ENVELOPE_COUNT_FOR_BAND_CHECK:
            continue
        if not (p10 <= fs.shock <= p90):
            errors.append(
                f"Factor '{fs.factor}' shock {fs.shock:.4f} is outside the empirical "
                f"envelope [p10={p10:.4f}, p90={p90:.4f}] (n={int(count)}). Move the "
                f"shock inside the band."
            )

    return errors
