"""LLM-free completion study (Phase 42).

Question: does a COHERENT factor vector fix the scenario layer's understatement,
and does a market-relative basis make the attribution explainable?

For every (registry event × sample book) pair the engine-replay harness can
compute, the scenario is reduced to a few ANCHOR moves taken from the event's
own realized factor returns, and each variant reconstructs everything else:

    V0  raw basis, unanchored factors held at 0        (today's production semantics)
    V1  raw basis, conditional completion              s_u = Σ_ua Σ_aa⁻¹ a
    V2  relative basis, unanchored relative moves 0    ("moves with the market")
    V3  relative basis, conditional completion
    V4  V3 with a stress-week covariance (largest-|SPY| quartile of weeks)
    V5  V3 with rates as yield changes and VIX / oil / dollar as log changes

Modeled factor P&L is compared with the book's realized buy-and-hold USD return,
and the full realized vector (exactly the engine replay) is the upper bound. The
anchors are REALIZED moves, so this isolates completion quality from the LLM:
it asks "if a scenario stated these moves correctly, how much of the book's
outcome would each method recover?" The LLM's own magnitudes are a separate,
paid study (`app/llm/shock_calibration.py`).

Inputs are gathered once (network) and evaluated purely, so the inputs can be
pickled and the evaluation re-run without touching the market-data provider.
Deliberately imports only `app.data.*` / `app.factors.*` / `app.config`.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd

from app.config import Config, load_config
from app.data.market import compute_weekly_returns, fetch_daily_prices, fetch_weekly_prices
from app.data.sample_portfolios import (
    CASH_TICKER,
    SAMPLE_PORTFOLIOS,
    get_portfolio,
    sample_as_of,
)
from app.factors.analogs import (
    HistoricalEvent,
    events_version,
    fetch_event_returns_matrix,
    load_events,
)
from app.factors.completion import (
    RelativeBasis,
    complete_shocks,
    fit_relative_basis,
    shrunk_covariance,
)
from app.factors.engine_replay import (
    realized_book_return,
    select_vintage_factors,
    vintage_ticker_returns,
)
from app.factors.regression import (
    estimate_betas_and_stats,
    estimate_betas_for_portfolio,
    regression_spec,
)
from app.factors.universe import (
    FACTORS,
    factor_name_by_ticker,
    factor_tickers,
    factor_universe_version,
)

logger = logging.getLogger(__name__)

MARKET = "SPY"
RELATIVE_GROUPS = ("market", "sector", "style")
# Factors whose yfinance series is a LEVEL (yield, index points, futures price),
# not a total-return price. Production treats every factor as a percent change of
# its level; V5 tests the units people actually state these moves in.
LEVEL_TRANSFORMS: dict[str, str] = {
    "TNX": "yield_change",
    "VIX": "log",
    "OIL": "log",
    "DXY": "log",
}
STRESS_QUANTILE = 0.75
ANCHOR_SETS: tuple[str, ...] = ("market", "market_macro", "market_top2", "market_top4")
VARIANTS: tuple[str, ...] = ("V0", "V1", "V2", "V3", "V4", "V5")
COMPLETION_VARIANTS = frozenset({"V1", "V3", "V4", "V5"})
VARIANT_LABELS: dict[str, str] = {
    "V0": "raw basis, unanchored = 0 (production today)",
    "V1": "raw basis, conditional completion",
    "V2": "relative basis, unanchored relative = 0",
    "V3": "relative basis, conditional completion",
    "V4": "relative basis, completion with stress-week covariance",
    "V5": "relative basis, completion, yield-change / log units",
}
ANCHOR_SET_LABELS: dict[str, str] = {
    "market": "SPY only",
    "market_macro": "SPY + the seven macro factors",
    "market_top2": "SPY + the two most extreme other moves",
    "market_top4": "SPY + the four most extreme other moves",
}

# Pre-registered adoption gates (fixed before the first run; see docs/methodology.md).
G1_MAE_RATIO = 0.75
G2_MAE_TOLERANCE = 0.0025
G3_MAE_TOLERANCE = 0.0010
DEFAULT_BOOTSTRAP = 30
DEFAULT_SEED = 20261016


# ---------------------------------------------------------------- inputs (network)


@dataclass(frozen=True)
class EventInputs:
    """Vintage factor history and realized event moves for one registry event."""

    event_id: str
    start_date: date
    end_date: date
    factor_returns: pd.DataFrame
    dropped: list[str]
    level_changes: pd.DataFrame
    realized: dict[str, float]
    realized_levels: dict[str, float]
    start_levels: dict[str, float]


@dataclass(frozen=True)
class BookInputs:
    """Vintage USD holding returns and the realized book return for one pair."""

    event_id: str
    portfolio_key: str
    ticker_returns: pd.DataFrame | None
    realized_pnl: float | None
    skipped_reason: str | None


@dataclass(frozen=True)
class StudyInputs:
    events: list[EventInputs]
    books: list[BookInputs]
    reference_tnx_level: float | None
    reference_date: str | None
    regression_spec: str
    events_version: str
    factor_universe_version: str
    weights_as_of: str
    gathered_at: str


def _level_changes(levels: pd.DataFrame, index: pd.Index) -> pd.DataFrame:
    """Weekly level transforms: yield changes in decimal yield, else log changes."""
    out: dict[str, pd.Series] = {}
    for name, kind in LEVEL_TRANSFORMS.items():
        if name not in levels.columns:
            continue
        series = levels[name].astype(float)
        if kind == "yield_change":
            out[name] = (series / 100.0).diff()
        else:
            out[name] = np.log(series.where(series > 0.0)).diff()
    return pd.DataFrame(out).reindex(index)


def _level_moves(daily: pd.DataFrame) -> tuple[dict[str, float], dict[str, float]]:
    """Event-window moves in level units plus the starting levels."""
    moves: dict[str, float] = {}
    starts: dict[str, float] = {}
    for name, kind in LEVEL_TRANSFORMS.items():
        if name not in daily.columns:
            continue
        series = daily[name].dropna()
        if len(series) < 2:
            continue
        first, last = float(series.iloc[0]), float(series.iloc[-1])
        starts[name] = first
        if kind == "yield_change":
            moves[name] = (last - first) / 100.0
        elif first > 0.0 and last > 0.0:
            moves[name] = math.log(last / first)
    return moves, starts


def _gather_event(
    event: HistoricalEvent, realized_row: Mapping[str, float], config: Config
) -> EventInputs:
    prices = fetch_weekly_prices(
        factor_tickers(), end=event.start_date, lookback_weeks=config.beta_lookback_weeks
    )
    names = factor_name_by_ticker()
    returns = compute_weekly_returns(prices).rename(columns=names)
    vintage, _ = select_vintage_factors(returns)
    dropped = sorted(set(FACTORS) - {str(c) for c in vintage.columns})
    level_cols = [n for n in LEVEL_TRANSFORMS if n in vintage.columns]
    levels = prices.rename(columns=names)
    level_changes = _level_changes(levels[level_cols], vintage.index)
    realized_levels: dict[str, float] = {}
    start_levels: dict[str, float] = {}
    if level_cols:
        daily = fetch_daily_prices(
            [FACTORS[n].ticker for n in level_cols],
            start=event.start_date,
            end=event.end_date + timedelta(days=1),
        ).rename(columns=names)
        realized_levels, start_levels = _level_moves(daily)
    realized = {
        str(f): float(v)
        for f, v in realized_row.items()
        if f in vintage.columns and v is not None and pd.notna(v)
    }
    return EventInputs(
        event_id=event.id,
        start_date=event.start_date,
        end_date=event.end_date,
        factor_returns=vintage,
        dropped=dropped,
        level_changes=level_changes,
        realized=realized,
        realized_levels=realized_levels,
        start_levels=start_levels,
    )


def _gather_book(event: HistoricalEvent, portfolio_key: str, config: Config) -> BookInputs:
    portfolio = get_portfolio(portfolio_key)
    if CASH_TICKER in portfolio.holdings:
        return BookInputs(
            event.id, portfolio_key, None, None, "cash sleeve not supported by the replay harness"
        )
    try:
        ticker_returns = vintage_ticker_returns(portfolio, event, config)
        realized = realized_book_return(portfolio, event)
    except RuntimeError as exc:
        return BookInputs(event.id, portfolio_key, None, None, f"{type(exc).__name__}: {exc}")
    return BookInputs(event.id, portfolio_key, ticker_returns, realized, None)


def gather_inputs(
    *,
    event_ids: Sequence[str] | None = None,
    portfolio_keys: Sequence[str] | None = None,
    config: Config | None = None,
    max_workers: int = 4,
) -> StudyInputs:
    """Fetch every input the study needs (the only network-touching stage)."""
    config = config or load_config()
    events = load_events()
    ids = list(event_ids) if event_ids is not None else list(events)
    unknown = sorted(set(ids) - set(events))
    if unknown:
        raise ValueError(f"Unknown event ids: {unknown}")
    keys = list(portfolio_keys) if portfolio_keys is not None else list(SAMPLE_PORTFOLIOS)

    matrix = fetch_event_returns_matrix(ids, registry=events)
    workers = max(1, max_workers)
    with ThreadPoolExecutor(max_workers=min(workers, len(ids))) as pool:
        event_inputs = list(
            pool.map(lambda eid: _gather_event(events[eid], matrix.loc[eid].to_dict(), config), ids)
        )
    tasks = [(eid, key) for eid in ids for key in keys]
    with ThreadPoolExecutor(max_workers=min(workers, len(tasks))) as pool:
        books = list(pool.map(lambda t: _gather_book(events[t[0]], t[1], config), tasks))

    reference_level: float | None = None
    reference_date: str | None = None
    try:
        tnx = fetch_weekly_prices([FACTORS["TNX"].ticker], lookback_weeks=8)
        series = tnx[FACTORS["TNX"].ticker].dropna()
        if not series.empty:
            reference_level = float(series.iloc[-1])
            reference_date = str(pd.Timestamp(series.index[-1]).date())
    except RuntimeError as exc:
        logger.warning("Reference 10Y level unavailable: %s", exc)

    return StudyInputs(
        events=event_inputs,
        books=books,
        reference_tnx_level=reference_level,
        reference_date=reference_date,
        regression_spec=regression_spec(
            lookback_weeks=config.beta_lookback_weeks, alpha=config.ridge_alpha
        ),
        events_version=events_version(),
        factor_universe_version=factor_universe_version(),
        weights_as_of=sample_as_of(),
        gathered_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )


# ------------------------------------------------------------ evaluation (pure)


@dataclass(frozen=True)
class _EventModel:
    """Everything book-independent about one event, in every basis."""

    inputs: EventInputs
    horizon_weeks: float
    basis: RelativeBasis
    frames: dict[str, pd.DataFrame]  # "raw" | "rel" | "units" weekly factor frames
    covs: dict[str, pd.DataFrame]  # per completion variant
    realized: dict[str, dict[str, float]]  # "raw" | "rel" | "units"
    anchors: dict[str, list[str]]
    unavailable: dict[str, str]  # variant -> reason


@dataclass(frozen=True)
class AttributionStability:
    """Bootstrap stability of the factor attribution of the full realized vector."""

    top_driver: str
    top_driver_agreement: float
    dispersion: float
    market_share: float


@dataclass(frozen=True)
class PairRecord:
    event_id: str
    portfolio_key: str
    horizon_weeks: float | None
    realized_pnl: float | None
    full_replay: dict[str, float] = field(default_factory=dict)
    modeled: dict[str, float] = field(default_factory=dict)
    sigma: dict[str, float] = field(default_factory=dict)
    attribution: dict[str, AttributionStability] = field(default_factory=dict)
    skipped_reason: str | None = None


@dataclass(frozen=True)
class VariantStats:
    anchor_set: str
    variant: str
    n: int
    mae: float | None
    bias: float | None
    sign_hit_rate: float | None
    pearson_r: float | None
    coverage_1sd: float | None
    coverage_2sd: float | None
    implied_r2: float | None


@dataclass(frozen=True)
class GateVerdict:
    key: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class StudySummary:
    n_pairs: int
    n_computed: int
    n_common: int
    variant_stats: list[VariantStats]
    mean_by_variant: dict[str, dict[str, float | None]]
    attribution: dict[str, dict[str, float | None]]
    gates: list[GateVerdict]
    collinearity: dict[str, object]
    transport: dict[str, object]
    replay_crosscheck: dict[str, float | int | None]
    regression_spec: str
    events_version: str
    factor_universe_version: str
    weights_as_of: str
    gathered_at: str
    generated_at: str
    bootstrap: int


def _relative_names(columns: Sequence[str]) -> list[str]:
    return [
        str(c) for c in columns if str(c) != MARKET and FACTORS[str(c)].group in RELATIVE_GROUPS
    ]


def _build_event_model(ev: EventInputs) -> _EventModel | str:
    frame = ev.factor_returns
    if MARKET not in frame.columns or MARKET not in ev.realized:
        return f"{MARKET} unavailable at this vintage"
    horizon = max((ev.end_date - ev.start_date).days, 1) / 7.0
    unavailable: dict[str, str] = {}

    cov_raw, _ = shrunk_covariance(frame)
    basis = fit_relative_basis(frame, MARKET, _relative_names(frame.columns))
    rel = basis.returns(frame)
    cov_rel, _ = shrunk_covariance(rel)
    covs = {"V1": cov_raw, "V3": cov_rel}

    complete = rel.dropna(how="any")
    spy_abs = complete[MARKET].abs()
    stress = complete.loc[spy_abs >= spy_abs.quantile(STRESS_QUANTILE)]
    try:
        covs["V4"], _ = shrunk_covariance(stress)
    except (ValueError, np.linalg.LinAlgError) as exc:
        unavailable["V4"] = f"stress covariance unavailable: {exc}"

    frames = {"raw": frame, "rel": rel}
    realized_raw = dict(ev.realized)
    realized_rel = basis.to_relative(realized_raw)
    realized = {"raw": realized_raw, "rel": realized_rel}

    level_cols = [n for n in LEVEL_TRANSFORMS if n in frame.columns]
    missing_units = [
        n for n in level_cols if n not in ev.level_changes.columns or n not in ev.realized_levels
    ]
    if missing_units:
        unavailable["V5"] = f"level series unavailable for {missing_units}"
    else:
        units = rel.copy()
        for name in level_cols:
            units[name] = ev.level_changes[name]
        try:
            covs["V5"], _ = shrunk_covariance(units)
            frames["units"] = units
            realized["units"] = {
                **realized_rel,
                **{n: ev.realized_levels[n] for n in level_cols if n in realized_rel},
            }
        except (ValueError, np.linalg.LinAlgError) as exc:
            unavailable["V5"] = f"unit covariance unavailable: {exc}"

    sd = np.sqrt(np.diag(cov_raw.to_numpy()))
    sd_by_name = dict(zip((str(c) for c in cov_raw.index), sd, strict=True))
    z = {
        f: v / (sd_by_name[f] * math.sqrt(horizon))
        for f, v in realized_raw.items()
        if f in sd_by_name and sd_by_name[f] > 0.0
    }
    others = sorted((f for f in z if f != MARKET), key=lambda f: -abs(z[f]))
    macro = [f for f, meta in FACTORS.items() if meta.group == "macro" and f in realized_raw]
    anchors = {
        "market": [MARKET],
        "market_macro": [MARKET, *macro],
        "market_top2": [MARKET, *others[:2]],
        "market_top4": [MARKET, *others[:4]],
    }
    return _EventModel(
        inputs=ev,
        horizon_weeks=horizon,
        basis=basis,
        frames=frames,
        covs=covs,
        realized=realized,
        anchors=anchors,
        unavailable=unavailable,
    )


_VARIANT_BASIS = {"V0": "raw", "V1": "raw", "V2": "rel", "V3": "rel", "V4": "rel", "V5": "units"}


def _full_vector(model: _EventModel, anchor_set: str, variant: str) -> pd.Series | None:
    """The complete factor vector a variant implies, in that variant's own basis."""
    basis_key = _VARIANT_BASIS[variant]
    if basis_key not in model.realized or (variant in model.unavailable):
        return None
    realized = model.realized[basis_key]
    names = [str(c) for c in model.frames[basis_key].columns]
    anchors = {f: realized[f] for f in model.anchors[anchor_set] if f in realized}
    if variant in COMPLETION_VARIANTS:
        return complete_shocks(model.covs[variant], anchors).shocks.reindex(names).fillna(0.0)
    return pd.Series({n: anchors.get(n, 0.0) for n in names}, dtype=float)


