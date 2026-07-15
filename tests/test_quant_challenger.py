from __future__ import annotations

import pytest

from app.factors.quant_challenger import ChallengerCase, evaluate_challenger


def _passing_cases() -> list[ChallengerCase]:
    regions = ["north_america", "developed_ex_us", "japan"]
    horizons = [5, 21, 63]
    cases = []
    for index in range(12):
        realized = -0.12 + index * 0.01
        quant = realized + 0.005
        cases.append(
            ChallengerCase(
                case_id=f"case-{index}",
                region=regions[index % len(regions)],
                horizon=horizons[index % len(horizons)],
                legacy_pnl=realized + 0.04,
                quant_pnl=quant,
                quant_repeat_pnl=quant,
                realized_pnl=realized,
                range_p10=realized - 0.03,
                range_p90=realized + 0.03,
                neighbor_count=50,
                effective_sample_size=35.0,
            )
        )
    return cases


def test_challenger_passes_only_with_support_coverage_repeatability_and_improvement() -> None:
    report = evaluate_challenger(_passing_cases())

    assert report.promote
    assert all(gate.passed for gate in report.gates)
    assert report.quant_mae < report.legacy_mae
    assert report.quant_sign_hit_rate >= report.legacy_sign_hit_rate
    assert report.range_coverage == 1.0


def test_challenger_fails_closed_on_weak_support_or_missing_repeat() -> None:
    cases = _passing_cases()
    cases[0] = cases[0].model_copy(update={"effective_sample_size": 19.9, "quant_repeat_pnl": None})

    report = evaluate_challenger(cases)

    assert not report.promote
    failed = {gate.key for gate in report.gates if not gate.passed}
    assert "support" in failed
    assert "repeatability" in failed


def test_challenger_rejects_duplicate_cases_and_invalid_ranges() -> None:
    case = _passing_cases()[0]
    with pytest.raises(ValueError, match="Duplicate case_id"):
        evaluate_challenger([case, case])

    with pytest.raises(ValueError, match="range_p10"):
        ChallengerCase.model_validate({**case.model_dump(), "range_p10": 0.2, "range_p90": 0.1})


def test_challenger_rejects_or_fails_inconsistent_ess_and_neighbor_count() -> None:
    case = _passing_cases()[0]
    with pytest.raises(ValueError, match="effective_sample_size"):
        ChallengerCase.model_validate(
            {**case.model_dump(), "neighbor_count": 1, "effective_sample_size": 20.0}
        )

    cases = _passing_cases()
    cases[0] = cases[0].model_copy(update={"neighbor_count": 1, "effective_sample_size": 20.0})
    report = evaluate_challenger(cases)
    assert not next(gate for gate in report.gates if gate.key == "support").passed
