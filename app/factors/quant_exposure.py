"""Regional, prior-shrunk equity exposures for the optional Quant V2 engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

Region = Literal["north_america", "developed_ex_us", "japan", "generic"]
ExposureTier = Literal["estimated", "strongly_shrunk", "prior_proxy"]

MIN_PROXY_OBSERVATIONS = 52
FULL_ESTIMATE_OBSERVATIONS = 156
MAX_HISTORY_YEARS = 5
HALF_LIFE_YEARS = 2.0
EXPOSURE_RIDGE_ALPHA = 1.0
INDUSTRY_MAPPING_SPEC = "coarse-sector-to-ff12-v1"
QUANT_EXPOSURE_SPEC = (
    "regional-prior-ridge-v1|frequency=weekly|history=5y|half_life=2y|"
    "proxy=52|estimated=156|alpha=1"
)

_REGION_PREFIX: dict[Region, str] = {
    "north_america": "NA",
    "developed_ex_us": "DMX",
    "japan": "JP",
    "generic": "DEV",
}
_FACTOR_COLUMNS = ("MKT_RF", "SMB", "HML", "RMW", "CMA", "MOM")
_DEVELOPED_EX_US_COUNTRIES = frozenset(
    {
        "australia",
        "austria",
        "belgium",
        "denmark",
        "finland",
        "france",
        "germany",
        "hong kong",
        "ireland",
        "israel",
        "italy",
        "netherlands",
        "new zealand",
        "norway",
        "portugal",
        "singapore",
        "spain",
        "sweden",
        "switzerland",
        "united kingdom",
    }
)
_SECTOR_TO_INDUSTRY = {
    "basic materials": "Chems",
    "communication services": "Telcm",
    "consumer cyclical": "Shops",
    "consumer defensive": "NoDur",
    "energy": "Enrgy",
    "financial services": "Money",
    "healthcare": "Hlth",
    "industrials": "Manuf",
    "real estate": "Other",
    "technology": "BusEq",
    "utilities": "Utils",
}


@dataclass(frozen=True)
class HoldingFactorSet:
    ticker: str
    region: Region
    factors: pd.DataFrame
    risk_free: pd.Series
    prior: dict[str, float]
    industry_factor: str | None
    industry_mapping: str | None


@dataclass(frozen=True)
class ExposureEstimate:
    ticker: str
    region: Region
    tier: ExposureTier
    n_obs: int
    coefficients: dict[str, float]
    prior: dict[str, float]
    data_weight: float
    industry_factor: str | None
    industry_mapping: str | None


def classify_region(ticker: str, metadata: dict[str, str] | None) -> Region:
    """Classify known developed listings and fall back to broad developed factors."""
    country = (metadata or {}).get("country", "").strip().casefold()
    if country in {"united states", "united states of america", "canada"}:
        return "north_america"
    if country == "japan" or (country in {"", "unknown"} and ticker.upper().endswith(".T")):
        return "japan"
    if country in _DEVELOPED_EX_US_COUNTRIES:
        return "developed_ex_us"
    return "generic"


def industry_factor_for_holding(metadata: dict[str, str] | None) -> str | None:
    """Return a 12-industry key for US holdings only."""
    if not metadata or metadata.get("country", "").strip().casefold() not in {
        "united states",
        "united states of america",
    }:
        return None
    return _SECTOR_TO_INDUSTRY.get(metadata.get("sector", "").strip().casefold())


def _normalize_datetime_index(frame: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    result = frame.copy()
    index = pd.DatetimeIndex(pd.to_datetime(result.index)).tz_localize(None)
    if index.has_duplicates:
        raise ValueError("history contains duplicate dates")
    result.index = index
    return result.sort_index()


def slice_history(frame: pd.DataFrame | pd.Series, *, end: object) -> pd.DataFrame | pd.Series:
    """Return at most five trailing years ending at ``end`` with no look-ahead."""
    normalized = _normalize_datetime_index(frame)
    cutoff = pd.Timestamp(end).tz_localize(None)
    start = cutoff - pd.DateOffset(years=MAX_HISTORY_YEARS)
    return normalized.loc[(normalized.index >= start) & (normalized.index <= cutoff)].copy()


def exponential_history_weights(index: pd.DatetimeIndex, *, end: object) -> pd.Series:
    """Two-year half-life weights anchored on the requested vintage date."""
    dates = pd.DatetimeIndex(pd.to_datetime(index)).tz_localize(None)
    cutoff = pd.Timestamp(end).tz_localize(None)
    if (dates > cutoff).any():
        raise ValueError("history weights cannot include dates after end")
    age_years = (cutoff - dates).days / 365.25
    values = np.asarray(np.power(0.5, age_years / HALF_LIFE_YEARS), dtype=float)
    if len(values) == 0:
        return pd.Series(dtype=float, index=dates, name="weight")
    values = values / values.mean()
    return pd.Series(values, index=dates, name="weight")


def build_holding_factor_set(
    ticker: str,
    metadata: dict[str, str] | None,
    *,
    regional_factors: dict[str, pd.DataFrame],
    us_industries: pd.DataFrame | None,
    end: object,
) -> HoldingFactorSet:
    """Construct one holding's prefixed regional factors and optional US industry leg."""
    region = classify_region(ticker, metadata)
    if region not in regional_factors:
        raise ValueError(f"regional factors are unavailable for {region!r}")

    raw = slice_history(regional_factors[region], end=end)
    assert isinstance(raw, pd.DataFrame)
    required = {*_FACTOR_COLUMNS, "RF"}
    missing = required - set(raw.columns)
    if missing:
        raise ValueError(f"regional factor frame is missing columns: {sorted(missing)}")

    prefix = _REGION_PREFIX[region]
    factors = raw[list(_FACTOR_COLUMNS)].rename(
        columns={name: f"{prefix}:{name}" for name in _FACTOR_COLUMNS}
    )
    risk_free = raw["RF"].rename("RF")
    prior = dict.fromkeys(factors.columns, 0.0)
    prior[f"{prefix}:MKT_RF"] = 1.0

    industry = industry_factor_for_holding(metadata)
    if industry is not None:
        if us_industries is None or industry not in us_industries.columns:
            raise ValueError(f"US industry history is unavailable for {industry!r}")
        industry_history = slice_history(us_industries[[industry]], end=end)
        assert isinstance(industry_history, pd.DataFrame)
        aligned = industry_history[industry].reindex(factors.index)
        industry_key = f"US_IND:{industry}"
        factors[industry_key] = aligned - (raw["MKT_RF"] + raw["RF"])
        prior[industry_key] = 1.0

    return HoldingFactorSet(
        ticker=ticker,
        region=region,
        factors=factors,
        risk_free=risk_free,
        prior=prior,
        industry_factor=industry,
        industry_mapping=INDUSTRY_MAPPING_SPEC if industry is not None else None,
    )