def _implied_errors(
    model: _EventModel, anchor_set: str, variant: str
) -> tuple[float, float] | None:
    """(Σ squared z-error, Σ squared realized z) over unanchored non-level factors.

    Scored in ABSOLUTE raw units so every variant is judged on the same targets;
    level factors are excluded because V5 states them in different units.
    """
    vec = _full_vector(model, anchor_set, variant)
    if vec is None:
        return None
    if _VARIANT_BASIS[variant] in ("rel", "units"):
        vec = pd.Series(model.basis.to_absolute(vec.to_dict()))
    cov = model.covs["V1"]
    sd = dict(zip((str(c) for c in cov.index), np.sqrt(np.diag(cov.to_numpy())), strict=True))
    scale = math.sqrt(model.horizon_weeks)
    err = base = 0.0
    anchored = set(model.anchors[anchor_set])
    for f, actual in model.realized["raw"].items():
        if f in anchored or f in LEVEL_TRANSFORMS or not sd.get(f, 0.0) > 0.0:
            continue
        denom = sd[f] * scale
        err += ((actual - float(vec.get(f, 0.0))) / denom) ** 2
        base += (actual / denom) ** 2
    return err, base


def _attribution_stability(
    frame: pd.DataFrame,
    ticker_returns: pd.DataFrame,
    weights: pd.Series,
    realized: Mapping[str, float],
    *,
    alpha: float,
    bootstrap: int,
    rng: np.random.Generator,
) -> AttributionStability | None:
    complete = frame.dropna(how="any")
    targets = ticker_returns.reindex(complete.index)
    names = [str(c) for c in complete.columns]
    move = pd.Series({n: float(realized.get(n, 0.0)) for n in names})

    def contributions(f: pd.DataFrame, y: pd.DataFrame) -> pd.Series:
        betas, _ = estimate_betas_and_stats(y, f, alpha=alpha)
        exposure = betas.T @ weights.reindex(betas.index).fillna(0.0)
        return exposure.reindex(names).fillna(0.0) * move

    full = contributions(complete, targets)
    total_abs = float(full.abs().sum())
    if total_abs == 0.0:
        return None
    top = str(full.abs().idxmax())
    n = len(complete)
    samples: list[pd.Series] = []
    for _ in range(bootstrap):
        idx = rng.integers(0, n, n)
        try:
            samples.append(
                contributions(
                    complete.iloc[idx].reset_index(drop=True),
                    targets.iloc[idx].reset_index(drop=True),
                )
            )
        except RuntimeError:
            continue
    if not samples:
        return None
    stacked = pd.DataFrame(samples)
    agreement = float(np.mean([str(s.abs().idxmax()) == top for s in samples]))
    return AttributionStability(
        top_driver=top,
        top_driver_agreement=agreement,
        dispersion=float(stacked.std(axis=0, ddof=1).fillna(0.0).sum()),
        market_share=float(abs(full.get(MARKET, 0.0))) / total_abs,
    )


