"""Joint-historical scenario construction for the optional Quant V2 engine."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf

VALID_HORIZONS = frozenset({5, 21, 63})
VALID_SEVERITIES = frozenset({1.0, 1.5, 2.0})
STATE_LEVEL_COLUMNS = ("VIX", "US_10Y_YIELD", "BROAD_DOLLAR", "WTI", "HYG", "SHY")
STATE_FEATURES = ("volatility", "rates", "dollar", "oil", "credit")
MAX_NEIGHBORS = 50
MIN_EFFECTIVE_SAMPLE_SIZE = 20.0
MAX_STATE_FORWARD_FILL_ROWS = 5
MAX_EVENT_ANCHOR_GAP_DAYS = 7
QUANT_SCENARIO_SPEC = (
    "joint-history-v1|horizons=5,21,63|covariance=ledoit-wolf|neighbors=50|"
    "kernel=gaussian|minimum-ess=20|point=weighted-medoid|range=weighted-bootstrap"
)


class QuantModelDomainError(ValueError):
    """Raised when the requested scenario is not supported by public history."""


@dataclass(frozen=True)
class DirectAttribution:
    total_pnl: float
    by_factor: dict[str, float]
    by_ticker: dict[str, float]


@dataclass(frozen=True)
class HistoricalModelRange:
    p10: float
    p50: float
    p90: float
    draws: int
    seed: int


@dataclass(frozen=True)
class QuantSupport:
    candidate_count: int
    direction_compatible_count: int
    neighbor_count: int
    effective_sample_size: float
    medoid_date: pd.Timestamp
    nearest_distance: float
    kernel_bandwidth: float
    query_dates: tuple[pd.Timestamp, ...]
    data_start: pd.Timestamp
    data_end: pd.Timestamp


@dataclass(frozen=True)
class QuantScenarioOutput:
    factor_shocks: dict[str, float]
    by_factor: dict[str, float]
    by_ticker: dict[str, float]
    total_pnl: float
    factor_ranges: dict[str, dict[str, float]]
    model_range: HistoricalModelRange
    support: QuantSupport
    neighbor_dates: tuple[pd.Timestamp, ...]
    neighbor_weights: tuple[float, ...]


def _timestamp(value: object) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert(None)
    return timestamp


def _validated_frame(
    frame: pd.DataFrame,
    *,
    name: str,
    end: object | None = None,
) -> pd.DataFrame:
    result = frame.copy()
    result.index = pd.DatetimeIndex(pd.to_datetime(result.index)).tz_localize(None)
    if end is not None:
        result = result.loc[result.index <= _timestamp(end)]
    if result.empty:
        raise ValueError(f"{name} must be non-empty in the requested vintage")
    if result.index.has_duplicates:
        raise ValueError(f"{name} contains duplicate dates")
    result = result.sort_index()
    values = result.to_numpy(dtype=float)
    if not np.isfinite(values[~np.isnan(values)]).all():
        raise ValueError(f"{name} contains non-finite values")
    return result.astype(float)


def _validate_horizon(horizon: int) -> None:
    if horizon not in VALID_HORIZONS:
        raise ValueError(f"horizon must be one of {sorted(VALID_HORIZONS)} trading days")


def _validate_severity(severity: float) -> None:
    if float(severity) not in VALID_SEVERITIES:
        raise ValueError(f"severity must be one of {sorted(VALID_SEVERITIES)}")


def build_state_change_history(
    state_levels: pd.DataFrame,
    *,
    horizon: int,
    as_of: object,
) -> pd.DataFrame:
    """Transform public market levels into comparable fixed-horizon state changes."""
    _validate_horizon(horizon)
    levels = _validated_frame(state_levels, name="state_levels", end=as_of)
    missing = set(STATE_LEVEL_COLUMNS) - set(levels.columns)
    if missing:
        raise ValueError(f"state_levels is missing columns: {sorted(missing)}")
    levels = levels.loc[:, list(STATE_LEVEL_COLUMNS)]
    levels = levels.ffill(limit=MAX_STATE_FORWARD_FILL_ROWS)
    if levels.empty:
        raise ValueError("state_levels has no observations on or before as_of")

    positive_columns = ["VIX", "BROAD_DOLLAR", "HYG", "SHY"]
    if (levels[positive_columns].dropna() <= 0).any().any():
        raise ValueError("VIX, broad-dollar, HYG, and SHY levels must be positive")

    oil_abs = levels["WTI"].abs().replace(0.0, np.nan)
    oil_scale = float(oil_abs.median(skipna=True))
    if not np.isfinite(oil_scale) or oil_scale <= 0:
        raise ValueError("WTI history has no usable scale")

    transformed = pd.DataFrame(
        {
            "volatility": np.log(levels["VIX"]),
            "rates": levels["US_10Y_YIELD"],
            "dollar": np.log(levels["BROAD_DOLLAR"]),
            "oil": np.arcsinh(levels["WTI"] / oil_scale),
            "credit": np.log(levels["SHY"] / levels["HYG"]),
        },
        index=levels.index,
    )
    changes = transformed.diff(periods=horizon).dropna(how="any")
    if changes.empty:
        raise ValueError("state history is shorter than the requested horizon")
    if not np.isfinite(changes.to_numpy()).all():
        raise ValueError("state transformations produced non-finite values")
    return changes.loc[:, list(STATE_FEATURES)]


def build_factor_outcome_history(
    factor_returns: pd.DataFrame,
    *,
    horizon: int,
    as_of: object,
) -> pd.DataFrame:
    """Compound daily factor returns over exact trailing trading-day windows."""
    _validate_horizon(horizon)
    returns = _validated_frame(factor_returns, name="factor_returns", end=as_of)
    if returns.isna().any().any():
        raise ValueError("factor_returns contains missing values")
    if (returns <= -1.0).any().any():
        raise ValueError("factor returns must be greater than -1")
    compounded = np.expm1(np.log1p(returns).rolling(horizon, min_periods=horizon).sum())
    outcomes = compounded.dropna(how="any")
    if outcomes.empty:
        raise ValueError("factor history is shorter than the requested horizon")
    return outcomes


def build_joint_histories(
    factor_returns: pd.DataFrame,
    state_levels: pd.DataFrame,
    *,
    horizon: int,
    as_of: object,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Roll state changes and factor outcomes on one complete trading calendar."""
    _validate_horizon(horizon)
    returns = _validated_frame(factor_returns, name="factor_returns", end=as_of)
    levels = _validated_frame(state_levels, name="state_levels", end=as_of)
    missing = set(STATE_LEVEL_COLUMNS) - set(levels.columns)
    if missing:
        raise ValueError(f"state_levels is missing columns: {sorted(missing)}")
    returns = returns.dropna(how="any")
    if returns.empty:
        raise ValueError("factor_returns has no complete observations")

    # Preserve official observations that fall between factor-market dates, then
    # carry them only across the bounded publication/holiday gap before selecting
    # the factor calendar. Both horizon windows are rolled after this alignment.
    union_index = levels.index.union(returns.index).sort_values()
    aligned_levels = (
        levels.loc[:, list(STATE_LEVEL_COLUMNS)]
        .reindex(union_index)
        .ffill(limit=MAX_STATE_FORWARD_FILL_ROWS)
        .reindex(returns.index)
        .dropna(how="any")
    )
    aligned_returns = returns.loc[aligned_levels.index]
    states = build_state_change_history(aligned_levels, horizon=horizon, as_of=as_of)
    outcomes = build_factor_outcome_history(aligned_returns, horizon=horizon, as_of=as_of)
    joint_index = states.index.intersection(outcomes.index)
    return states.loc[joint_index], outcomes.loc[joint_index]


