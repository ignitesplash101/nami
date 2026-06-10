"""Deterministic, warning-only risk diagnostics for scenario outputs."""

from __future__ import annotations

import math
from itertools import combinations

import pandas as pd

from app.factors.universe import FACTORS
from app.llm.schemas import (
    FactorShock,
    PeripheryShock,
    PortfolioPnL,
    RegressionQuality,
    RiskDiagnostic,
)

MIN_MATERIAL_SHOCK = 0.01
MIN_MATERIAL_ENVELOPE_MEAN = 0.01
MIN_CROSS_CREDIT = 0.0025
POS_CORR_THRESHOLD = 0.75
NEG_CORR_THRESHOLD = -0.55
MAX_PAIR_DIAGNOSTICS = 6
MAX_CROSS_CREDIT_DIAGNOSTICS = 6

# Below this in-sample R², the factor model explains little of a name's weekly
# variance, so its factor-implied scenario P&L likely understates true risk.
LOW_R2_THRESHOLD = 0.30
MAX_LOW_R2_DIAGNOSTICS = 6

# Advisory tier for periphery shocks (the hard ±0.75 band lives in
# app/llm/validation.py — that validator is retry-then-fail, this one warns).
PERIPHERY_ADVISORY_ABS = 0.35


def _display(factor: str) -> str:
    meta = FACTORS.get(factor)
    return f"{meta.display_name} ({factor})" if meta else factor


def _sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def generate_risk_diagnostics(
    *,
    factor_shocks: list[FactorShock],
    envelope: pd.DataFrame,
    factor_returns_history: pd.DataFrame | None,
    portfolio_pnl: PortfolioPnL,
    portfolio_holdings: dict[str, float] | None = None,
    periphery_shocks: list[PeripheryShock] | None = None,
    regression_quality: RegressionQuality | None = None,
) -> list[RiskDiagnostic]:
    """Return review warnings without changing shocks or P&L.

    The checks are deliberately methodology-based rather than scenario-keyword
    based. A warning means "review the rationale"; it is not a hard failure.
    The newer inputs default to None so older call sites stay valid; their
    checks are simply skipped when the input is absent.
    """
    diagnostics: list[RiskDiagnostic] = []
    explicit = {fs.factor: fs.shock for fs in factor_shocks if abs(fs.shock) >= MIN_MATERIAL_SHOCK}

    diagnostics.extend(_envelope_direction_conflicts(explicit, envelope))
    diagnostics.extend(_correlation_conflicts(explicit, factor_returns_history))
    diagnostics.extend(_conditional_cross_credit(explicit, portfolio_pnl))
    diagnostics.extend(_low_regression_r2(regression_quality))
    diagnostics.extend(_position_loss_floor(portfolio_pnl, portfolio_holdings))
    diagnostics.extend(_periphery_magnitude(periphery_shocks))
    diagnostics.extend(_periphery_dominance(portfolio_pnl))
    return diagnostics


def _envelope_direction_conflicts(
    explicit: dict[str, float], envelope: pd.DataFrame
) -> list[RiskDiagnostic]:
    diagnostics: list[RiskDiagnostic] = []
    for factor, shock in explicit.items():
        if factor not in envelope.index:
            continue
        row = envelope.loc[factor]
        mean = row.get("mean")
        count = row.get("count")
        if not _finite(mean) or not _finite(count):
            continue
        mean_value = float(mean)
        count_value = int(count)
        if count_value < 3 or abs(mean_value) < MIN_MATERIAL_ENVELOPE_MEAN:
            continue
        if _sign(shock) == _sign(mean_value):
            continue
        diagnostics.append(
            RiskDiagnostic(
                kind="envelope_direction_conflict",
                message=(
                    f"{_display(factor)} shock direction differs from the selected "
                    "analog envelope mean; review whether the narrative explains the divergence."
                ),
                factors=[factor],
                evidence={
                    "shock": float(shock),
                    "envelope_mean": mean_value,
                    "analog_count": count_value,
                },
            )
        )
    return diagnostics


def _correlation_conflicts(
    explicit: dict[str, float], factor_returns_history: pd.DataFrame | None
) -> list[RiskDiagnostic]:
    if factor_returns_history is None or len(explicit) < 2:
        return []

    available = [factor for factor in explicit if factor in factor_returns_history.columns]
    if len(available) < 2:
        return []

    corr = factor_returns_history[available].corr()
    diagnostics: list[RiskDiagnostic] = []
    for left, right in combinations(available, 2):
        rho = corr.loc[left, right]
        if not _finite(rho):
            continue
        rho_value = float(rho)
        same_sign = _sign(explicit[left]) == _sign(explicit[right])
        opposite_sign = _sign(explicit[left]) == -_sign(explicit[right])
        if rho_value >= POS_CORR_THRESHOLD and opposite_sign:
            diagnostics.append(
                _pair_diagnostic(
                    left,
                    right,
                    rho_value,
                    "highly positively correlated factors have opposite-signed explicit shocks",
                )
            )
        elif rho_value <= NEG_CORR_THRESHOLD and same_sign:
            diagnostics.append(
                _pair_diagnostic(
                    left,
                    right,
                    rho_value,
                    "historically negatively correlated factors have same-signed explicit shocks",
                )
            )

    diagnostics.sort(key=lambda item: abs(float(item.evidence.get("correlation", 0))), reverse=True)
    return diagnostics[:MAX_PAIR_DIAGNOSTICS]