def _evaluate_pair(
    model: _EventModel,
    book: BookInputs,
    config: Config,
    *,
    bootstrap: int,
    rng: np.random.Generator,
) -> PairRecord:
    def skip(reason: str) -> PairRecord:
        return PairRecord(
            event_id=book.event_id,
            portfolio_key=book.portfolio_key,
            horizon_weeks=model.horizon_weeks,
            realized_pnl=None,
            skipped_reason=reason,
        )

    if book.skipped_reason is not None or book.ticker_returns is None:
        return skip(book.skipped_reason or "no ticker returns")
    portfolio = get_portfolio(book.portfolio_key)
    exposures: dict[str, pd.Series] = {}
    idio_var = 0.0
    weights: pd.Series | None = None
    try:
        for basis_key, frame in model.frames.items():
            betas, stats = estimate_betas_for_portfolio(
                portfolio,
                lookback_weeks=config.beta_lookback_weeks,
                alpha=config.ridge_alpha,
                factor_returns=frame,
                ticker_returns=book.ticker_returns,
            )
            w = pd.Series(portfolio.holdings).reindex(betas.index).fillna(0.0)
            exposures[basis_key] = betas.T @ w
            if basis_key == "raw":
                weights = w
                idio_var = sum(
                    (float(w[t]) * s.idio_vol_weekly) ** 2 for t, s in stats.items() if t in w
                )
    except RuntimeError as exc:  # incl. InsufficientHistoryError
        return skip(f"{type(exc).__name__}: {exc}")

    h = model.horizon_weeks
    full_replay = {
        key: float(
            sum(float(exposures[key].get(f, 0.0)) * v for f, v in model.realized[key].items())
        )
        for key in exposures
        if key in model.realized
    }
    modeled: dict[str, float] = {}
    sigma: dict[str, float] = {}
    for anchor_set in ANCHOR_SETS:
        for variant in VARIANTS:
            basis_key = _VARIANT_BASIS[variant]
            if basis_key not in exposures:
                continue
            try:
                vec = _full_vector(model, anchor_set, variant)
            except np.linalg.LinAlgError:
                vec = None
            if vec is None:
                continue
            exposure = exposures[basis_key].reindex(vec.index).fillna(0.0)
            key = f"{anchor_set}:{variant}"
            modeled[key] = float(exposure @ vec)
            if variant in COMPLETION_VARIANTS:
                realized = model.realized[basis_key]
                anchors = {f: realized[f] for f in model.anchors[anchor_set] if f in realized}
                cond = complete_shocks(model.covs[variant], anchors).conditional_cov
                e_u = exposure.reindex(cond.index).fillna(0.0).to_numpy()
                factor_var = float(e_u @ cond.to_numpy() @ e_u)
                sigma[key] = math.sqrt(max(h * (factor_var + idio_var), 0.0))

    attribution: dict[str, AttributionStability] = {}
    if bootstrap > 0 and weights is not None:
        for basis_key in ("raw", "rel"):
            stability = _attribution_stability(
                model.frames[basis_key],
                book.ticker_returns,
                weights,
                model.realized[basis_key],
                alpha=config.ridge_alpha,
                bootstrap=bootstrap,
                rng=rng,
            )
            if stability is not None:
                attribution[basis_key] = stability

    return PairRecord(
        event_id=book.event_id,
        portfolio_key=book.portfolio_key,
        horizon_weeks=h,
        realized_pnl=book.realized_pnl,
        full_replay=full_replay,
        modeled=modeled,
        sigma=sigma,
        attribution=attribution,
    )


