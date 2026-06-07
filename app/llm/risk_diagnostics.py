"""Deterministic, warning-only risk diagnostics for scenario outputs."""

from __future__ import annotations

import math
from itertools import combinations

import pandas as pd

from app.factors.universe import FACTORS
from app.llm.schemas import FactorShock, PortfolioPnL, RiskDiagnostic

MIN_MATERIAL_SHOCK = 0.01
MIN_MATERIAL_ENVELOPE_MEAN = 0.01
MIN_CROSS_CREDIT = 0.0025
POS_CORR_THRESHOLD = 0.75
NEG_CORR_THRESHOLD = -0.55
MAX_PAIR_DIAGNOSTICS = 6
MAX_CROSS_CREDIT_DIAGNOSTICS = 6


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
) -> list[RiskDiagnostic]:
    """Return review warnings without changing shocks or P&L.

    The checks are deliberately methodology-based rather than scenario-keyword
    based. A warning means "review the rationale"; it is not a hard failure.
    """
    diagnostics: list[RiskDiagnostic] = []
    explicit = {fs.factor: fs.shock for fs in factor_shocks if abs(fs.shock) >= MIN_MATERIAL_SHOCK}

    diagnostics.extend(_envelope_direction_conflicts(explicit, envelope))
    diagnostics.extend(_correlation_conflicts(explicit, factor_returns_history))
    diagnostics.extend(_conditional_cross_credit(explicit, portfolio_pnl))
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