def _pair_diagnostic(left: str, right: str, rho: float, issue: str) -> RiskDiagnostic:
    return RiskDiagnostic(
        kind="correlation_conflict",
        message=(
            f"{_display(left)} and {_display(right)}: {issue}; review whether the "
            "scenario narrative supports this rotation."
        ),
        factors=[left, right],
        evidence={"correlation": rho},
    )


def _low_regression_r2(regression_quality: RegressionQuality | None) -> list[RiskDiagnostic]:
    if regression_quality is None:
        return []
    rows = [
        (ticker, q) for ticker, q in regression_quality.by_ticker.items() if q.r2 < LOW_R2_THRESHOLD
    ]
    rows.sort(key=lambda item: item[1].r2)
    return [
        RiskDiagnostic(
            kind="low_regression_r2",
            message=(
                f"Factor model explains little of {ticker}'s weekly variance "
                f"(R² = {q.r2:.2f}, n = {q.n_obs}); factor-implied P&L likely "
                "understates this name's scenario risk."
            ),
            evidence={"ticker": ticker, "r2": float(q.r2), "n_obs": int(q.n_obs)},
        )
        for ticker, q in rows[:MAX_LOW_R2_DIAGNOSTICS]
    ]


def _position_loss_floor(
    portfolio_pnl: PortfolioPnL, portfolio_holdings: dict[str, float] | None
) -> list[RiskDiagnostic]:
    """Flag names whose MODELED return breaches -100% of the position.

    `by_ticker_total[t]` is the weight-multiplied contribution, so the
    per-position return is `by_ticker_total[t] / w_t`. The engine deliberately
    never clamps (linearity is the contract behind attribution sums and the
    client-side dollar view) — this diagnostic is the honest flag instead.
    """
    if not portfolio_holdings:
        return []
    diagnostics: list[RiskDiagnostic] = []
    for ticker, contribution in portfolio_pnl.by_ticker_total.items():
        weight = portfolio_holdings.get(ticker, 0.0)
        if weight <= 0.0:
            continue
        modeled_return = contribution / weight
        if modeled_return >= -1.0:
            continue
        diagnostics.append(
            RiskDiagnostic(
                kind="position_loss_exceeds_100pct",
                message=(
                    f"{ticker}'s modeled scenario return is {modeled_return:.1%} — the "
                    "linear factor model has no floor at -100%, so treat this as the "
                    "position being wiped out. Shocks are never clamped."
                ),
                evidence={
                    "ticker": ticker,
                    "modeled_return": float(modeled_return),
                    "weight": float(weight),
                },
            )
        )
    return diagnostics


def _periphery_magnitude(periphery_shocks: list[PeripheryShock] | None) -> list[RiskDiagnostic]:
    if not periphery_shocks:
        return []
    return [
        RiskDiagnostic(
            kind="periphery_magnitude",
            message=(
                f"Periphery shock on {ps.ticker} is {ps.shock:+.1%} — a large "
                "single-episode idiosyncratic move; review whether the narrative "
                "supports name-specific stress of this size."
            ),
            evidence={"ticker": ps.ticker, "shock": float(ps.shock)},
        )
        for ps in periphery_shocks
        if math.isfinite(ps.shock) and abs(ps.shock) > PERIPHERY_ADVISORY_ABS
    ]


def _periphery_dominance(portfolio_pnl: PortfolioPnL) -> list[RiskDiagnostic]:
    diagnostics: list[RiskDiagnostic] = []
    for ticker, periphery in portfolio_pnl.by_ticker_periphery.items():
        factor = portfolio_pnl.by_ticker_factor.get(ticker, 0.0)
        if abs(periphery) < MIN_CROSS_CREDIT or abs(periphery) <= abs(factor):
            continue
        diagnostics.append(
            RiskDiagnostic(
                kind="periphery_dominance",
                severity="info",
                message=(
                    f"The name-specific (periphery) shock, not the factor model, drives "
                    f"{ticker}'s modeled P&L; the factor attribution views do not "
                    "explain this name's result."
                ),
                evidence={
                    "ticker": ticker,
                    "periphery_contribution": float(periphery),
                    "factor_contribution": float(factor),
                },
            )
        )
    return diagnostics


def _conditional_cross_credit(
    explicit: dict[str, float], portfolio_pnl: PortfolioPnL
) -> list[RiskDiagnostic]:
    full = portfolio_pnl.by_factor_conditional_shapley
    if not full:
        return []

    rows = [
        (factor, contribution)
        for factor, contribution in full.items()
        if factor not in explicit and abs(contribution) >= MIN_CROSS_CREDIT
    ]
    rows.sort(key=lambda item: abs(item[1]), reverse=True)

    return [
        RiskDiagnostic(
            kind="conditional_cross_credit",
            severity="info",
            message=(
                f"{_display(factor)} receives full-conditional correlation credit "
                "despite no explicit scenario shock; do not read it as a causal driver."
            ),
            factors=[factor],
            evidence={"conditional_contribution": float(contribution)},
        )
        for factor, contribution in rows[:MAX_CROSS_CREDIT_DIAGNOSTICS]
    ]