def estimate_shrinkage_covariance(frame: pd.DataFrame) -> np.ndarray:
    """Return a positive-definite Ledoit-Wolf covariance estimate."""
    if len(frame) < 2 or frame.shape[1] == 0:
        raise ValueError("covariance history needs at least two rows and one column")
    values = frame.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("covariance history contains non-finite values")
    covariance = np.asarray(LedoitWolf(assume_centered=False).fit(values).covariance_)
    if covariance.shape != (frame.shape[1], frame.shape[1]):
        raise RuntimeError("shrinkage covariance returned an unexpected shape")
    if np.linalg.eigvalsh(covariance).min() <= 0:
        raise QuantModelDomainError("state covariance is not positive definite")
    return covariance


def filter_state_directions(
    history: pd.DataFrame,
    directions: Mapping[str, int],
) -> pd.DataFrame:
    """Apply exact semantic sign constraints without relaxing sparse results."""
    if set(directions) != set(history.columns):
        raise ValueError("directions must name every state feature exactly once")
    mask = pd.Series(True, index=history.index)
    for feature in history.columns:
        direction = int(directions[feature])
        if direction not in {-1, 0, 1}:
            raise ValueError("state directions must be -1, 0, or 1")
        if direction > 0:
            mask &= history[feature] > 0
        elif direction < 0:
            mask &= history[feature] < 0
    return history.loc[mask].copy()


