"""Regional factor selection and prior-shrunk exposure contracts."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def _region_frame(index: pd.DatetimeIndex) -> pd.DataFrame:
    x = np.linspace(-0.02, 0.02, len(index))
    return pd.DataFrame(
        {
            "MKT_RF": x,
            "SMB": np.sin(np.arange(len(index))) * 0.005,
            "HML": np.cos(np.arange(len(index))) * 0.004,
            "RMW": np.sin(np.arange(len(index)) / 3) * 0.003,
            "CMA": np.cos(np.arange(len(index)) / 4) * 0.002,
            "MOM": np.sin(np.arange(len(index)) / 5) * 0.006,
            "RF": np.full(len(index), 0.0002),
        },
        index=index,
    )


def test_region_classification_has_safe_generic_fallback() -> None:
    from app.factors.quant_exposure import classify_region

    assert classify_region("RY", {"country": "Canada"}) == "north_america"
    assert classify_region("SAP", {"country": "Germany"}) == "developed_ex_us"
    assert classify_region("7203.T", {"country": "Japan"}) == "japan"
    assert classify_region("7203.T", None) == "japan"
    assert classify_region("7203.T", {"country": "Unknown"}) == "japan"
    assert classify_region("CUSTOM", None) == "generic"
    assert classify_region("CUSTOM", {"country": "Unknown"}) == "generic"


def test_us_industry_mapping_is_not_applied_outside_the_us() -> None:
    from app.factors.quant_exposure import industry_factor_for_holding

    assert (
        industry_factor_for_holding({"country": "United States", "sector": "Technology"}) == "BusEq"
    )
    assert industry_factor_for_holding({"country": "Canada", "sector": "Technology"}) is None
    assert industry_factor_for_holding(None) is None


def test_us_industry_leg_is_excess_over_total_regional_market() -> None:
    from app.factors.quant_exposure import build_holding_factor_set

    index = pd.date_range("2024-01-02", periods=3, freq="B")
    north_america = _region_frame(index)
    industries = pd.DataFrame({"BusEq": [0.03, -0.01, 0.02]}, index=index)
    factor_set = build_holding_factor_set(
        "AAPL",
        {"country": "United States", "sector": "Technology"},
        regional_factors={"north_america": north_america},
        us_industries=industries,
        end="2024-01-05",
    )

    expected = industries["BusEq"] - (north_america["MKT_RF"] + north_america["RF"])
    pd.testing.assert_series_equal(factor_set.factors["US_IND:BusEq"], expected, check_names=False)
    assert factor_set.prior["NA:MKT_RF"] == 1.0
    assert factor_set.prior["US_IND:BusEq"] == 1.0
    assert factor_set.industry_factor == "BusEq"
    assert factor_set.industry_mapping == "coarse-sector-to-ff12-v1"


def test_known_region_never_silently_falls_back_when_its_data_is_missing() -> None:
    from app.factors.quant_exposure import build_holding_factor_set

    index = pd.date_range("2024-01-02", periods=3, freq="B")
    with pytest.raises(ValueError, match="north_america"):
        build_holding_factor_set(
            "AAPL",
            {"country": "United States", "sector": "Technology"},
            regional_factors={"generic": _region_frame(index)},
            us_industries=None,
            end=index[-1],
        )


def test_exposure_uses_stock_excess_returns() -> None:
    from app.factors.quant_exposure import build_holding_factor_set, estimate_exposure

    index = pd.date_range("2021-01-04", periods=800, freq="B")
    regional = _region_frame(index)
    factor_set = build_holding_factor_set(
        "CUSTOM",
        None,
        regional_factors={"generic": regional},
        us_industries=None,
        end=index[-1],
    )
    total_stock_return = regional["RF"] + 1.4 * regional["MKT_RF"]
    estimate = estimate_exposure("CUSTOM", total_stock_return, factor_set, end=index[-1])

    assert estimate.tier == "estimated"
    assert estimate.n_obs == 160
    assert estimate.coefficients["DEV:MKT_RF"] == pytest.approx(1.4, abs=0.08)


def test_exposure_tiers_and_priors_are_explicit() -> None:
    from app.factors.quant_exposure import build_holding_factor_set, estimate_exposure

    long_index = pd.date_range("2021-01-04", periods=800, freq="B")
    regional = _region_frame(long_index)
    factor_set = build_holding_factor_set(
        "AAPL",
        {"country": "United States", "sector": "Technology"},
        regional_factors={"north_america": regional},
        us_industries=pd.DataFrame({"BusEq": regional["MKT_RF"] + regional["RF"]}),
        end=long_index[-1],
    )
    returns = regional["RF"] + 1.8 * regional["MKT_RF"]

    estimated = estimate_exposure("AAPL", returns, factor_set, end=long_index[-1])
    strong = estimate_exposure("AAPL", returns.iloc[:500], factor_set, end=long_index[499])
    proxy = estimate_exposure("AAPL", returns.iloc[:250], factor_set, end=long_index[249])

    assert estimated.tier == "estimated"
    assert strong.tier == "strongly_shrunk"
    assert 1.0 < strong.coefficients["NA:MKT_RF"] < 1.8
    assert proxy.tier == "prior_proxy"
    assert proxy.coefficients == proxy.prior
    assert proxy.coefficients["NA:MKT_RF"] == 1.0
    assert proxy.coefficients["US_IND:BusEq"] == 1.0
    assert all(
        value == 0.0
        for key, value in proxy.coefficients.items()
        if key not in {"NA:MKT_RF", "US_IND:BusEq"}
    )


def test_exposure_shrinkage_is_continuous_at_estimated_boundary() -> None:
    from app.factors.quant_exposure import build_holding_factor_set, estimate_exposure

    index = pd.date_range("2021-01-04", periods=800, freq="B")
    regional = _region_frame(index)
    factor_set = build_holding_factor_set(
        "CUSTOM",
        None,
        regional_factors={"generic": regional},
        us_industries=None,
        end=index[-1],
    )
    returns = regional["RF"] + 1.8 * regional["MKT_RF"]

    week_155 = estimate_exposure("CUSTOM", returns.iloc[:775], factor_set, end=index[774])
    week_156 = estimate_exposure("CUSTOM", returns.iloc[:780], factor_set, end=index[779])

    assert week_155.tier == "strongly_shrunk"
    assert week_156.tier == "estimated"
    assert week_155.data_weight == pytest.approx(103 / 104)
    assert week_156.data_weight == 1.0
    assert abs(week_156.coefficients["DEV:MKT_RF"] - week_155.coefficients["DEV:MKT_RF"]) < 0.03


def test_history_slice_is_capped_at_five_years_and_has_no_lookahead() -> None:
    from app.factors.quant_exposure import slice_history

    index = pd.to_datetime(["2018-12-31", "2019-01-02", "2024-01-02", "2024-01-03"])
    frame = pd.DataFrame({"value": [1, 2, 3, 999]}, index=index)
    result = slice_history(frame, end="2024-01-02")

    assert result.index.min() == pd.Timestamp("2019-01-02")
    assert result.index.max() == pd.Timestamp("2024-01-02")
    assert 999 not in result["value"].tolist()


def test_two_year_exponential_half_life_is_pinned() -> None:
    from app.factors.quant_exposure import exponential_history_weights

    index = pd.DatetimeIndex(["2022-01-03", "2024-01-03"])
    weights = exponential_history_weights(index, end="2024-01-03")
    assert weights.iloc[0] / weights.iloc[1] == pytest.approx(0.5, rel=0.002)
    assert weights.mean() == pytest.approx(1.0)


def test_daily_sources_compound_to_weekly_before_alignment() -> None:
    from app.factors.quant_exposure import compound_weekly_returns

    factors = pd.DataFrame(
        {"factor": [0.10, 0.10]}, index=pd.to_datetime(["2024-01-01", "2024-01-02"])
    )
    stock = pd.DataFrame(
        {"stock": [0.20, 0.20]}, index=pd.to_datetime(["2024-01-02", "2024-01-03"])
    )

    weekly_factors = compound_weekly_returns(factors)
    weekly_stock = compound_weekly_returns(stock)

    assert weekly_factors.iloc[0, 0] == pytest.approx(0.21)
    assert weekly_stock.iloc[0, 0] == pytest.approx(0.44)


def test_partial_week_is_labeled_at_last_observation_without_lookahead() -> None:
    from app.factors.quant_exposure import build_holding_factor_set, estimate_exposure

    index = pd.date_range(end="2024-01-03", periods=300, freq="B")
    regional = _region_frame(index)
    factor_set = build_holding_factor_set(
        "CUSTOM",
        None,
        regional_factors={"generic": regional},
        us_industries=None,
        end=index[-1],
    )
    returns = regional["RF"] + regional["MKT_RF"]

    estimate = estimate_exposure("CUSTOM", returns, factor_set, end=index[-1])

    assert index[-1].day_name() == "Wednesday"
    assert estimate.tier == "strongly_shrunk"


def test_portfolio_estimator_keeps_unknown_custom_holdings_modelable() -> None:
    from app.factors.quant_exposure import estimate_portfolio_exposures

    index = pd.date_range("2023-01-02", periods=300, freq="B")
    regional = _region_frame(index)
    returns = pd.DataFrame(
        {"CUSTOM": regional["RF"] + regional["MKT_RF"]},
        index=index,
    )
    betas, diagnostics = estimate_portfolio_exposures(
        returns,
        metadata={},
        regional_factors={"generic": regional},
        us_industries=None,
        end=index[-1],
    )

    assert list(betas.index) == ["CUSTOM"]
    assert diagnostics["CUSTOM"].region == "generic"
    assert diagnostics["CUSTOM"].tier == "strongly_shrunk"
    assert "DEV:MKT_RF" in betas.columns


def test_zero_overlap_fails_instead_of_emitting_plausible_prior_betas() -> None:
    from app.factors.quant_exposure import build_holding_factor_set, estimate_exposure

    factor_index = pd.date_range("2023-01-02", periods=300, freq="B")
    stock_index = pd.date_range("2010-01-04", periods=20, freq="B")
    factor_set = build_holding_factor_set(
        "CUSTOM",
        None,
        regional_factors={"generic": _region_frame(factor_index)},
        us_industries=None,
        end=factor_index[-1],
    )
    stock = pd.Series(0.0, index=stock_index)

    with pytest.raises(ValueError, match="no overlapping weekly"):
        estimate_exposure("CUSTOM", stock, factor_set, end=factor_index[-1])
