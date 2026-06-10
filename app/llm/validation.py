"""Semantic validation of LLM shock proposals — checks pydantic can't.

Returns a list of human-readable error strings; the gemini_client formats them into
the retry prompt as bullets. An empty list means the proposal is acceptable.

Every returned string is BLOCKING: the retry loop re-asks once with the error list
embedded, and a second failure raises RuntimeError. The envelope band check applies
only when a factor's analog count is >= MIN_ENVELOPE_COUNT_FOR_BAND_CHECK. The
validator never reads the `reasoning` field — reasoning is for human review only
(pinned by tests/test_validation.py).
"""

from __future__ import annotations

import math

import pandas as pd

from app.data.sample_portfolios import Portfolio
from app.factors.universe import FACTORS
from app.llm.schemas import ShockProposalOutput

# Minimum analog-event count required to enforce the [p10, p90] band check.
# Below this, the band collapses (count=1: a single point; count=2: a 2-point
# span shaped entirely by interpolation) and rejecting on floating-point
# divergence between the LLM's displayed-precision output and the envelope
# is unjustifiable. Mirrored by the adjustment-side keep-or-remove carve-out in
# app/llm/adjust_validation.py, and in docs/methodology.md and CLAUDE.md.
MIN_ENVELOPE_COUNT_FOR_BAND_CHECK = 3

# Hard band for periphery (per-ticker idiosyncratic) shocks. Periphery has no
# historical envelope, but a single-episode idiosyncratic move beyond ±75% on
# top of the factor-driven move is outside this tool's plausible-stress scope —
# and anything <= -1.0 is economically impossible for a long position. The
# advisory tier (|shock| > 0.35) lives in app/llm/risk_diagnostics.py: this
# validator is retry-then-fail, so softer flags do not belong here.
MAX_ABS_PERIPHERY_SHOCK = 0.75


def validate_shock_proposal(
    output: ShockProposalOutput,
    *,
    envelope: pd.DataFrame,
    portfolio: Portfolio,
) -> list[str]:
    """Validate a `ShockProposalOutput` against the factor universe, envelope, and
    portfolio. Every error string is blocking: identity errors (unknown factor /
    unknown ticker / duplicates), periphery-magnitude violations, and envelope-band
    violations (enforced only at count >= MIN_ENVELOPE_COUNT_FOR_BAND_CHECK) all
    feed the same one-retry-then-fail loop in gemini_client.

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

    # --- Periphery shocks: tickers must be in the portfolio, no duplicates,
    # --- magnitude within the hard ±MAX_ABS_PERIPHERY_SHOCK band ---
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
        if not math.isfinite(ps.shock):
            errors.append(f"Periphery shock for '{ps.ticker}' is not finite: {ps.shock!r}.")
        elif abs(ps.shock) > MAX_ABS_PERIPHERY_SHOCK:
            errors.append(
                f"Periphery shock for '{ps.ticker}' is {ps.shock:.4f}; |shock| must be "
                f"<= {MAX_ABS_PERIPHERY_SHOCK}. Reduce the magnitude or move the effect "
                f"into factor shocks."
            )

    # --- Envelope band check (count >= 3): blocking after one retry ---
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
