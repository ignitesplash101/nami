"""Deterministic joint-historical Quant V2 scenario math."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def _state_levels(n: int = 700) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    index = pd.date_range("2018-01-02", periods=n, freq="B")
    levels = pd.DataFrame(
        {
            "VIX": 20 * np.exp(np.cumsum(rng.normal(0, 0.018, n))),
            "US_10Y_YIELD": 0.03 + np.cumsum(rng.normal(0, 0.00018, n)),
            "BROAD_DOLLAR": 100 * np.exp(np.cumsum(rng.normal(0, 0.002, n))),
            "WTI": 55 + np.cumsum(rng.normal(0, 0.7, n)),
            "HYG": 80 * np.exp(np.cumsum(rng.normal(0, 0.0025, n))),
            "SHY": 82 * np.exp(np.cumsum(rng.normal(0, 0.00045, n))),
        },
        index=index,
    )
    levels.loc[index[120], "WTI"] = -37.0
    return levels


def _factor_returns(index: pd.DatetimeIndex) -> pd.DataFrame:
    rng = np.random.default_rng(11)
    common = rng.normal(0, 0.009, len(index))
    return pd.DataFrame(
        {
            "NA:MKT_RF": common,
            "NA:SMB": 0.25 * common + rng.normal(0, 0.004, len(index)),
            "NA:MOM": -0.15 * common + rng.normal(0, 0.004, len(index)),
        },
        index=index,
    )


def _betas() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "NA:MKT_RF": [1.2, 0.7],
            "NA:SMB": [0.3, -0.1],
            "NA:MOM": [-0.2, 0.4],
        },
        index=["A", "B"],
    )


def _neutral_directions() -> dict[str, int]:
    return dict.fromkeys(("volatility", "rates", "dollar", "oil", "credit"), 0)


def test_state_transforms_are_fixed_horizon_robust_and_vintage_safe() -> None:
    from app.factors.quant_scenario import build_state_change_history

    levels = _state_levels(180)
    as_of = levels.index[150]
    changes = build_state_change_history(levels, horizon=5, as_of=as_of)

    assert list(changes.columns) == ["volatility", "rates", "dollar", "oil", "credit"]
    assert changes.index.max() <= as_of
    assert np.isfinite(changes.to_numpy()).all()
    expected_credit = np.log(levels["SHY"] / levels["HYG"]).diff(5).loc[as_of]
    assert changes.loc[as_of, "credit"] == pytest.approx(expected_credit)


def test_factor_windows_compound_over_exact_trading_horizon() -> None:
    from app.factors.quant_scenario import build_factor_outcome_history

    index = pd.date_range("2024-01-02", periods=6, freq="B")
    returns = pd.DataFrame({"F": [0.10] * 6}, index=index)
    outcomes = build_factor_outcome_history(returns, horizon=5, as_of=index[-1])

    assert outcomes.index.tolist() == [index[4], index[5]]
    assert outcomes.iloc[0, 0] == pytest.approx(1.1**5 - 1.0)


def test_joint_histories_roll_on_one_complete_calendar() -> None:
    from app.factors.quant_scenario import build_joint_histories

    levels = _state_levels(180)
    returns = _factor_returns(levels.index).drop(index=levels.index[10])
    states, outcomes = build_joint_histories(
        returns,
        levels,
        horizon=5,
        as_of=levels.index[-1],
    )

    assert states.index.equals(outcomes.index)
    endpoint = returns.index[10]
    aligned_start = returns.index[5]
    assert states.loc[endpoint, "rates"] == pytest.approx(
        levels.loc[endpoint, "US_10Y_YIELD"] - levels.loc[aligned_start, "US_10Y_YIELD"]
    )


def test_future_bad_rows_do_not_change_a_vintage_result() -> None:
    from app.factors.quant_scenario import (
        build_factor_outcome_history,
        build_state_change_history,
    )

    levels = _state_levels(180)
    factors = _factor_returns(levels.index)
    as_of = levels.index[-5]
    expected_states = build_state_change_history(levels, horizon=5, as_of=as_of)
    expected_factors = build_factor_outcome_history(factors, horizon=5, as_of=as_of)
    future_date = as_of + pd.Timedelta(days=10)
    bad_levels = pd.concat(
        [
            levels,
            pd.DataFrame(
                [[np.inf] * 6, [np.inf] * 6], index=[future_date] * 2, columns=levels.columns
            ),
        ]
    )
    bad_factors = pd.concat(
        [
            factors,
            pd.DataFrame(
                [[np.inf] * factors.shape[1], [np.inf] * factors.shape[1]],
                index=[future_date] * 2,
                columns=factors.columns,
            ),
        ]
    )

    pd.testing.assert_frame_equal(
        build_state_change_history(bad_levels, horizon=5, as_of=as_of),
        expected_states,
        check_freq=False,
    )
    pd.testing.assert_frame_equal(
        build_factor_outcome_history(bad_factors, horizon=5, as_of=as_of),
        expected_factors,
        check_freq=False,
    )


def test_shrinkage_covariance_is_finite_for_collinear_state_features() -> None:
    from app.factors.quant_scenario import estimate_shrinkage_covariance

    x = np.linspace(-2, 2, 100)
    frame = pd.DataFrame({"a": x, "b": 2 * x, "c": np.sin(x)})
    covariance = estimate_shrinkage_covariance(frame)

    assert covariance.shape == (3, 3)
    assert np.linalg.eigvalsh(covariance).min() > 0


def test_direction_filter_is_semantic_and_never_relaxed() -> None:
    from app.factors.quant_scenario import filter_state_directions

    history = pd.DataFrame(
        {
            "volatility": [1.0, 1.0, -1.0],
            "rates": [-1.0, 1.0, -1.0],
            "dollar": [0.0, 0.0, 0.0],
            "oil": [-1.0, -1.0, 1.0],
            "credit": [1.0, -1.0, 1.0],
        },
        index=pd.date_range("2024-01-01", periods=3),
    )
    directions = {"volatility": 1, "rates": -1, "dollar": 0, "oil": -1, "credit": 1}

    filtered = filter_state_directions(history, directions)

    assert filtered.index.tolist() == [history.index[0]]


def test_kernel_weights_and_effective_sample_floor() -> None:
    from app.factors.quant_scenario import (
        QuantModelDomainError,
        effective_sample_size,
        gaussian_kernel_weights,
        require_effective_sample_size,
    )

    weights = gaussian_kernel_weights(np.linspace(0.0, 2.0, 50), bandwidth=2.0)
    assert weights.sum() == pytest.approx(1.0)
    assert effective_sample_size(weights) > 40
    with pytest.raises(QuantModelDomainError, match="effective sample size"):
        require_effective_sample_size(np.array([0.99, *([0.01 / 49] * 49)]), minimum=20)


def test_weighted_medoid_is_an_observed_joint_factor_vector() -> None:
    from app.factors.quant_scenario import weighted_medoid

    outcomes = pd.DataFrame(
        {"F1": [0.0, 1.0, 10.0], "F2": [0.0, 1.0, 10.0]},
        index=pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03"]),
    )
    date = weighted_medoid(outcomes, np.array([0.2, 0.7, 0.1]))

    assert date == outcomes.index[1]
    assert outcomes.loc[date].tolist() == [1.0, 1.0]


def test_direct_attribution_reconciles_exactly_without_shapley() -> None:
    from app.factors.quant_scenario import direct_attribution

    shocks = pd.Series({"NA:MKT_RF": -0.10, "NA:SMB": 0.02, "NA:MOM": -0.03})
    result = direct_attribution(_betas(), {"A": 0.6, "B": 0.4}, shocks)

    expected_market = (0.6 * 1.2 + 0.4 * 0.7) * -0.10
    assert result.by_factor["NA:MKT_RF"] == pytest.approx(expected_market)
    assert sum(result.by_factor.values()) == pytest.approx(result.total_pnl)
    assert sum(result.by_ticker.values()) == pytest.approx(result.total_pnl)


def test_model_domain_rejects_query_beyond_observed_robust_support() -> None:
    from app.factors.quant_scenario import QuantModelDomainError, validate_model_domain

    rng = np.random.default_rng(2)
    history = pd.DataFrame(rng.normal(size=(200, 5)), columns=list("abcde"))
    with pytest.raises(QuantModelDomainError, match="outside historical support"):
        validate_model_domain(pd.Series([50.0] * 5, index=history.columns), history)


def test_historical_model_range_draws_are_seeded_joint_and_ordered() -> None:
    from app.factors.quant_scenario import historical_model_range

    outcomes = pd.DataFrame(
        {
            "NA:MKT_RF": [-0.20, -0.10, 0.0, 0.05],
            "NA:SMB": [0.03, 0.01, -0.01, 0.0],
            "NA:MOM": [-0.05, -0.02, 0.01, 0.02],
        }
    )
    weights = np.array([0.4, 0.3, 0.2, 0.1])
    first = historical_model_range(
        outcomes, weights, _betas(), {"A": 0.6, "B": 0.4}, severity=1.5, draws=4096, seed=17
    )
    second = historical_model_range(
        outcomes, weights, _betas(), {"A": 0.6, "B": 0.4}, severity=1.5, draws=4096, seed=17
    )

    assert first == second
    assert first.p10 <= first.p50 <= first.p90
    assert first.draws == 4096


def test_quant_scenario_uses_whole_vector_severity_and_at_most_50_neighbors() -> None:
    from app.factors.quant_scenario import run_quant_scenario

    levels = _state_levels()
    factors = _factor_returns(levels.index)
    event_dates = [levels.index[300], levels.index[420], levels.index[520]]
    kwargs = {
        "factor_returns": factors,
        "state_levels": levels,
        "betas": _betas(),
        "holdings": {"A": 0.6, "B": 0.4},
        "event_end_dates": event_dates,
        "directions": _neutral_directions(),
        "horizon": 21,
        "as_of": levels.index[-1],
        "range_draws": 2048,
        "range_seed": 3,
    }
    base = run_quant_scenario(severity=1.0, **kwargs)
    severe = run_quant_scenario(severity=2.0, **kwargs)

    assert severe.total_pnl == pytest.approx(2.0 * base.total_pnl)
    assert severe.factor_shocks == pytest.approx(
        {factor: 2.0 * value for factor, value in base.factor_shocks.items()}
    )
    assert base.support.neighbor_count <= 50
    assert base.support.effective_sample_size >= 20
    assert base.support.medoid_date in base.neighbor_dates
    assert set(base.factor_ranges) == set(base.factor_shocks)
    assert severe.factor_ranges["NA:MKT_RF"]["p10"] == pytest.approx(
        2.0 * base.factor_ranges["NA:MKT_RF"]["p10"]
    )


@pytest.mark.parametrize("horizon", [4, 20, 64])
def test_quant_scenario_rejects_non_contract_horizons(horizon: int) -> None:
    from app.factors.quant_scenario import run_quant_scenario

    levels = _state_levels(200)
    with pytest.raises(ValueError, match="horizon"):
        run_quant_scenario(
            factor_returns=_factor_returns(levels.index),
            state_levels=levels,
            betas=_betas(),
            holdings={"A": 0.6, "B": 0.4},
            event_end_dates=[levels.index[100], levels.index[150]],
            directions=_neutral_directions(),
            horizon=horizon,
            severity=1.0,
            as_of=levels.index[-1],
        )


def test_event_anchor_uses_last_joint_row_on_or_before_event_end() -> None:
    from app.factors.quant_scenario import build_event_query

    index = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-05"])
    history = pd.DataFrame(np.arange(15).reshape(3, 5), index=index, columns=list("abcde"))
    query, dates = build_event_query(history, [pd.Timestamp("2024-01-04")])

    assert dates == (pd.Timestamp("2024-01-03"),)
    pd.testing.assert_series_equal(query, history.loc["2024-01-03"], check_names=False)


def test_quant_scenario_rejects_event_after_as_of() -> None:
    from app.factors.quant_scenario import QuantModelDomainError, run_quant_scenario

    levels = _state_levels(300)
    as_of = levels.index[-5]
    with pytest.raises(QuantModelDomainError, match="after as_of"):
        run_quant_scenario(
            factor_returns=_factor_returns(levels.index),
            state_levels=levels,
            betas=_betas(),
            holdings={"A": 0.6, "B": 0.4},
            event_end_dates=[as_of + pd.Timedelta(days=1)],
            directions=_neutral_directions(),
            horizon=21,
            severity=1.0,
            as_of=as_of,
        )