def _prior_target_ridge(
    design: pd.DataFrame,
    target: pd.Series,
    weights: pd.Series,
    prior: dict[str, float],
) -> np.ndarray:
    """Exponentially weighted ridge around a raw-unit informative prior."""
    x = design.to_numpy(dtype=float)
    y = target.to_numpy(dtype=float)
    prior_vector = np.array([prior[column] for column in design.columns], dtype=float)
    w = weights.to_numpy(dtype=float)
    w = w / w.mean()

    mean = np.average(x, axis=0, weights=w)
    centered = x - mean
    scale = np.sqrt(np.average(centered**2, axis=0, weights=w))
    active = scale > np.finfo(float).eps
    if not active.any():
        return prior_vector

    z = centered[:, active] / scale[active]
    residual = y - x @ prior_vector
    augmented = np.column_stack([np.ones(len(z)), z])
    root_w = np.sqrt(w)
    weighted_design = augmented * root_w[:, None]
    gram = weighted_design.T @ weighted_design
    penalty = np.diag([0.0, *([EXPOSURE_RIDGE_ALPHA] * int(active.sum()))])
    rhs = weighted_design.T @ (residual * root_w)
    solution = np.linalg.solve(gram + penalty, rhs)

    estimate = prior_vector.copy()
    estimate[active] += solution[1:] / scale[active]
    return estimate