def gaussian_kernel_weights(distances: np.ndarray, *, bandwidth: float) -> np.ndarray:
    """Normalize Gaussian distance weights."""
    values = np.asarray(distances, dtype=float)
    if values.ndim != 1 or len(values) == 0:
        raise ValueError("distances must be a non-empty vector")
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("distances must be finite and non-negative")
    if not np.isfinite(bandwidth) or bandwidth <= 0:
        raise QuantModelDomainError("kernel bandwidth must be positive")
    raw = np.exp(-0.5 * np.square(values / bandwidth))
    total = float(raw.sum())
    if not np.isfinite(total) or total <= 0:
        raise QuantModelDomainError("kernel weights underflowed to zero")
    return raw / total


def effective_sample_size(weights: np.ndarray) -> float:
    """Return Kish effective sample size for normalized or raw positive weights."""
    values = np.asarray(weights, dtype=float)
    if values.ndim != 1 or len(values) == 0:
        raise ValueError("weights must be a non-empty vector")
    if not np.isfinite(values).all() or (values < 0).any() or values.sum() <= 0:
        raise ValueError("weights must be finite, non-negative, and nonzero")
    normalized = values / values.sum()
    return float(1.0 / np.square(normalized).sum())


def require_effective_sample_size(
    weights: np.ndarray,
    *,
    minimum: float = MIN_EFFECTIVE_SAMPLE_SIZE,
) -> float:
    """Reject a locally concentrated estimate with inadequate historical support."""
    sample_size = effective_sample_size(weights)
    if sample_size < minimum:
        raise QuantModelDomainError(
            f"effective sample size {sample_size:.1f} is below the minimum {minimum:.1f}"
        )
    return sample_size