def _pearson(x: Sequence[float], y: Sequence[float]) -> float | None:
    if len(x) < 3:
        return None
    a, b = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if float(a.std()) == 0.0 or float(b.std()) == 0.0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def _variant_stats(
    pairs: Sequence[PairRecord],
    anchor_set: str,
    variant: str,
    implied: Mapping[tuple[str, str], tuple[float, float]],
) -> VariantStats:
    key = f"{anchor_set}:{variant}"
    rows = [p for p in pairs if key in p.modeled and p.realized_pnl is not None]
    errors = [p.modeled[key] - float(p.realized_pnl) for p in rows]
    sigmas = [p.sigma.get(key) for p in rows]
    cov1 = cov2 = None
    if variant in COMPLETION_VARIANTS and rows:
        inside1 = [abs(e) <= s for e, s in zip(errors, sigmas, strict=True) if s]
        inside2 = [abs(e) <= 2.0 * s for e, s in zip(errors, sigmas, strict=True) if s]
        cov1 = float(np.mean(inside1)) if inside1 else None
        cov2 = float(np.mean(inside2)) if inside2 else None
    err_sum, base_sum = implied.get((anchor_set, variant), (0.0, 0.0))
    return VariantStats(
        anchor_set=anchor_set,
        variant=variant,
        n=len(rows),
        mae=float(np.mean(np.abs(errors))) if errors else None,
        bias=float(np.mean(errors)) if errors else None,
        sign_hit_rate=(
            float(np.mean([(p.modeled[key] >= 0) == (p.realized_pnl >= 0) for p in rows]))
            if rows
            else None
        ),
        pearson_r=_pearson([p.modeled[key] for p in rows], [p.realized_pnl for p in rows]),
        coverage_1sd=cov1,
        coverage_2sd=cov2,
        implied_r2=(1.0 - err_sum / base_sum) if base_sum > 0.0 else None,
    )