def compound_weekly_returns(frame: pd.DataFrame) -> pd.DataFrame:
    """Aggregate daily return columns into Friday-ending weekly returns."""
    if frame.empty:
        return frame.copy()
    weekly = (1.0 + frame).resample("W-FRI").prod(min_count=1) - 1.0
    observed_end = frame.index.to_series().resample("W-FRI").max().reindex(weekly.index)
    weekly.index = pd.DatetimeIndex(observed_end.to_numpy())
    return weekly


def estimate_exposure(
    ticker: str,
    stock_returns: pd.Series,
    factor_set: HoldingFactorSet,
    *,
    end: object,
) -> ExposureEstimate:
    """Estimate an exponentially weighted exposure and shrink it toward explicit priors."""
    stock = slice_history(stock_returns.rename("stock"), end=end)
    assert isinstance(stock, pd.Series)
    weekly_factors = compound_weekly_returns(factor_set.factors)
    weekly_stock = compound_weekly_returns(stock.to_frame()).iloc[:, 0]
    weekly_rf = compound_weekly_returns(factor_set.risk_free.to_frame()).iloc[:, 0]
    joined = weekly_factors.join(weekly_stock).join(weekly_rf).dropna(how="any")
    n_obs = len(joined)
    prior = dict(factor_set.prior)

    if n_obs == 0:
        raise ValueError(f"{ticker}: no overlapping weekly stock and factor observations")

    if n_obs < MIN_PROXY_OBSERVATIONS:
        return ExposureEstimate(
            ticker=ticker,
            region=factor_set.region,
            tier="prior_proxy",
            n_obs=n_obs,
            coefficients=prior,
            prior=prior,
            data_weight=0.0,
            industry_factor=factor_set.industry_factor,
            industry_mapping=factor_set.industry_mapping,
        )

    columns = list(factor_set.factors.columns)
    target = joined["stock"] - joined["RF"]
    weights = exponential_history_weights(joined.index, end=end)
    raw = _prior_target_ridge(joined[columns], target, weights, prior)

    if n_obs >= FULL_ESTIMATE_OBSERVATIONS:
        tier: ExposureTier = "estimated"
        data_weight = 1.0
    else:
        tier = "strongly_shrunk"
        data_weight = (n_obs - MIN_PROXY_OBSERVATIONS) / (
            FULL_ESTIMATE_OBSERVATIONS - MIN_PROXY_OBSERVATIONS
        )

    coefficients = {
        column: float(data_weight * estimate + (1.0 - data_weight) * prior[column])
        for column, estimate in zip(columns, raw, strict=True)
    }
    return ExposureEstimate(
        ticker=ticker,
        region=factor_set.region,
        tier=tier,
        n_obs=n_obs,
        coefficients=coefficients,
        prior=prior,
        data_weight=data_weight,
        industry_factor=factor_set.industry_factor,
        industry_mapping=factor_set.industry_mapping,
    )


def estimate_portfolio_exposures(
    ticker_returns: pd.DataFrame,
    *,
    metadata: dict[str, dict[str, str]],
    regional_factors: dict[str, pd.DataFrame],
    us_industries: pd.DataFrame | None,
    end: object,
) -> tuple[pd.DataFrame, dict[str, ExposureEstimate]]:
    """Estimate every holding independently and return a zero-filled union matrix."""
    if ticker_returns.empty:
        raise ValueError("ticker_returns must be non-empty")
    estimates: dict[str, ExposureEstimate] = {}
    for ticker in ticker_returns.columns:
        factor_set = build_holding_factor_set(
            str(ticker),
            metadata.get(str(ticker)),
            regional_factors=regional_factors,
            us_industries=us_industries,
            end=end,
        )
        estimates[str(ticker)] = estimate_exposure(
            str(ticker), ticker_returns[ticker], factor_set, end=end
        )

    factor_names = sorted(
        {factor for estimate in estimates.values() for factor in estimate.coefficients}
    )
    betas = pd.DataFrame(
        {
            ticker: {factor: estimate.coefficients.get(factor, 0.0) for factor in factor_names}
            for ticker, estimate in estimates.items()
        }
    ).T
    betas.index.name = None
    return betas, estimates
