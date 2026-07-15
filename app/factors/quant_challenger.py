"""Deterministic offline promotion gates for the optional Quant V2 engine."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, model_validator

MIN_CHALLENGER_CASES = 12
MIN_EFFECTIVE_SAMPLE_SIZE = 20.0
MIN_RANGE_COVERAGE = 0.60
REPEAT_TOLERANCE = 1e-12
REQUIRED_REGIONS = frozenset({"north_america", "developed_ex_us", "japan"})
REQUIRED_HORIZONS = frozenset({5, 21, 63})


class ChallengerCase(BaseModel):
    """One paired, held-out legacy-versus-Quant observation."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    case_id: str
    region: Literal["north_america", "developed_ex_us", "japan", "generic"]
    horizon: Literal[5, 21, 63]
    legacy_pnl: float
    quant_pnl: float
    quant_repeat_pnl: float | None
    realized_pnl: float
    range_p10: float
    range_p90: float
    neighbor_count: int
    effective_sample_size: float

    @model_validator(mode="after")
    def validate_case(self) -> ChallengerCase:
        if not self.case_id.strip():
            raise ValueError("case_id must not be blank")
        if self.range_p10 > self.range_p90:
            raise ValueError("range_p10 must be <= range_p90")
        if self.neighbor_count <= 0:
            raise ValueError("neighbor_count must be positive")
        if self.effective_sample_size <= 0:
            raise ValueError("effective_sample_size must be positive")
        if self.effective_sample_size > self.neighbor_count:
            raise ValueError("effective_sample_size must be <= neighbor_count")
        return self


class ChallengerGate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    passed: bool
    detail: str


class ChallengerReport(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    promote: bool
    n_cases: int
    legacy_mae: float
    quant_mae: float
    legacy_sign_hit_rate: float
    quant_sign_hit_rate: float
    range_coverage: float
    max_repeat_delta: float | None
    gates: list[ChallengerGate]


def _sign_hit(modeled: np.ndarray, realized: np.ndarray) -> float:
    return float(np.mean((modeled >= 0.0) == (realized >= 0.0)))


def evaluate_challenger(cases: Sequence[ChallengerCase]) -> ChallengerReport:
    """Evaluate a paired held-out set and fail closed unless every gate passes."""
    if not cases:
        raise ValueError("At least one challenger case is required")
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("Duplicate case_id values are not allowed")

    realized = np.array([case.realized_pnl for case in cases], dtype=float)
    legacy = np.array([case.legacy_pnl for case in cases], dtype=float)
    quant = np.array([case.quant_pnl for case in cases], dtype=float)
    legacy_mae = float(np.mean(np.abs(legacy - realized)))
    quant_mae = float(np.mean(np.abs(quant - realized)))
    legacy_sign = _sign_hit(legacy, realized)
    quant_sign = _sign_hit(quant, realized)
    range_coverage = float(
        np.mean([case.range_p10 <= case.realized_pnl <= case.range_p90 for case in cases])
    )

    repeat_deltas = [
        abs(case.quant_pnl - case.quant_repeat_pnl)
        for case in cases
        if case.quant_repeat_pnl is not None
    ]
    repeats_complete = len(repeat_deltas) == len(cases)
    max_repeat_delta = max(repeat_deltas) if repeat_deltas else None
    regions = {case.region for case in cases}
    horizons = {case.horizon for case in cases}
    support_passed = all(
        MIN_EFFECTIVE_SAMPLE_SIZE <= case.effective_sample_size <= case.neighbor_count <= 50
        for case in cases
    )

    gates = [
        ChallengerGate(
            key="sample_size",
            passed=len(cases) >= MIN_CHALLENGER_CASES,
            detail=f"{len(cases)} cases; require at least {MIN_CHALLENGER_CASES}",
        ),
        ChallengerGate(
            key="domain_coverage",
            passed=regions >= REQUIRED_REGIONS and horizons >= REQUIRED_HORIZONS,
            detail=f"regions={sorted(regions)}; horizons={sorted(horizons)}",
        ),
        ChallengerGate(
            key="support",
            passed=support_passed,
            detail=(
                f"every case requires {MIN_EFFECTIVE_SAMPLE_SIZE:g} <= ESS " "<= neighbors <= 50"
            ),
        ),
        ChallengerGate(
            key="repeatability",
            passed=repeats_complete
            and max_repeat_delta is not None
            and max_repeat_delta <= REPEAT_TOLERANCE,
            detail=(
                "all repeats required; "
                f"max delta={max_repeat_delta if max_repeat_delta is not None else 'missing'}"
            ),
        ),
        ChallengerGate(
            key="mae",
            passed=quant_mae <= legacy_mae,
            detail=f"Quant MAE={quant_mae:.6f}; legacy MAE={legacy_mae:.6f}",
        ),
        ChallengerGate(
            key="sign_hit_rate",
            passed=quant_sign >= legacy_sign,
            detail=f"Quant={quant_sign:.1%}; legacy={legacy_sign:.1%}",
        ),
        ChallengerGate(
            key="range_coverage",
            passed=range_coverage >= MIN_RANGE_COVERAGE,
            detail=(
                f"held-out realized outcomes inside P10-P90={range_coverage:.1%}; "
                f"require >= {MIN_RANGE_COVERAGE:.0%}"
            ),
        ),
    ]
    return ChallengerReport(
        promote=all(gate.passed for gate in gates),
        n_cases=len(cases),
        legacy_mae=legacy_mae,
        quant_mae=quant_mae,
        legacy_sign_hit_rate=legacy_sign,
        quant_sign_hit_rate=quant_sign,
        range_coverage=range_coverage,
        max_repeat_delta=max_repeat_delta,
        gates=gates,
    )