def _mean_metric(pairs: Sequence[PairRecord], variant: str, metric: str) -> float | None:
    """A metric averaged over the four anchor sets on a FIXED set of pairs."""
    values: list[float] = []
    for anchor_set in ANCHOR_SETS:
        key = f"{anchor_set}:{variant}"
        rows = [p for p in pairs if key in p.modeled and p.realized_pnl is not None]
        if not rows:
            return None
        modeled = [p.modeled[key] for p in rows]
        realized = [float(p.realized_pnl) for p in rows]
        if metric == "mae":
            values.append(float(np.mean(np.abs(np.subtract(modeled, realized)))))
        elif metric == "bias":
            values.append(float(np.mean(np.subtract(modeled, realized))))
        elif metric == "r":
            r = _pearson(modeled, realized)
            if r is None:
                return None
            values.append(r)
    return float(np.mean(values))


def _gates(
    common: Sequence[PairRecord], attribution: Mapping[str, Mapping[str, float | None]]
) -> list[GateVerdict]:
    def fmt(x: float | None) -> str:
        return "n/a" if x is None else f"{x:.2%}"

    mae = {v: _mean_metric(common, v, "mae") for v in VARIANTS}
    r = {v: _mean_metric(common, v, "r") for v in VARIANTS}
    gates: list[GateVerdict] = []

    best = min(("V1", "V3"), key=lambda v: mae[v] if mae[v] is not None else math.inf)
    g1 = (
        mae["V0"] is not None
        and mae[best] is not None
        and r["V0"] is not None
        and r[best] is not None
        and mae[best] <= G1_MAE_RATIO * mae["V0"]
        and r[best] >= r["V0"]
    )
    gates.append(
        GateVerdict(
            "G1_completion",
            bool(g1),
            (
                f"best completion {best} mean MAE {fmt(mae[best])} vs V0 {fmt(mae['V0'])} "
                f"(needs ≤ {G1_MAE_RATIO:.0%} of V0); mean r {r[best]:.3f} vs V0 {r['V0']:.3f}"
                if r[best] is not None and r["V0"] is not None
                else "insufficient pairs"
            ),
        )
    )

    disp_raw = attribution.get("raw", {}).get("median_dispersion")
    disp_rel = attribution.get("rel", {}).get("median_dispersion")
    g2 = (
        mae["V1"] is not None
        and mae["V3"] is not None
        and abs(mae["V3"] - mae["V1"]) <= G2_MAE_TOLERANCE
        and disp_raw is not None
        and disp_rel is not None
        and disp_rel < disp_raw
    )
    gates.append(
        GateVerdict(
            "G2_relative_basis",
            bool(g2),
            f"V3 mean MAE {fmt(mae['V3'])} vs V1 {fmt(mae['V1'])} "
            f"(tolerance ±{G2_MAE_TOLERANCE:.2%}); median attribution dispersion "
            f"relative {fmt(disp_rel)} vs raw {fmt(disp_raw)}",
        )
    )

    g3 = (
        mae["V5"] is not None
        and mae["V3"] is not None
        and mae["V5"] <= mae["V3"] + G3_MAE_TOLERANCE
    )
    gates.append(
        GateVerdict(
            "G3_units",
            bool(g3),
            f"V5 mean MAE {fmt(mae['V5'])} vs V3 {fmt(mae['V3'])} "
            f"(tolerance +{G3_MAE_TOLERANCE:.2%})",
        )
    )
    return gates