def _robust_location_scale(history: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    center = history.median(axis=0)
    mad = (history - center).abs().median(axis=0) * 1.4826
    q75 = history.quantile(0.75)
    q25 = history.quantile(0.25)
    iqr_scale = (q75 - q25) / 1.349
    std = history.std(axis=0, ddof=0)
    scale = mad.where(mad > np.finfo(float).eps, iqr_scale)
    scale = scale.where(scale > np.finfo(float).eps, std)
    invalid = (~np.isfinite(scale)) | (scale <= np.finfo(float).eps)
    if invalid.any():
        raise QuantModelDomainError(
            f"state features have no historical variation: {sorted(scale.index[invalid])}"
        )
    return center, scale


def validate_model_domain(query: pd.Series, history: pd.DataFrame) -> None:
    """Fail when any requested state dimension lies beyond observed robust support."""
    if list(query.index) != list(history.columns):
        query = query.reindex(history.columns)
    if query.isna().any() or not np.isfinite(query.to_numpy(dtype=float)).all():
        raise ValueError("state query is incomplete or non-finite")
    center, scale = _robust_location_scale(history)
    standardized = (history - center) / scale
    query_z = (query - center) / scale
    tolerance = 1e-9
    outside = (query_z < standardized.min() - tolerance) | (
        query_z > standardized.max() + tolerance
    )
    if outside.any():
        raise QuantModelDomainError(
            f"state query is outside historical support for {sorted(query.index[outside])}"
        )


def build_event_query(
    history: pd.DataFrame,
    event_end_dates: Sequence[object],
    *,
    max_gap_days: int = MAX_EVENT_ANCHOR_GAP_DAYS,
) -> tuple[pd.Series, tuple[pd.Timestamp, ...]]:
    """Use the last joint observation on or before each selected event end."""
    if history.empty:
        raise ValueError("joint state history must be non-empty")
    if not event_end_dates:
        raise ValueError("at least one event end date is required")
    ordered = history.sort_index()
    selected: list[pd.Timestamp] = []
    for raw_end in event_end_dates:
        event_end = _timestamp(raw_end)
        eligible = ordered.index[ordered.index <= event_end]
        if len(eligible) == 0:
            raise QuantModelDomainError(f"event ending {event_end.date()} predates joint history")
        date = pd.Timestamp(eligible[-1])
        if (event_end - date).days > max_gap_days:
            raise QuantModelDomainError(
                f"event ending {event_end.date()} has no nearby joint observation"
            )
        selected.append(date)
    query = (
        ordered.loc[selected[0]].copy()
        if len(selected) == 1
        else ordered.loc[selected].median(axis=0)
    )
    return query, tuple(selected)


def weighted_medoid(outcomes: pd.DataFrame, weights: np.ndarray) -> pd.Timestamp:
    """Return the observed joint factor vector minimizing weighted robust distance."""
    if outcomes.empty:
        raise ValueError("factor outcomes must be non-empty")
    normalized = np.asarray(weights, dtype=float)
    if normalized.shape != (len(outcomes),):
        raise ValueError("weights must align with factor outcomes")
    if not np.isfinite(normalized).all() or (normalized < 0).any() or normalized.sum() <= 0:
        raise ValueError("weights must be finite, non-negative, and nonzero")
    normalized = normalized / normalized.sum()
    center = outcomes.median(axis=0)
    mad = (outcomes - center).abs().median(axis=0) * 1.4826
    scale = mad.where(mad > np.finfo(float).eps, outcomes.std(axis=0, ddof=0))
    scale = scale.where(scale > np.finfo(float).eps, 1.0)
    standardized = ((outcomes - center) / scale).to_numpy(dtype=float)
    pairwise = np.linalg.norm(standardized[:, None, :] - standardized[None, :, :], axis=2)
    costs = pairwise @ normalized
    return pd.Timestamp(outcomes.index[int(np.argmin(costs))])


def _portfolio_factor_exposure(
    betas: pd.DataFrame,
    holdings: Mapping[str, float],
    factor_names: Sequence[str],
) -> pd.Series:
    if set(holdings) != set(betas.index):
        raise ValueError("holdings and beta rows must contain the same tickers")
    missing = set(factor_names) - set(betas.columns)
    if missing:
        raise ValueError(f"betas are missing factors: {sorted(missing)}")
    weights = pd.Series({ticker: float(weight) for ticker, weight in holdings.items()})
    if not np.isfinite(weights.to_numpy()).all():
        raise ValueError("holdings contain non-finite weights")
    selected = betas.loc[weights.index, list(factor_names)].astype(float)
    if not np.isfinite(selected.to_numpy()).all():
        raise ValueError("betas contain non-finite values")
    return selected.mul(weights, axis=0).sum(axis=0)


def direct_attribution(
    betas: pd.DataFrame,
    holdings: Mapping[str, float],
    factor_shocks: pd.Series,
) -> DirectAttribution:
    """Calculate exact linear factor and holding contributions without Shapley."""
    shocks = factor_shocks.astype(float)
    if shocks.empty or not np.isfinite(shocks.to_numpy()).all():
        raise ValueError("factor shocks must be finite and non-empty")
    exposure = _portfolio_factor_exposure(betas, holdings, list(shocks.index))
    by_factor = (exposure * shocks).astype(float).to_dict()
    weights = pd.Series({ticker: float(weight) for ticker, weight in holdings.items()})
    ticker_values = betas.loc[weights.index, shocks.index].dot(shocks).mul(weights)
    by_ticker = ticker_values.astype(float).to_dict()
    total = float(sum(by_factor.values()))
    return DirectAttribution(total_pnl=total, by_factor=by_factor, by_ticker=by_ticker)


def historical_model_range(
    neighbor_outcomes: pd.DataFrame,
    neighbor_weights: np.ndarray,
    betas: pd.DataFrame,
    holdings: Mapping[str, float],
    *,
    severity: float,
    draws: int = 4096,
    seed: int = 1729,
) -> HistoricalModelRange:
    """Bootstrap whole historical factor vectors and report a deterministic P&L range."""
    _validate_severity(severity)
    if draws < 100:
        raise ValueError("historical model range requires at least 100 draws")
    weights = np.asarray(neighbor_weights, dtype=float)
    if weights.shape != (len(neighbor_outcomes),):
        raise ValueError("neighbor weights must align with outcomes")
    if not np.isfinite(weights).all() or (weights < 0).any() or weights.sum() <= 0:
        raise ValueError("neighbor weights must be finite, non-negative, and nonzero")
    probabilities = weights / weights.sum()
    exposure = _portfolio_factor_exposure(
        betas, holdings, [str(column) for column in neighbor_outcomes.columns]
    )
    rng = np.random.default_rng(seed)
    sampled = rng.choice(len(neighbor_outcomes), size=draws, replace=True, p=probabilities)
    joint_vectors = neighbor_outcomes.to_numpy(dtype=float)[sampled]
    pnl_draws = joint_vectors @ exposure.to_numpy(dtype=float) * float(severity)
    p10, p50, p90 = np.quantile(pnl_draws, [0.1, 0.5, 0.9])
    return HistoricalModelRange(
        p10=float(p10),
        p50=float(p50),
        p90=float(p90),
        draws=draws,
        seed=seed,
    )


def weighted_factor_ranges(
    neighbor_outcomes: pd.DataFrame,
    neighbor_weights: np.ndarray,
    *,
    severity: float,
) -> dict[str, dict[str, float]]:
    """Summarize each factor's weighted neighbor distribution after severity scaling."""
    _validate_severity(severity)
    weights = np.asarray(neighbor_weights, dtype=float)
    if weights.shape != (len(neighbor_outcomes),):
        raise ValueError("neighbor weights must align with outcomes")
    if not np.isfinite(weights).all() or (weights < 0).any() or weights.sum() <= 0:
        raise ValueError("neighbor weights must be finite, non-negative, and nonzero")
    weights = weights / weights.sum()
    result: dict[str, dict[str, float]] = {}
    for factor in neighbor_outcomes.columns:
        values = neighbor_outcomes[factor].to_numpy(dtype=float) * float(severity)
        order = np.argsort(values, kind="stable")
        ordered_values = values[order]
        cumulative = np.cumsum(weights[order])
        result[str(factor)] = {
            "mean": float(np.dot(values, weights)),
            "p10": float(np.interp(0.10, cumulative, ordered_values)),
            "p90": float(np.interp(0.90, cumulative, ordered_values)),
            "count": float(len(values)),
        }
    return result


def _mahalanobis_neighbors(
    history: pd.DataFrame,
    query: pd.Series,
) -> tuple[pd.DatetimeIndex, np.ndarray, float, float, float]:
    center, scale = _robust_location_scale(history)
    standardized = (history - center) / scale
    query_z = ((query - center) / scale).to_numpy(dtype=float)
    covariance = estimate_shrinkage_covariance(standardized)
    precision = np.linalg.inv(covariance)
    differences = standardized.to_numpy(dtype=float) - query_z
    squared = np.einsum("ij,jk,ik->i", differences, precision, differences)
    distances = np.sqrt(np.maximum(squared, 0.0))
    order = np.argsort(distances, kind="stable")[:MAX_NEIGHBORS]
    selected_distances = distances[order]
    positive = selected_distances[selected_distances > np.finfo(float).eps]
    if len(positive) == 0:
        raise QuantModelDomainError("historical neighbors have zero distance dispersion")
    bandwidth = float(np.median(positive))
    weights = gaussian_kernel_weights(selected_distances, bandwidth=bandwidth)
    sample_size = require_effective_sample_size(weights)
    return history.index[order], weights, bandwidth, sample_size, float(selected_distances.min())


def run_quant_scenario(
    *,
    factor_returns: pd.DataFrame,
    state_levels: pd.DataFrame,
    betas: pd.DataFrame,
    holdings: Mapping[str, float],
    event_end_dates: Sequence[object],
    directions: Mapping[str, int],
    horizon: int,
    severity: float,
    as_of: object,
    range_draws: int = 4096,
    range_seed: int = 1729,
) -> QuantScenarioOutput:
    """Construct a supported joint-history scenario and exact direct attribution."""
    _validate_horizon(horizon)
    _validate_severity(severity)
    cutoff = _timestamp(as_of)
    future_events = sorted(
        _timestamp(event_end) for event_end in event_end_dates if _timestamp(event_end) > cutoff
    )
    if future_events:
        raise QuantModelDomainError(
            f"selected event ending {future_events[0].date()} is after as_of {cutoff.date()}"
        )
    states, outcomes = build_joint_histories(
        factor_returns,
        state_levels,
        horizon=horizon,
        as_of=as_of,
    )
    joint_states = states.dropna(how="any")
    joint_outcomes = outcomes.loc[joint_states.index].dropna(how="any")
    joint_states = joint_states.loc[joint_outcomes.index]
    if len(joint_states) < int(MIN_EFFECTIVE_SAMPLE_SIZE):
        raise QuantModelDomainError("joint history has fewer than 20 complete observations")

    query, query_dates = build_event_query(joint_states, event_end_dates)
    validate_model_domain(query, joint_states)
    compatible = filter_state_directions(joint_states, directions)
    if len(compatible) < int(MIN_EFFECTIVE_SAMPLE_SIZE):
        raise QuantModelDomainError(
            "semantic direction filter leaves fewer than 20 historical observations"
        )
    validate_model_domain(query, compatible)
    (
        neighbor_dates,
        neighbor_weights,
        bandwidth,
        sample_size,
        nearest_distance,
    ) = _mahalanobis_neighbors(compatible, query)
    neighbor_outcomes = joint_outcomes.loc[neighbor_dates]
    medoid_date = weighted_medoid(neighbor_outcomes, neighbor_weights)
    medoid = neighbor_outcomes.loc[medoid_date] * float(severity)
    attribution = direct_attribution(betas, holdings, medoid)
    model_range = historical_model_range(
        neighbor_outcomes,
        neighbor_weights,
        betas,
        holdings,
        severity=severity,
        draws=range_draws,
        seed=range_seed,
    )
    factor_ranges = weighted_factor_ranges(
        neighbor_outcomes,
        neighbor_weights,
        severity=severity,
    )
    support = QuantSupport(
        candidate_count=len(joint_states),
        direction_compatible_count=len(compatible),
        neighbor_count=len(neighbor_dates),
        effective_sample_size=sample_size,
        medoid_date=medoid_date,
        nearest_distance=nearest_distance,
        kernel_bandwidth=bandwidth,
        query_dates=query_dates,
        data_start=pd.Timestamp(joint_states.index.min()),
        data_end=pd.Timestamp(joint_states.index.max()),
    )
    return QuantScenarioOutput(
        factor_shocks={str(key): float(value) for key, value in medoid.items()},
        by_factor=attribution.by_factor,
        by_ticker=attribution.by_ticker,
        total_pnl=attribution.total_pnl,
        factor_ranges=factor_ranges,
        model_range=model_range,
        support=support,
        neighbor_dates=tuple(pd.Timestamp(date) for date in neighbor_dates),
        neighbor_weights=tuple(float(value) for value in neighbor_weights),
    )