def _collinearity(models: Sequence[_EventModel]) -> dict[str, object]:
    """Variance inflation at the most recent vintage, raw vs relative basis."""
    if not models:
        return {}
    latest = max(models, key=lambda m: m.inputs.start_date)

    def vif(frame: pd.DataFrame) -> dict[str, float]:
        corr = frame.dropna(how="any").corr().to_numpy()
        try:
            inv = np.linalg.inv(corr)
        except np.linalg.LinAlgError:
            return {str(c): math.inf for c in frame.columns}
        return {str(c): float(inv[i, i]) for i, c in enumerate(frame.columns)}

    raw = vif(latest.frames["raw"])
    rel = vif(latest.frames["rel"])
    rows = sorted(
        ({"factor": f, "vif_raw": raw[f], "vif_relative": rel.get(f)} for f in raw),
        key=lambda row: -float(row["vif_raw"]),
    )
    return {
        "vintage_event": latest.inputs.event_id,
        "vintage_end": str(latest.inputs.start_date),
        "median_vif_raw": float(np.median(list(raw.values()))),
        "median_vif_relative": float(np.median(list(rel.values()))),
        "rows": rows,
    }


def _transport(inputs: StudyInputs) -> dict[str, object]:
    """What production's percent-of-level TNX move becomes at today's yield level."""
    ref = inputs.reference_tnx_level
    rows = []
    for ev in inputs.events:
        pct = ev.realized.get("TNX")
        y0 = ev.start_levels.get("TNX")
        true_move = ev.realized_levels.get("TNX")
        if pct is None or y0 is None or true_move is None:
            continue
        actual_bp = true_move * 10_000.0
        transported_bp = pct * ref * 100.0 if ref is not None else None
        rows.append(
            {
                "event_id": ev.event_id,
                "start_yield_pct": y0,
                "pct_of_level_move": pct,
                "actual_bp": actual_bp,
                "transported_bp": transported_bp,
                "distortion_bp": (
                    transported_bp - actual_bp if transported_bp is not None else None
                ),
            }
        )
    rows.sort(key=lambda r: -abs(r["distortion_bp"] or 0.0))
    distortions = [abs(r["distortion_bp"]) for r in rows if r["distortion_bp"] is not None]
    return {
        "reference_yield_pct": ref,
        "reference_date": inputs.reference_date,
        "median_abs_distortion_bp": float(np.median(distortions)) if distortions else None,
        "max_abs_distortion_bp": float(max(distortions)) if distortions else None,
        "rows": rows,
    }


def _attribution_summary(pairs: Sequence[PairRecord]) -> dict[str, dict[str, float | None]]:
    out: dict[str, dict[str, float | None]] = {}
    for basis_key in ("raw", "rel"):
        values = [p.attribution[basis_key] for p in pairs if basis_key in p.attribution]
        if not values:
            out[basis_key] = {"n": 0, "median_dispersion": None}
            continue
        out[basis_key] = {
            "n": len(values),
            "median_dispersion": float(np.median([v.dispersion for v in values])),
            "mean_top_driver_agreement": float(np.mean([v.top_driver_agreement for v in values])),
            "mean_market_share": float(np.mean([v.market_share for v in values])),
            "share_top_driver_is_market": float(np.mean([v.top_driver == MARKET for v in values])),
        }
    return out


def evaluate(
    inputs: StudyInputs,
    *,
    config: Config | None = None,
    bootstrap: int = DEFAULT_BOOTSTRAP,
    seed: int = DEFAULT_SEED,
    replay_reference: Mapping[tuple[str, str], float] | None = None,
) -> tuple[list[PairRecord], StudySummary]:
    """Score every variant on every computable pair. Pure: no network access."""
    config = config or load_config()
    rng = np.random.default_rng(seed)
    models: dict[str, _EventModel] = {}
    event_skips: dict[str, str] = {}
    for ev in inputs.events:
        built = _build_event_model(ev)
        if isinstance(built, str):
            event_skips[ev.event_id] = built
        else:
            models[ev.event_id] = built

    pairs: list[PairRecord] = []
    for book in inputs.books:
        model = models.get(book.event_id)
        if model is None:
            pairs.append(
                PairRecord(
                    event_id=book.event_id,
                    portfolio_key=book.portfolio_key,
                    horizon_weeks=None,
                    realized_pnl=None,
                    skipped_reason=event_skips.get(book.event_id, "event unavailable"),
                )
            )
            continue
        pairs.append(_evaluate_pair(model, book, config, bootstrap=bootstrap, rng=rng))

    computed = [p for p in pairs if p.skipped_reason is None]
    implied: dict[tuple[str, str], tuple[float, float]] = {}
    for model in models.values():
        if not any(p.event_id == model.inputs.event_id for p in computed):
            continue
        for anchor_set in ANCHOR_SETS:
            for variant in VARIANTS:
                try:
                    scored = _implied_errors(model, anchor_set, variant)
                except np.linalg.LinAlgError:
                    scored = None
                if scored is None:
                    continue
                err, base = implied.get((anchor_set, variant), (0.0, 0.0))
                implied[(anchor_set, variant)] = (err + scored[0], base + scored[1])

    stats = [_variant_stats(computed, a, v, implied) for a in ANCHOR_SETS for v in VARIANTS]
    gate_keys = [f"{a}:{v}" for a in ANCHOR_SETS for v in ("V0", "V1", "V3", "V5")]
    common = [p for p in computed if all(k in p.modeled for k in gate_keys)]
    attribution = _attribution_summary(common)
    mean_by_variant = {
        v: {
            "mae": _mean_metric(common, v, "mae"),
            "bias": _mean_metric(common, v, "bias"),
            "r": _mean_metric(common, v, "r"),
        }
        for v in VARIANTS
    }

    crosscheck: dict[str, float | int | None] = {"n_compared": 0, "max_abs_diff": None}
    if replay_reference:
        diffs = [
            abs(p.full_replay["raw"] - replay_reference[(p.event_id, p.portfolio_key)])
            for p in computed
            if "raw" in p.full_replay and (p.event_id, p.portfolio_key) in replay_reference
        ]
        crosscheck = {
            "n_compared": len(diffs),
            "max_abs_diff": float(max(diffs)) if diffs else None,
        }

    summary = StudySummary(
        n_pairs=len(pairs),
        n_computed=len(computed),
        n_common=len(common),
        variant_stats=stats,
        mean_by_variant=mean_by_variant,
        attribution=attribution,
        gates=_gates(common, attribution),
        collinearity=_collinearity(list(models.values())),
        transport=_transport(inputs),
        replay_crosscheck=crosscheck,
        regression_spec=inputs.regression_spec,
        events_version=inputs.events_version,
        factor_universe_version=inputs.factor_universe_version,
        weights_as_of=inputs.weights_as_of,
        gathered_at=inputs.gathered_at,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        bootstrap=bootstrap,
    )
    return pairs, summary


# ---------------------------------------------------------------------- render


def _pct(value: float | None, digits: int = 2) -> str:
    return "—" if value is None else f"{value * 100:+.{digits}f}%"


def _abs_pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.2f}%"


def _num(value: float | None, digits: int = 3) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def render_markdown(pairs: Sequence[PairRecord], summary: StudySummary) -> str:
    """The human-readable study artifact (fully regenerated, never hand-edited)."""
    lines = [
        "# Completion study — coherent scenarios and an explainable basis",
        "",
        "> Generated by `uv run python scripts/run_completion_study.py`. Do not hand-edit.",
        "> No language model is involved anywhere in this study.",
        "",
        "## What this measures",
        "",
        "Production fills every factor a scenario does not name with **exactly zero**. "
        "This study asks how much of a book's realized outcome each alternative recovers "
        "when the scenario states only a few moves correctly. For each (historical event × "
        "sample book) pair, the anchors are the event's own realized moves for the anchor "
        "set, betas are estimated at the event's vintage (no look-ahead), and the modeled "
        "factor P&L is compared with the book's realized buy-and-hold USD return.",
        "",
        "Completion uses the conditional expectation of the unanchored factors given the "
        "anchors, `s_u = Σ_ua Σ_aa⁻¹ a`, with Σ the vintage weekly covariance after "
        "Ledoit–Wolf shrinkage of the correlations. The relative basis replaces each "
        "non-market equity factor `k` by `r_k − b_k·r_SPY`.",
        "",
        "| variant | meaning |",
        "|---|---|",
        *(f"| {v} | {VARIANT_LABELS[v]} |" for v in VARIANTS),
        "",
        "| anchor set | anchors |",
        "|---|---|",
        *(f"| `{a}` | {ANCHOR_SET_LABELS[a]} |" for a in ANCHOR_SETS),
        "",
        "Honest read: anchors are realized moves, so this is an upper bound on what a "
        "perfectly specified scenario could deliver, not the LLM's skill. Books are today's "
        "frozen weights replayed onto history (survivorship and drift), and the modeled "
        "side is factor-only. `top2`/`top4` pick the most extreme realized moves, which "
        "uses hindsight to mimic a scenario that names its salient drivers.",
        "",
        "## Gates (pre-registered before the first run)",
        "",
        "| gate | verdict | evidence |",
        "|---|---|---|",
        *(f"| {g.key} | {'PASS' if g.passed else 'FAIL'} | {g.detail} |" for g in summary.gates),
        "",
        f"Gates are computed on the {summary.n_common} pairs where every gated variant "
        f"exists ({summary.n_computed} of {summary.n_pairs} pairs computed). G1: the better "
        f"completion variant cuts mean MAE to ≤ {G1_MAE_RATIO:.0%} of V0 without lowering "
        f"mean Pearson r. G2: the relative basis keeps MAE within ±{G2_MAE_TOLERANCE:.2%} of "
        "V1 and lowers the median bootstrap attribution dispersion. G3: yield-change / log "
        f"units keep MAE within +{G3_MAE_TOLERANCE:.2%} of V3.",
        "",
        "## Mean over anchor sets (gate population)",
        "",
        "| variant | mean MAE | mean bias | mean r |",
        "|---|---:|---:|---:|",
        *(
            f"| {v} | {_abs_pct(summary.mean_by_variant[v]['mae'])} | "
            f"{_pct(summary.mean_by_variant[v]['bias'])} | "
            f"{_num(summary.mean_by_variant[v]['r'])} |"
            for v in VARIANTS
        ),
        "",
        "## By anchor set (all computable pairs per variant)",
        "",
        "| anchors | variant | n | MAE | bias | sign | r | ±1σ cover | ±2σ cover | implied R² |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        *(
            f"| `{s.anchor_set}` | {s.variant} | {s.n} | {_abs_pct(s.mae)} | {_pct(s.bias)} | "
            f"{_abs_pct(s.sign_hit_rate)} | {_num(s.pearson_r)} | {_abs_pct(s.coverage_1sd)} | "
            f"{_abs_pct(s.coverage_2sd)} | {_num(s.implied_r2)} |"
            for s in summary.variant_stats
        ),
        "",
        "Implied R² scores the unanchored, non-level factors in standardized units against "
        "their realized moves; holding them at zero scores exactly 0. The ±σ coverage is "
        "the share of pairs whose realized return falls inside the single uncertainty band "
        "`h·[E_uᵀ Σ_u|a E_u + Σ wᵢ²σᵢ²]`; a calibrated 1σ band covers about 68%.",
        "",
        "## Attribution stability (full realized vector, bootstrap of weeks)",
        "",
        f"Each pair's betas are re-estimated on {summary.bootstrap} bootstrap resamples of "
        "its vintage weeks. Dispersion is the summed standard deviation of the per-factor "
        "contributions; agreement is how often the largest contributor stays the same.",
        "",
        "| basis | pairs | median dispersion | top-driver agreement | market share of "
        "|contrib| | top driver is market |",
        "|---|---:|---:|---:|---:|---:|",
        *(
            f"| {basis_key} | {int(vals.get('n') or 0)} | "
            f"{_abs_pct(vals.get('median_dispersion'))} | "
            f"{_abs_pct(vals.get('mean_top_driver_agreement'))} | "
            f"{_abs_pct(vals.get('mean_market_share'))} | "
            f"{_abs_pct(vals.get('share_top_driver_is_market'))} |"
            for basis_key, vals in summary.attribution.items()
        ),
        "",
    ]

    col = summary.collinearity
    if col:
        lines.extend(
            [
                "## Collinearity of the factor basis",
                "",
                f"Variance inflation factors at the most recent vintage "
                f"(`{col['vintage_event']}`, data to {col['vintage_end']}). Median VIF: raw "
                f"{float(col['median_vif_raw']):.1f}, relative "
                f"{float(col['median_vif_relative']):.1f}.",
                "",
                "| factor | VIF raw | VIF relative |",
                "|---|---:|---:|",
                *(
                    f"| {row['factor']} | {float(row['vif_raw']):.1f} | "
                    f"{float(row['vif_relative']):.1f} |"
                    for row in col["rows"]  # type: ignore[union-attr]
                ),
                "",
            ]
        )

    tr = summary.transport
    if tr and tr.get("rows"):
        ref = tr.get("reference_yield_pct")
        lines.extend(
            [
                "## Rate units: transporting an analog's 10Y move",
                "",
                "Production states the 10Y factor as a percent change of the yield LEVEL. "
                "Applied to a different starting level, the same percent move becomes a "
                "different number of basis points. Reference level: "
                f"{_num(ref, 2)}% on {tr.get('reference_date')}. Median absolute "
                f"distortion {_num(tr.get('median_abs_distortion_bp'), 0)}bp, max "
                f"{_num(tr.get('max_abs_distortion_bp'), 0)}bp.",
                "",
                "| event | start 10Y | % of level | actual bp | bp at reference | distortion |",
                "|---|---:|---:|---:|---:|---:|",
                *(
                    f"| {r['event_id']} | {float(r['start_yield_pct']):.2f}% | "
                    f"{float(r['pct_of_level_move']) * 100:+.1f}% | "
                    f"{float(r['actual_bp']):+.0f} | {_num(r['transported_bp'], 0)} | "
                    f"{_num(r['distortion_bp'], 0)} |"
                    for r in tr["rows"]  # type: ignore[union-attr]
                ),
                "",
            ]
        )

    cc = summary.replay_crosscheck
    lines.extend(
        [
            "## Cross-check against the engine replay",
            "",
            f"The full realized vector through raw-basis betas reproduces the engine "
            f"replay's modeled P&L on {cc.get('n_compared')} pairs; max absolute difference "
            f"{_num(cc.get('max_abs_diff'), 6)}.",
            "",
            "## Per pair (anchor set `market_top4`)",
            "",
            "| event | book | realized | full replay | V0 | V1 | V3 | V5 | ±1σ (V3) |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for p in pairs:
        if p.skipped_reason is not None:
            continue
        m = p.modeled
        lines.append(
            f"| {p.event_id} | {p.portfolio_key} | {_pct(p.realized_pnl)} | "
            f"{_pct(p.full_replay.get('raw'))} | {_pct(m.get('market_top4:V0'))} | "
            f"{_pct(m.get('market_top4:V1'))} | {_pct(m.get('market_top4:V3'))} | "
            f"{_pct(m.get('market_top4:V5'))} | {_abs_pct(p.sigma.get('market_top4:V3'))} |"
        )
    skipped = [p for p in pairs if p.skipped_reason is not None]
    if skipped:
        lines.extend(["", "## Skipped pairs", "", "| event | book | reason |", "|---|---|---|"])
        for p in skipped:
            reason = (p.skipped_reason or "").replace("|", "/")
            if len(reason) > 140:
                reason = reason[:137] + "..."
            lines.append(f"| {p.event_id} | {p.portfolio_key} | {reason} |")
    lines.extend(
        [
            "",
            "## Provenance",
            "",
            f"- regression_spec: `{summary.regression_spec}`",
            f"- events_version: `{summary.events_version}`",
            f"- factor_universe_version: `{summary.factor_universe_version}`",
            f"- sample weights as of: {summary.weights_as_of}",
            f"- inputs gathered: {summary.gathered_at}",
            f"- generated: {summary.generated_at}",
            "",
        ]
    )
    return "\n".join(lines)
