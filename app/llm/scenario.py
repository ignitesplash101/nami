"""End-to-end scenario orchestrator: cache -> analog select -> envelope -> shock propose -> betas -> P&L -> cache write.

Also exposes `adjust_scenario_shocks` for the iterative shock-editing path: given a
canonical scenario's cache key plus either manual slider overrides or a natural-language
adjustment prompt, return a derived ScenarioResult with the same narrative / citations /
analogs / periphery but recomputed factor shocks and P&L.
"""

from __future__ import annotations

import logging
import math
import statistics
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pandas as pd

from app.config import Config, load_config
from app.data.cache import CacheProtocol, CloudStorageCache
from app.data.fx import convert_weekly_returns_to_usd
from app.data.market import compute_weekly_returns, fetch_weekly_prices
from app.data.market_cache import MARKET_CACHE_VERSION
from app.data.marking import MarkResult, mark_book
from app.data.quant_sources import PUBLIC_DATA_CACHE_VERSION
from app.data.sample_portfolios import CASH_TICKER, Portfolio, get_portfolio, sample_benchmark
from app.factors.analogs import (
    HistoricalEvent,
    compute_envelope_from_matrix,
    event_summaries,
    events_version,
    filter_events_as_of,
    load_events,
    summarize_events,
)
from app.factors.quant_exposure import QUANT_EXPOSURE_SPEC
from app.factors.quant_inputs import prepare_quant_inputs
from app.factors.quant_scenario import (
    QUANT_SCENARIO_SPEC,
    direct_attribution,
)
from app.factors.quant_scenario import (
    run_quant_scenario as run_quant_model,
)
from app.factors.regression import (
    MIN_REGRESSION_WEEKS,
    REGRESSION_ESTIMATOR_ID,
    TickerRegressionStats,
    estimate_betas_for_portfolio,
    fetch_factor_returns_with_history,
    regression_spec,
)
from app.factors.shocks import analog_replay_pnl, portfolio_idio_band, portfolio_pnl
from app.factors.universe import FACTORS, factor_universe_version
from app.factors.warm_cache import (
    get_event_returns_matrix,
    get_factor_returns_with_history,
    get_selected_event_returns_matrix,
)
from app.llm.adjust_validation import validate_factor_overrides
from app.llm.gemini_client import GeminiClient
from app.llm.prompts import PROMPT_VERSION
from app.llm.risk_diagnostics import generate_risk_diagnostics
from app.llm.schemas import (
    AnalogEventReturns,
    AnalogReplay,
    AnalogReplayEntry,
    AnalogSelection,
    FactorShock,
    HistoricalModelRangeResult,
    PnLUncertainty,
    PortfolioPnL,
    QuantExposureResult,
    QuantSourceVersionResult,
    QuantSupportResult,
    RegressionQuality,
    ScenarioResult,
    SeverityLadder,
    ShockAdjustment,
    TickerRegressionQuality,
)
from app.llm.validation import MIN_ENVELOPE_COUNT_FOR_BAND_CHECK
from app.utils.calendar import latest_market_date, resolve_effective_market_date
from app.utils.hashing import scenario_cache_key

logger = logging.getLogger(__name__)

QUANT_ENGINE_SPEC = (
    f"quant-v2|market={MARKET_CACHE_VERSION}|public={PUBLIC_DATA_CACHE_VERSION}|"
    f"exposure={QUANT_EXPOSURE_SPEC}|scenario={QUANT_SCENARIO_SPEC}"
)
QUANT_MIN_EVENT_END = date(2007, 7, 31)

# Minimum number of historical analog events required for envelope computation.
# Surfaces as a 422 error from the API layer rather than a raw Gemini failure.
MIN_ELIGIBLE_ANALOG_EVENTS = 2

# Enforced analog-selection cardinality (the prompt asks for "2 to 5"; this is the
# enforcement of record — it also covers the pinned-decomposition path, which
# bypasses the LLM entirely). Below 2 the envelope is a single point; above 5 the
# analog set stops being a mechanism match. Out-of-range selections raise
# ValueError → HTTP 422.
MIN_SELECTED_ANALOGS = 2
MAX_SELECTED_ANALOGS = 5

ProgressCallback = Callable[[str, str], None]
"""Optional progress hook for `run_scenario`. Called as `progress(stage, status)`
at stage boundaries (e.g. ("analogs", "start") then ("analogs", "done")). Stages,
in order: cache_check, cache_hit OR (market+analogs+envelope+narrative+betas+
attribution). The SSE wrapper emits its own terminal {"stage":"done", "result":...}
event after `run_scenario` returns, so this callback never emits "done" itself.
Unused on the blocking path.
"""


def _noop(_stage: str, _status: str) -> None:
    pass


def compute_scenario_cache_key(
    scenario_text: str,
    portfolio: str | Portfolio,
    *,
    config: Config | None = None,
    market_date: date | None = None,
    position_quantities: dict[str, float] | None = None,
    horizon: int = 21,
    severity: float = 1.0,
    benchmark: str | None = None,
) -> str:
    """Compute the cache key the same way `run_scenario` does.

    Used by API handlers to surface the key to the client so subsequent
    adjustment requests can reference the canonical cached result. `market_date`
    is resolved to the effective NYSE trading day to match run_scenario's keying.

    In quantity (MTM) mode the weights are price-derived, so the key is folded on
    the raw `position_quantities` and the (provisional) holdings are dropped from
    the hash — mirroring `run_scenario`.
    """
    config = config or load_config()
    # Mirror run_scenario's anchoring exactly so keys never diverge: the live
    # anchor is the latest NYSE close, computed once.
    live_as_of = latest_market_date()
    requested_as_of = market_date or live_as_of
    effective_as_of = resolve_effective_market_date(requested_as_of, today_fn=lambda: live_as_of)
    portfolio_obj, resolved_key = _resolve_portfolio(portfolio, None)
    is_quant = config.engine_mode == "quant_v2"
    benchmark_ticker = (
        _resolve_benchmark(portfolio_obj, resolved_key, benchmark) if is_quant else None
    )
    return scenario_cache_key(
        scenario_text=scenario_text,
        portfolio_key=resolved_key,
        portfolio_holdings={} if position_quantities else portfolio_obj.holdings,
        market_date=effective_as_of,
        model_id=config.vertex_model_id,
        prompt_version=PROMPT_VERSION,
        factor_universe_version=factor_universe_version(),
        events_version=events_version(),
        regression_spec=regression_spec(
            lookback_weeks=config.beta_lookback_weeks, alpha=config.ridge_alpha
        ),
        position_quantities=position_quantities,
        engine_mode=config.engine_mode,
        horizon=horizon if is_quant else 21,
        severity=severity if is_quant else 1.0,
        engine_spec=QUANT_ENGINE_SPEC if config.engine_mode != "legacy" else None,
        benchmark_ticker=benchmark_ticker,
    )


def _resolve_portfolio(
    portfolio: str | Portfolio | None,
    portfolio_key: str | None,
) -> tuple[Portfolio, str]:
    if portfolio is not None and portfolio_key is not None:
        raise ValueError("Pass either `portfolio` or `portfolio_key`, not both")
    if portfolio is None and portfolio_key is None:
        raise ValueError("Must pass `portfolio` (str|Portfolio) or `portfolio_key` (str)")

    if isinstance(portfolio, Portfolio):
        return portfolio, "custom"
    if isinstance(portfolio, str):
        return get_portfolio(portfolio), portfolio
    assert portfolio_key is not None  # narrowed by the guards above
    return get_portfolio(portfolio_key), portfolio_key


def _apply_mtm(
    result: ScenarioResult,
    *,
    position_quantities: dict[str, float] | None = None,
    portfolio_nav: float | None = None,
    reporting_currency: str | None = None,
    precomputed: MarkResult | None = None,
) -> ScenarioResult:
    """Attach marked dollar metadata to a return-space result (never mutates in place).

    Quantity mode marks the book — reusing `precomputed` if supplied, else
    re-marking from `position_quantities` at `result.market_date` — and is
    fail-closed (a missing/stale price or FX raises `MarkingError`). NAV-scalar
    mode attaches the given NAV. Dollars themselves are derived client-side as
    `return_field × portfolio_nav` (the engine is linear), so nothing dollar-valued
    is stored beyond NAV + marking metadata. Returns `result` unchanged when no MTM
    was requested. These fields are intentionally NEVER written back to the cache.
    """
    currency = reporting_currency or "USD"
    if position_quantities:
        mark = precomputed or mark_book(
            position_quantities, as_of=result.market_date, reporting_currency=currency
        )
        return result.model_copy(
            update={
                "portfolio_nav": mark.nav,
                "reporting_currency": mark.reporting_currency,
                "position_quantities": dict(position_quantities),
                "position_values": mark.position_values,
                "mark_prices": mark.mark_prices,
                "price_date_by_ticker": mark.price_date_by_ticker,
                "fx_rates": mark.fx_rates,
                "fx_date_by_currency": mark.fx_date_by_currency,
            }
        )
    if portfolio_nav is not None:
        return result.model_copy(
            update={"portfolio_nav": float(portfolio_nav), "reporting_currency": currency}
        )
    return result


def _market_tickers(portfolio: Portfolio) -> list[str]:
    """Portfolio tickers excluding the non-market CASH sentinel (never fetched)."""
    return [t for t in portfolio.tickers if t != CASH_TICKER]


def _estimate_betas_cash_aware(
    portfolio: Portfolio,
    *,
    config: Config,
    factor_returns,
    ticker_returns,
) -> tuple[pd.DataFrame, dict[str, TickerRegressionStats]]:
    """(Betas, fit stats) for the book, injecting a zero-beta row for a CASH sleeve.

    CASH is never sent to yfinance. The beta estimator runs on a cash-free
    (re-normalized — betas are weight-independent) portfolio so its sum-to-1 +
    ticker-membership invariants hold; the CASH row is then injected as all-zeros
    so `portfolio_pnl` carries CASH at exactly 0 factor contribution while its
    weight still dilutes the rest. The stats dict deliberately carries NO entry
    for CASH — no regression ran for it. Non-cash books take the unchanged path
    (and the same `estimate_betas_for_portfolio` call the test mocks patch).
    """
    if CASH_TICKER not in portfolio.holdings:
        return estimate_betas_for_portfolio(
            portfolio,
            lookback_weeks=config.beta_lookback_weeks,
            alpha=config.ridge_alpha,
            factor_returns=factor_returns,
            ticker_returns=ticker_returns,
        )
    market = {t: w for t, w in portfolio.holdings.items() if t != CASH_TICKER}
    total = sum(market.values()) or 1.0
    beta_portfolio = Portfolio(
        name=portfolio.name,
        description=portfolio.description,
        holdings={t: w / total for t, w in market.items()},
    )
    betas, stats = estimate_betas_for_portfolio(
        beta_portfolio,
        lookback_weeks=config.beta_lookback_weeks,
        alpha=config.ridge_alpha,
        factor_returns=factor_returns,
        ticker_returns=ticker_returns,
    )
    betas.loc[CASH_TICKER] = 0.0
    return betas, stats


def _book_betas(
    book: Portfolio, config: Config
) -> tuple[pd.DataFrame, dict[str, TickerRegressionStats], str]:
    """Shared LLM-free market path for the pre-scenario surfaces (profile,
    events replay): weekly prices → USD conversion → warm factor cache →
    cash-aware ridge. Returns (betas, stats, as_of_iso)."""
    prices = fetch_weekly_prices(_market_tickers(book), lookback_weeks=config.beta_lookback_weeks)
    ticker_returns = convert_weekly_returns_to_usd(compute_weekly_returns(prices))
    factor_returns, _history = get_factor_returns_with_history(
        lookback_weeks=config.beta_lookback_weeks
    )
    betas, stats = _estimate_betas_cash_aware(
        book, config=config, factor_returns=factor_returns, ticker_returns=ticker_returns
    )
    return betas, stats, str(pd.Timestamp(ticker_returns.index.max()).date())


def compute_events_replay(
    portfolio: str | Portfolio,
    *,
    config: Config | None = None,
) -> dict[str, object]:
    """LLM-free all-events replay: every registry event through the CURRENT book.

    Each event's realized factor returns are pushed through the book's current
    betas via `analog_replay_pnl` — the same math as a result's analog-replay
    strip, generalized from the selected analogs to the full registry and
    available before any paid run. Rows are sorted worst-first. Factor-model
    only (no periphery/idiosyncratic effects), current betas on historical
    windows — a severity screen, not a backtest and not a forecast.
    """
    config = config or load_config()
    book = get_portfolio(portfolio) if isinstance(portfolio, str) else portfolio

    betas, _stats, as_of = _book_betas(book, config)
    events = load_events()
    matrix = get_event_returns_matrix()

    per_event: list[dict[str, object]] = []
    for event_id, row in matrix.iterrows():
        event = events[str(event_id)]
        pnl, covered = analog_replay_pnl(book, betas, row.to_dict())
        per_event.append(
            {
                "event_id": event.id,
                "name": event.name,
                "start_date": event.start_date.isoformat(),
                "end_date": event.end_date.isoformat(),
                "window_calendar_days": (event.end_date - event.start_date).days,
                "tags": list(event.tags),
                "replay_pnl": float(pnl),
                "n_factors_covered": int(covered),
            }
        )
    per_event.sort(key=lambda r: r["replay_pnl"])  # worst-first

    return {
        "portfolio_name": book.name,
        "as_of": as_of,
        "n_factors": int(betas.shape[1]),
        "per_event": per_event,
    }


def compute_book_profile(
    portfolio: str | Portfolio,
    *,
    config: Config | None = None,
) -> dict[str, object]:
    """LLM-free pre-scenario book profile — "what am I holding?" for free.

    Runs the exact market path a scenario would (weekly prices, USD conversion,
    warm factor cache, the cash-aware standardized ridge) with zero Gemini
    involvement, and returns a JSON-safe dict: portfolio-level factor exposures
    (Σᵢ wᵢ·βᵢ,f per factor), per-name fit quality sorted by weight, and the
    1-week ±1σ idio dispersion floor. Nothing here is cached beyond the market
    layers — the profile recomputes from current data on every call.
    """
    config = config or load_config()
    book = get_portfolio(portfolio) if isinstance(portfolio, str) else portfolio

    betas, stats, as_of = _book_betas(book, config)

    weights = pd.Series(book.holdings, dtype=float).reindex(betas.index).fillna(0.0)
    exposures = betas.mul(weights, axis=0).sum(axis=0)
    idio_band_weekly = float(
        sum((book.holdings.get(t, 0.0) * s.idio_vol_weekly) ** 2 for t, s in stats.items()) ** 0.5
    )

    def _name_row(ticker: str, weight: float) -> dict[str, object]:
        s = stats.get(ticker)
        return {
            "ticker": ticker,
            "weight": float(weight),
            "r2": (float(s.r2) if s else None),
            "r2_adj": (float(s.r2_adj) if s and s.r2_adj is not None else None),
            "n_obs": (int(s.n_obs) if s else None),
            "idio_vol_weekly": (float(s.idio_vol_weekly) if s else None),
        }

    per_name = [
        _name_row(t, w)
        for t, w in sorted(book.holdings.items(), key=lambda kv: kv[1], reverse=True)
    ]
    return {
        "portfolio_name": book.name,
        "as_of": as_of,
        "factor_exposures": {str(f): float(v) for f, v in exposures.items()},
        "per_name": per_name,
        "idio_band_weekly": idio_band_weekly,
        "n_factors": int(betas.shape[1]),
    }


def _per_event_records(
    returns_matrix: pd.DataFrame,
    events: dict[str, HistoricalEvent],
) -> list[dict[str, object]]:
    """JSON-safe per-analog factor returns + window length (selection order).

    The same payload feeds the shock-extraction prompt's PER-EVENT section and
    `ScenarioResult.analog_event_returns`. Values are 4-dp decimal total returns
    over the event's exact-day window; None where the factor's ETF predates it.
    """
    records: list[dict[str, object]] = []
    for event_id, row in returns_matrix.iterrows():
        event = events[str(event_id)]
        records.append(
            {
                "event_id": str(event_id),
                "window_calendar_days": (event.end_date - event.start_date).days,
                "factor_returns": {
                    str(f): (round(float(v), 4) if pd.notna(v) else None) for f, v in row.items()
                },
            }
        )
    return records


def _analog_replay_block(
    portfolio: Portfolio,
    betas: pd.DataFrame,
    returns_matrix: pd.DataFrame,
) -> AnalogReplay:
    """Factor-only replay of each selected analog through the run's betas.

    Rows arrive (and leave) in selection order. Deterministic post-processing of
    the same keyed inputs as the betas and the envelope — no LLM involvement —
    so the block is cached with the canonical result like `regression_quality`.
    """
    entries: list[AnalogReplayEntry] = []
    for event_id, row in returns_matrix.iterrows():
        replay_pnl, covered = analog_replay_pnl(portfolio, betas, row.to_dict())
        entries.append(
            AnalogReplayEntry(
                event_id=str(event_id),
                replay_pnl=replay_pnl,
                n_factors_covered=covered,
                n_factors_total=len(row),
            )
        )
    pnls = [e.replay_pnl for e in entries]
    return AnalogReplay(
        per_event=entries,
        min_pnl=min(pnls),
        median_pnl=float(statistics.median(pnls)),
        max_pnl=max(pnls),
    )


def _pnl_uncertainty_block(
    stats: dict[str, TickerRegressionStats],
    holdings: dict[str, float],
    window_calendar_days: list[int],
) -> PnLUncertainty | None:
    """±1σ idio band over the median selected-analog horizon.

    Shock-independent (residual vols + analog windows only) and deterministic
    from the keyed vintage — cached with the canonical, recomputed on
    adjustments from the same inputs. None when no analog windows are known
    (old canonicals without `analog_event_returns`).
    """
    if not window_calendar_days:
        return None
    horizon_weeks = float(statistics.median(window_calendar_days)) / 7.0
    weekly, band = portfolio_idio_band(stats, holdings, horizon_weeks)
    return PnLUncertainty(
        band_1sigma=band,
        portfolio_idio_vol_weekly=weekly,
        horizon_weeks=horizon_weeks,
    )


def _severity_ladder_block(
    portfolio: Portfolio,
    betas: pd.DataFrame,
    factor_shocks: list[FactorShock],
    factor_envelope: dict[str, dict[str, float]],
    *,
    periphery_total: float,
) -> SeverityLadder:
    """Envelope-constrained worst/base/best engine P&L (vertex of the shock box).

    P&L is linear in each factor's shock, so its min/max over the per-factor
    [p10, p90] box is attained by pushing each banded shock to whichever band
    edge is adverse (resp. favorable) for THIS book's exposure
    `E_f = Σ_t w_t·β_{t,f}` — NOT by all-p10/all-p90 rungs, whose ordering a
    negative exposure flips. Banded means envelope `count ≥ 3` with finite
    p10/p90 — the same gate `validate_factor_overrides` puts on the adjustment
    sliders; low-evidence shocks are held at their proposed values in every
    rung, removed (0.0) shocks contribute nothing, and the periphery total
    rides along unchanged. `worst ≤ base ≤ best` holds whenever every banded
    shock sits inside its own band (the proposal and adjustment validators
    both enforce this). Shock-DEPENDENT — recomputed on adjustments, unlike
    the preserved `analog_replay`.
    """
    weights = pd.Series(portfolio.holdings, dtype=float).reindex(betas.index).fillna(0.0)
    exposures = betas.mul(weights, axis=0).sum(axis=0)

    worst = base = best = periphery_total
    n_banded = 0
    n_held = 0
    for fs in factor_shocks:
        if fs.shock == 0.0 or fs.factor not in exposures.index:
            continue
        exposure = float(exposures[fs.factor])
        base_contrib = exposure * fs.shock
        base += base_contrib

        env = factor_envelope.get(fs.factor) or {}
        count = env.get("count")
        p10 = env.get("p10")
        p90 = env.get("p90")
        banded = (
            count is not None
            and count >= MIN_ENVELOPE_COUNT_FOR_BAND_CHECK
            and p10 is not None
            and p90 is not None
            and math.isfinite(p10)
            and math.isfinite(p90)
        )
        if banded:
            lo = exposure * float(p10)
            hi = exposure * float(p90)
            worst += min(lo, hi)
            best += max(lo, hi)
            n_banded += 1
        else:
            worst += base_contrib
            best += base_contrib
            n_held += 1

    return SeverityLadder(
        worst_pnl=float(worst),
        base_pnl=float(base),
        best_pnl=float(best),
        n_banded=n_banded,
        n_held=n_held,
    )


def _regression_quality_block(
    stats: dict[str, TickerRegressionStats],
    config: Config,
) -> RegressionQuality:
    """Map the estimator's fit stats into the cached `ScenarioResult` block."""
    return RegressionQuality(
        estimator=REGRESSION_ESTIMATOR_ID,
        lookback_weeks=config.beta_lookback_weeks,
        alpha=config.ridge_alpha,
        min_obs=MIN_REGRESSION_WEEKS,
        by_ticker={
            ticker: TickerRegressionQuality(
                r2=s.r2,
                n_obs=s.n_obs,
                idio_vol_weekly=s.idio_vol_weekly,
                r2_adj=s.r2_adj,
                p_eff=s.p_eff,
            )
            for ticker, s in stats.items()
        },
    )


def _resolve_benchmark(
    portfolio: Portfolio, resolved_key: str, benchmark: str | None
) -> str | None:
    """Benchmark ticker: explicit request wins, else the sample's own benchmark."""
    if benchmark:
        return benchmark.strip().upper() or None
    if portfolio.benchmark:
        return portfolio.benchmark
    return sample_benchmark(resolved_key)


def _benchmark_overlay(
    result: ScenarioResult,
    benchmark_ticker: str | None,
    *,
    config: Config,
    factor_returns=None,
    factor_history=None,
    benchmark_returns=None,
) -> ScenarioResult:
    """Attach benchmark + active-return as a NON-cached overlay (mirrors `_apply_mtm`).

    The benchmark is run as a one-holding portfolio through the result's own
    `factor_shocks` (empty periphery). Benchmark total P&L and naive attribution
    are sufficient for active return, so conditional maps are deliberately skipped.
    This is a display adornment: any failure logs and leaves the benchmark fields
    None rather than failing the run. Pre-fetched returns are reused on a cache miss;
    the cache-hit path fetches its own vintage-correct inputs.
    """
    if not benchmark_ticker:
        return result
    try:
        is_backdated = result.market_date < latest_market_date()
        yf_end = (result.market_date + timedelta(days=1)) if is_backdated else None
        if factor_returns is None:
            if is_backdated:
                factor_returns, factor_history = fetch_factor_returns_with_history(
                    lookback_weeks=config.beta_lookback_weeks, end=yf_end
                )
            else:
                factor_returns, factor_history = get_factor_returns_with_history(
                    lookback_weeks=config.beta_lookback_weeks
                )
        if benchmark_returns is None:
            bench_prices = fetch_weekly_prices(
                [benchmark_ticker], lookback_weeks=config.beta_lookback_weeks, end=yf_end
            )
            benchmark_returns = compute_weekly_returns(bench_prices)
        bench_portfolio = Portfolio(
            name=benchmark_ticker,
            description="Benchmark",
            holdings={benchmark_ticker: 1.0},
        )
        bench_betas, _ = estimate_betas_for_portfolio(
            bench_portfolio,
            lookback_weeks=config.beta_lookback_weeks,
            alpha=config.ridge_alpha,
            factor_returns=factor_returns,
            ticker_returns=benchmark_returns,
        )
        bench_pnl = portfolio_pnl(
            bench_portfolio,
            bench_betas,
            shocks={fs.factor: fs.shock for fs in result.factor_shocks},
            periphery_shocks={},
            factor_returns_history=None,
        )
        return result.model_copy(
            update={
                "benchmark_ticker": benchmark_ticker,
                "benchmark_pnl": PortfolioPnL(**bench_pnl),
                "active_return": result.portfolio_pnl.total_pnl - bench_pnl["total_pnl"],
            }
        )
    except Exception as exc:  # noqa: BLE001 — benchmark is a display adornment, degrade gracefully
        logger.warning("Benchmark overlay unavailable for %s: %s", benchmark_ticker, exc)
        return result


def _quant_direction_map(state_directions) -> dict[str, int]:
    expected = {"volatility", "rates", "dollar", "oil", "credit"}
    names = [item.state for item in state_directions]
    if len(names) != len(expected) or set(names) != expected:
        raise ValueError(
            "Quant V2 analog selection must provide each market-state direction exactly once"
        )
    mapping = {"up": 1, "down": -1, "neutral": 0}
    return {item.state: mapping[item.direction] for item in state_directions}


def _direct_pnl_model(
    total: float, by_factor: dict[str, float], by_ticker: dict[str, float]
) -> PortfolioPnL:
    return PortfolioPnL(
        total_pnl=total,
        by_factor_naive=by_factor,
        by_factor_conditional_shapley=None,
        by_factor_conditional_shapley_explicit=None,
        by_factor_conditional_shapley_grouped=None,
        by_ticker_factor=by_ticker,
        by_ticker_periphery=dict.fromkeys(by_ticker, 0.0),
        by_ticker_total=by_ticker,
    )


def _run_quant_v2_scenario(
    scenario_text: str,
    portfolio: str | Portfolio | None = None,
    *,
    config: Config,
    gemini: GeminiClient | None = None,
    cache: CacheProtocol | None = None,
    market_date: date | None = None,
    skip_cache: bool = False,
    portfolio_key: str | None = None,
    progress: ProgressCallback | None = None,
    position_quantities: dict[str, float] | None = None,
    portfolio_nav: float | None = None,
    reporting_currency: str | None = None,
    pinned_event_ids: list[str] | None = None,
    benchmark: str | None = None,
    horizon: int = 21,
    severity: float = 1.0,
) -> ScenarioResult:
    if pinned_event_ids is not None:
        raise ValueError("Narrative Shapley is unavailable for Quant V2 results")
    portfolio_obj, resolved_key = _resolve_portfolio(portfolio, portfolio_key)
    gemini = gemini or GeminiClient(config)
    if cache is None:
        cache = CloudStorageCache(config.gcs_bucket, prefix="scenario_cache")
    progress = progress or _noop

    live_as_of = latest_market_date()
    requested_as_of = market_date or live_as_of
    effective_as_of = resolve_effective_market_date(requested_as_of, today_fn=lambda: live_as_of)
    is_backdated = effective_as_of < live_as_of
    benchmark_ticker = _resolve_benchmark(portfolio_obj, resolved_key, benchmark)
    key = scenario_cache_key(
        scenario_text=scenario_text,
        portfolio_key=resolved_key,
        portfolio_holdings={} if position_quantities else portfolio_obj.holdings,
        market_date=effective_as_of,
        model_id=config.vertex_model_id,
        prompt_version=PROMPT_VERSION,
        factor_universe_version=factor_universe_version(),
        events_version=events_version(),
        regression_spec=regression_spec(
            lookback_weeks=config.beta_lookback_weeks, alpha=config.ridge_alpha
        ),
        position_quantities=position_quantities,
        engine_mode="quant_v2",
        horizon=horizon,
        severity=severity,
        engine_spec=QUANT_ENGINE_SPEC,
        benchmark_ticker=benchmark_ticker,
    )
    progress("cache_check", "start")
    if not skip_cache:
        cached = cache.get_json(key, ttl_hours=24 * config.llm_cache_ttl_days)
        if cached is not None:
            progress("cache_hit", "done")
            return _apply_mtm(
                ScenarioResult.model_validate(cached),
                position_quantities=position_quantities,
                portfolio_nav=portfolio_nav,
                reporting_currency=reporting_currency,
            )
    progress("cache_check", "done")

    mark_result: MarkResult | None = None
    if position_quantities:
        mark_result = mark_book(
            position_quantities,
            as_of=effective_as_of,
            reporting_currency=reporting_currency or "USD",
        )
        portfolio_obj = Portfolio(
            name=portfolio_obj.name,
            description=portfolio_obj.description,
            holdings=mark_result.weights,
        )

    events = {
        event_id: event
        for event_id, event in load_events().items()
        if event.end_date >= QUANT_MIN_EVENT_END and event.end_date <= effective_as_of
    }
    if len(events) < MIN_ELIGIBLE_ANALOG_EVENTS:
        raise ValueError(
            f"Quant V2 has fewer than {MIN_ELIGIBLE_ANALOG_EVENTS} eligible analogs "
            f"at {effective_as_of.isoformat()}"
        )

    progress("market", "start")
    with ThreadPoolExecutor(max_workers=1) as pool:
        prepared_future = pool.submit(
            prepare_quant_inputs,
            portfolio_obj,
            as_of=effective_as_of,
            benchmark_ticker=benchmark_ticker,
        )
        analog_out = gemini.select_quant_analogs(scenario_text, summarize_events(events))
        prepared = prepared_future.result()
    progress("market", "done")

    progress("analogs", "start")
    selected_events = analog_out.selected_events
    selected_ids = [item.event_id for item in selected_events]
    unique_ids = set(selected_ids)
    unknown_ids = sorted({event_id for event_id in selected_ids if event_id not in events})
    if unknown_ids:
        raise ValueError(f"Quant V2 analog selector returned unavailable events: {unknown_ids}")
    if len(unique_ids) != len(selected_ids):
        raise ValueError("Quant V2 analog selection contains duplicate event ids")
    if not (MIN_SELECTED_ANALOGS <= len(unique_ids) <= MAX_SELECTED_ANALOGS):
        raise ValueError(
            f"Analog selection must contain {MIN_SELECTED_ANALOGS} to "
            f"{MAX_SELECTED_ANALOGS} unique events"
        )
    directions = _quant_direction_map(analog_out.state_directions)
    progress("analogs", "done")

    progress("attribution", "start")
    modeled = run_quant_model(
        factor_returns=prepared.factor_returns,
        state_levels=prepared.state_levels,
        betas=prepared.betas,
        holdings=portfolio_obj.holdings,
        event_end_dates=[events[event_id].end_date for event_id in selected_ids],
        directions=directions,
        horizon=horizon,
        severity=severity,
        as_of=effective_as_of,
    )
    portfolio_pnl_model = _direct_pnl_model(modeled.total_pnl, modeled.by_factor, modeled.by_ticker)
    progress("attribution", "done")

    support_payload = {
        "candidate_count": modeled.support.candidate_count,
        "direction_compatible_count": modeled.support.direction_compatible_count,
        "neighbor_count": modeled.support.neighbor_count,
        "effective_sample_size": modeled.support.effective_sample_size,
        "medoid_date": modeled.support.medoid_date.date(),
        "nearest_distance": modeled.support.nearest_distance,
        "kernel_bandwidth": modeled.support.kernel_bandwidth,
        "query_dates": [timestamp.date() for timestamp in modeled.support.query_dates],
        "data_start": modeled.support.data_start.date(),
        "data_end": modeled.support.data_end.date(),
    }
    selected_analog_events = [
        {
            "id": event.id,
            "name": event.name,
            "start_date": event.start_date.isoformat(),
            "end_date": event.end_date.isoformat(),
            "tags": list(event.tags),
            "description": event.description,
        }
        for event in (events[event_id] for event_id in selected_ids)
    ]
    progress("narrative", "start")
    narrative, citations = gemini.narrate_quant_scenario(
        scenario_text=scenario_text,
        as_of_date=effective_as_of,
        selected_analog_events=selected_analog_events,
        state_directions=[item.model_dump() for item in analog_out.state_directions],
        factor_ranges=modeled.factor_ranges,
        support=support_payload,
        portfolio=portfolio_obj,
        analog_grounded=is_backdated,
    )
    progress("narrative", "done")

    factor_shocks = [
        FactorShock(
            factor=factor,
            shock=shock,
            reasoning=(
                f"Observed weighted medoid of {modeled.support.neighbor_count} joint "
                f"historical neighbors, scaled {severity:g}x."
            ),
        )
        for factor, shock in modeled.factor_shocks.items()
    ]
    benchmark_pnl: PortfolioPnL | None = None
    active_return: float | None = None
    if benchmark_ticker and prepared.benchmark_beta is not None:
        benchmark_betas = pd.DataFrame(
            [prepared.benchmark_beta.to_dict()], index=[benchmark_ticker]
        )
        benchmark_direct = direct_attribution(
            benchmark_betas,
            {benchmark_ticker: 1.0},
            pd.Series(modeled.factor_shocks),
        )
        benchmark_pnl = _direct_pnl_model(
            benchmark_direct.total_pnl,
            benchmark_direct.by_factor,
            benchmark_direct.by_ticker,
        )
        active_return = modeled.total_pnl - benchmark_direct.total_pnl

    result = ScenarioResult(
        scenario_text=scenario_text,
        market_date=effective_as_of,
        portfolio_key=resolved_key,
        portfolio_name=portfolio_obj.name,
        portfolio_holdings=dict(portfolio_obj.holdings),
        analogs_selected=selected_events,
        factor_shocks=factor_shocks,
        periphery_shocks=[],
        narrative=narrative,
        citations=citations,
        factor_envelope=modeled.factor_ranges,
        portfolio_pnl=portfolio_pnl_model,
        requested_as_of_date=requested_as_of,
        narrative_mode="analog_only" if is_backdated else "grounded",
        selected_event_ids=selected_ids,
        position_quantities=dict(position_quantities) if position_quantities else None,
        reporting_currency=(reporting_currency or "USD") if position_quantities else None,
        benchmark_ticker=benchmark_ticker,
        benchmark_pnl=benchmark_pnl,
        active_return=active_return,
        engine_mode="quant_v2",
        engine_version=QUANT_ENGINE_SPEC,
        methodology="joint_historical_neighbors",
        horizon_trading_days=horizon,
        severity_multiplier=severity,
        historical_model_range=HistoricalModelRangeResult(
            p10=modeled.model_range.p10,
            p50=modeled.model_range.p50,
            p90=modeled.model_range.p90,
            draws=modeled.model_range.draws,
            seed=modeled.model_range.seed,
        ),
        quant_support=QuantSupportResult(**support_payload),
        quant_exposures={
            ticker: QuantExposureResult(
                region=estimate.region,
                tier=estimate.tier,
                n_obs=estimate.n_obs,
                data_weight=estimate.data_weight,
                coefficients=estimate.coefficients,
                industry_factor=estimate.industry_factor,
                industry_mapping=estimate.industry_mapping,
            )
            for ticker, estimate in prepared.exposures.items()
        },
        quant_source_versions={
            dataset_id: QuantSourceVersionResult(
                dataset_id=source.dataset_id,
                url=source.url,
                sha256=source.sha256,
                retrieved_at=source.retrieved_at,
            )
            for dataset_id, source in prepared.sources.items()
        },
    )
    cache.put_json(key, result.model_dump(mode="json"))
    return _apply_mtm(
        result,
        position_quantities=position_quantities,
        portfolio_nav=portfolio_nav,
        reporting_currency=reporting_currency,
        precomputed=mark_result,
    )


def run_scenario(
    scenario_text: str,
    portfolio: str | Portfolio | None = None,
    *,
    config: Config | None = None,
    gemini: GeminiClient | None = None,
    cache: CacheProtocol | None = None,
    market_date: date | None = None,
    skip_cache: bool = False,
    portfolio_key: str | None = None,
    progress: ProgressCallback | None = None,
    position_quantities: dict[str, float] | None = None,
    portfolio_nav: float | None = None,
    reporting_currency: str | None = None,
    pinned_event_ids: list[str] | None = None,
    benchmark: str | None = None,
    horizon: int = 21,
    severity: float = 1.0,
) -> ScenarioResult:
    """Dispatch to the configured engine while preserving the legacy default."""
    resolved_config = config or load_config()
    common = {
        "config": resolved_config,
        "gemini": gemini,
        "cache": cache,
        "market_date": market_date,
        "skip_cache": skip_cache,
        "portfolio_key": portfolio_key,
        "progress": progress,
        "position_quantities": position_quantities,
        "portfolio_nav": portfolio_nav,
        "reporting_currency": reporting_currency,
        "pinned_event_ids": pinned_event_ids,
        "benchmark": benchmark,
        "horizon": horizon,
        "severity": severity,
    }
    if resolved_config.engine_mode == "quant_v2":
        return _run_quant_v2_scenario(scenario_text, portfolio, **common)

    legacy = _run_legacy_scenario(scenario_text, portfolio, **common)
    if resolved_config.engine_mode == "shadow" and pinned_event_ids is None:
        try:
            challenger = _run_quant_v2_scenario(
                scenario_text,
                portfolio,
                **{**common, "config": replace(resolved_config, engine_mode="quant_v2")},
            )
            logger.info(
                "Quant V2 shadow comparison legacy_total=%s quant_total=%s delta=%s",
                legacy.portfolio_pnl.total_pnl,
                challenger.portfolio_pnl.total_pnl,
                challenger.portfolio_pnl.total_pnl - legacy.portfolio_pnl.total_pnl,
            )
        except Exception as exc:  # noqa: BLE001 - challenger must never fail the primary run
            logger.warning("Quant V2 shadow run unavailable: %s", exc)
    return legacy


def _run_legacy_scenario(
    scenario_text: str,
    portfolio: str | Portfolio | None = None,
    *,
    config: Config | None = None,
    gemini: GeminiClient | None = None,
    cache: CacheProtocol | None = None,
    market_date: date | None = None,
    skip_cache: bool = False,
    portfolio_key: str | None = None,
    progress: ProgressCallback | None = None,
    position_quantities: dict[str, float] | None = None,
    portfolio_nav: float | None = None,
    reporting_currency: str | None = None,
    pinned_event_ids: list[str] | None = None,
    benchmark: str | None = None,
    horizon: int = 21,
    severity: float = 1.0,
) -> ScenarioResult:
    """End-to-end pipeline.

    The `market_date` argument doubles as the as-of date. When it equals today,
    the pipeline runs the standard live-grounded path (Google Search citations,
    warm-cached factor returns). When it is in the past, the pipeline switches
    to vintage-controlled backdated mode:

      * The historical-events registry is filtered to `event.end_date <=
        effective_as_of` so the analog selector cannot see future-dated events.
      * yfinance fetches pass `end=effective_as_of + 1 day` (the +1 day is
        because yfinance `end=` is exclusive) and the warm cache is bypassed.
      * The narrative call goes through `_analog_grounded_narrative` (no Google
        Search) so the LLM is constrained to analog-event grounding.

    `effective_as_of` is the last NYSE trading day on or before the user's
    requested `market_date`, resolved via `resolve_effective_market_date`.

    Args:
        scenario_text: natural-language scenario description.
        portfolio: a sample-portfolio key (str), a Portfolio object (custom), or None
            (in which case `portfolio_key` MUST be given). Cannot be combined with
            `portfolio_key`.
        portfolio_key: back-compat keyword equivalent to passing `portfolio=<str>`.
            Cannot be combined with `portfolio`.
        gemini, cache: dependency-injected for tests.
        progress: optional callback invoked at stage boundaries. See ProgressCallback.

    Raises:
        ValueError: when backdating yields < MIN_ELIGIBLE_ANALOG_EVENTS analogs.
            (API layer translates to HTTP 422 with the as-of date in the message.)
    """
    portfolio_obj, resolved_key = _resolve_portfolio(portfolio, portfolio_key)

    config = config or load_config()
    gemini = gemini or GeminiClient(config)
    if cache is None:
        cache = CloudStorageCache(config.gcs_bucket, prefix="scenario_cache")

    # The latest NYSE close is the single anchor for "live": the default as-of
    # AND the live-vs-backdated classification both derive from it, computed once
    # so a run crossing 16:00 ET can't classify itself inconsistently.
    live_as_of = latest_market_date()
    requested_as_of = market_date or live_as_of
    effective_as_of = resolve_effective_market_date(requested_as_of, today_fn=lambda: live_as_of)
    is_backdated = effective_as_of < live_as_of
    # Pinned-analog runs (narrative-decomposition subsets) skip analog selection and
    # the live Google-Search grounding so subset payoffs are deterministic. They
    # share the analog-only narrative path with backdated runs.
    use_analog_only = is_backdated or pinned_event_ids is not None
    progress = progress or _noop

    # Benchmark for relative (active) return — explicit request wins, else the
    # sample portfolio's own benchmark. Attached as a non-cached overlay below.
    benchmark_ticker = _resolve_benchmark(portfolio_obj, resolved_key, benchmark)

    # Cache key uses effective_as_of — that's what determines the actual data
    # used. A user picking a weekend resolves to the prior Friday, and both
    # requests should share a cache entry.
    # In quantity (MTM) mode the weights are derived from marks, so the key is
    # folded on the raw quantities and the provisional holdings are dropped from
    # the hash (NAV / FX / marks are never keyed — applied post-retrieval).
    progress("cache_check", "start")
    key = scenario_cache_key(
        scenario_text=scenario_text,
        portfolio_key=resolved_key,
        portfolio_holdings={} if position_quantities else portfolio_obj.holdings,
        market_date=effective_as_of,
        model_id=config.vertex_model_id,
        prompt_version=PROMPT_VERSION,
        factor_universe_version=factor_universe_version(),
        events_version=events_version(),
        regression_spec=regression_spec(
            lookback_weeks=config.beta_lookback_weeks, alpha=config.ridge_alpha
        ),
        position_quantities=position_quantities,
        pinned_event_ids=pinned_event_ids,
        engine_mode=config.engine_mode,
        horizon=21,
        severity=1.0,
        engine_spec=QUANT_ENGINE_SPEC if config.engine_mode == "shadow" else None,
    )

    if not skip_cache:
        cached = cache.get_json(key, ttl_hours=24 * config.llm_cache_ttl_days)
        if cached is not None:
            progress("cache_hit", "done")
            # Cache holds the return-space canonical (+ quantity inputs); the NAV /
            # marks are recomputed here so a cache hit never serves stale dollars.
            cached_result = ScenarioResult.model_validate(cached)
            marked = _apply_mtm(
                cached_result,
                position_quantities=position_quantities or cached_result.position_quantities,
                portfolio_nav=portfolio_nav,
                reporting_currency=reporting_currency or cached_result.reporting_currency,
            )
            # Benchmark attaches on the hit path too (it fetches its own
            # vintage-correct factor + benchmark returns) so a cache hit never
            # silently drops the benchmark.
            return _benchmark_overlay(marked, benchmark_ticker, config=config)
    progress("cache_check", "done")

    # Quantity (MTM) mode: mark the book BEFORE the Gemini chain so the LLM prompt
    # AND the engine both see the price-derived weights. Marking is a short serial
    # prefix here and is fail-closed (a missing/stale price or FX raises MarkingError
    # → the API surfaces 503, never a percentage-only valuation).
    mark_result: MarkResult | None = None
    if position_quantities:
        mark_result = mark_book(
            position_quantities,
            as_of=effective_as_of,
            reporting_currency=reporting_currency or "USD",
        )
        portfolio_obj = Portfolio(
            name=portfolio_obj.name,
            description=portfolio_obj.description,
            holdings=mark_result.weights,
        )

    # Event registry — full for live runs, end-date-filtered for backdated runs.
    full_events = load_events()
    if is_backdated:
        events = filter_events_as_of(full_events, effective_as_of)
        if len(events) < MIN_ELIGIBLE_ANALOG_EVENTS:
            raise ValueError(
                f"Backdating to {effective_as_of.isoformat()} leaves only "
                f"{len(events)} eligible historical analogs "
                f"(minimum {MIN_ELIGIBLE_ANALOG_EVENTS} required). Try a more "
                f"recent as-of date."
            )
        analog_summaries = summarize_events(events)
    else:
        events = full_events
        analog_summaries = event_summaries()

    factor_universe_desc = [
        {
            "name": f.name,
            "ticker": f.ticker,
            "group": f.group,
            "short_label": f.short_label,
            "display_name": f.display_name,
            "description": f.description,
        }
        for f in FACTORS.values()
    ]

    # yfinance end= is exclusive; +1 day yields a bar inclusive of effective_as_of.
    # Live runs pass end=None and let the helper anchor on today.
    yf_end = (effective_as_of + timedelta(days=1)) if is_backdated else None

    # Hoist yfinance to overlap with the Gemini chain. Backdated runs MUST
    # bypass the warm cache (it keys only on lookback_weeks and always returns
    # current data) — call the underlying fetch directly with end=.
    with ThreadPoolExecutor(max_workers=3) as pool:
        progress("market", "start")
        portfolio_future = pool.submit(
            fetch_weekly_prices,
            _market_tickers(portfolio_obj),
            lookback_weeks=config.beta_lookback_weeks,
            end=yf_end,
        )
        # Fetch the benchmark's prices in the same batch (overlaps the Gemini
        # chain) so the post-cache benchmark overlay on the miss path is free.
        benchmark_future = (
            pool.submit(
                fetch_weekly_prices,
                [benchmark_ticker],
                lookback_weeks=config.beta_lookback_weeks,
                end=yf_end,
            )
            if benchmark_ticker
            else None
        )
        if is_backdated:
            factors_future = pool.submit(
                fetch_factor_returns_with_history,
                lookback_weeks=config.beta_lookback_weeks,
                end=yf_end,
            )
        else:
            factors_future = pool.submit(
                get_factor_returns_with_history,
                lookback_weeks=config.beta_lookback_weeks,
            )

        progress("analogs", "start")
        if pinned_event_ids is not None:
            # Fixed-context decomposition: reuse the source scenario's analog set
            # verbatim (no LLM re-selection) so subset payoffs are deterministic.
            selected_ids = list(pinned_event_ids)
            selected_events = [
                AnalogSelection(
                    event_id=eid,
                    why_relevant="Pinned from the source scenario (fixed-context decomposition).",
                )
                for eid in selected_ids
            ]
        else:
            analog_out = gemini.select_analogs(scenario_text, analog_summaries)
            selected_events = analog_out.selected_events
            selected_ids = [a.event_id for a in selected_events]
        # Guard against the selector hallucinating an event id outside the
        # (possibly backdate-filtered) registry — or a pinned id no longer present.
        # compute_envelope would otherwise raise a bare KeyError, which the /run
        # endpoint does not map (it catches ValueError -> 422).
        unknown_ids = sorted({eid for eid in selected_ids if eid not in events})
        if unknown_ids:
            raise ValueError(
                f"Analog selector returned event ids not in the "
                f"{'backdated ' if is_backdated else ''}registry: {unknown_ids}. "
                "Please re-run the scenario."
            )
        # Cardinality enforcement of record — the "2 to 5" in the selection prompt
        # is guidance only, and the pinned path bypasses the LLM entirely.
        # Duplicate ids within bounds are caught by the selected-event helper.
        unique_ids = set(selected_ids)
        if not (MIN_SELECTED_ANALOGS <= len(unique_ids) <= MAX_SELECTED_ANALOGS):
            raise ValueError(
                f"Analog selection must contain {MIN_SELECTED_ANALOGS} to "
                f"{MAX_SELECTED_ANALOGS} unique events; got {len(unique_ids)}. "
                "Please re-run the scenario."
            )
        progress("analogs", "done")

        progress("envelope", "start")
        returns_matrix = get_selected_event_returns_matrix(selected_ids, registry=events)
        envelope = compute_envelope_from_matrix(returns_matrix)
        per_event_returns = _per_event_records(returns_matrix, events)
        progress("envelope", "done")

        progress("narrative", "start")
        if use_analog_only:
            # Backdated OR pinned-decomposition: ground the narrative in the selected
            # analog events only (no Google Search). Build the full event payload.
            selected_analog_events = [
                {
                    "id": e.id,
                    "name": e.name,
                    "start_date": e.start_date.isoformat(),
                    "end_date": e.end_date.isoformat(),
                    "tags": list(e.tags),
                    "description": e.description,
                }
                for e in (events[eid] for eid in selected_ids if eid in events)
            ]
            shock_out, citations = gemini.propose_shocks_with_retry(
                scenario_text=scenario_text,
                portfolio=portfolio_obj,
                factor_universe_descriptions=factor_universe_desc,
                envelope=envelope,
                events_registry=events,
                analog_grounded=True,
                as_of_date=effective_as_of,
                selected_analog_events=selected_analog_events,
                per_event_returns=per_event_returns,
            )
        else:
            shock_out, citations = gemini.propose_shocks_with_retry(
                scenario_text=scenario_text,
                portfolio=portfolio_obj,
                factor_universe_descriptions=factor_universe_desc,
                envelope=envelope,
                events_registry=events,
                per_event_returns=per_event_returns,
            )
        progress("narrative", "done")

        ticker_prices = portfolio_future.result()
        factor_returns, factor_history = factors_future.result()
        progress("market", "done")

    # Non-USD listings (e.g. `.T`) are converted to USD returns BEFORE beta
    # estimation so betas absorb FX exposure and active return vs a USD
    # benchmark is currency-consistent. All-USD books pass through untouched.
    ticker_returns = convert_weekly_returns_to_usd(
        compute_weekly_returns(ticker_prices), end=yf_end
    )

    progress("betas", "start")
    betas, regression_stats = _estimate_betas_cash_aware(
        portfolio_obj,
        config=config,
        factor_returns=factor_returns,
        ticker_returns=ticker_returns,
    )
    analog_replay = _analog_replay_block(portfolio_obj, betas, returns_matrix)
    progress("betas", "done")

    progress("attribution", "start")
    pnl = portfolio_pnl(
        portfolio_obj,
        betas,
        shocks={fs.factor: fs.shock for fs in shock_out.factor_shocks},
        periphery_shocks={
            ps.ticker: ps.shock for ps in shock_out.periphery_shocks if ps.ticker != CASH_TICKER
        },
        factor_returns_history=factor_history,
    )
    progress("attribution", "done")

    factor_envelope = {
        name: {
            "mean": float(row["mean"]) if row["count"] > 0 else 0.0,
            "p10": float(row["p10"]) if row["count"] > 0 else 0.0,
            "p90": float(row["p90"]) if row["count"] > 0 else 0.0,
            "count": int(row["count"]),
        }
        for name, row in envelope.iterrows()
    }

    portfolio_pnl_model = PortfolioPnL(**pnl)
    regression_quality = _regression_quality_block(regression_stats, config)
    pnl_uncertainty = _pnl_uncertainty_block(
        regression_stats,
        portfolio_obj.holdings,
        [int(rec["window_calendar_days"]) for rec in per_event_returns],
    )
    severity_ladder = _severity_ladder_block(
        portfolio_obj,
        betas,
        shock_out.factor_shocks,
        factor_envelope,
        periphery_total=sum(portfolio_pnl_model.by_ticker_periphery.values()),
    )
    risk_diagnostics = generate_risk_diagnostics(
        factor_shocks=shock_out.factor_shocks,
        envelope=envelope,
        factor_returns_history=factor_history,
        portfolio_pnl=portfolio_pnl_model,
        portfolio_holdings=portfolio_obj.holdings,
        periphery_shocks=shock_out.periphery_shocks,
        regression_quality=regression_quality,
        analog_replay=analog_replay,
    )

    result = ScenarioResult(
        scenario_text=scenario_text,
        market_date=effective_as_of,
        portfolio_key=resolved_key,
        portfolio_name=portfolio_obj.name,
        portfolio_holdings=dict(portfolio_obj.holdings),
        analogs_selected=selected_events,
        factor_shocks=shock_out.factor_shocks,
        periphery_shocks=shock_out.periphery_shocks,
        narrative=shock_out.narrative,
        citations=citations,
        factor_envelope=factor_envelope,
        portfolio_pnl=portfolio_pnl_model,
        risk_diagnostics=risk_diagnostics,
        regression_quality=regression_quality,
        analog_event_returns=[AnalogEventReturns.model_validate(rec) for rec in per_event_returns],
        analog_replay=analog_replay,
        pnl_uncertainty=pnl_uncertainty,
        severity_ladder=severity_ladder,
        requested_as_of_date=requested_as_of,
        narrative_mode="analog_only" if use_analog_only else "grounded",
        selected_event_ids=selected_ids,
        engine_mode="legacy",
        engine_version=regression_spec(
            lookback_weeks=config.beta_lookback_weeks, alpha=config.ridge_alpha
        ),
        methodology="llm_shock_envelope",
        # Cache the quantity INPUTS (already in the key, deterministic) so a hit or
        # an adjustment can re-mark; the marked dollar OUTPUTS (nav/values/marks/fx)
        # are deliberately left None here and attached post-retrieval, never cached.
        position_quantities=dict(position_quantities) if position_quantities else None,
        reporting_currency=(reporting_currency or "USD") if position_quantities else None,
    )

    # Persist the return-space canonical only (no NAV / dollars / marks / benchmark).
    cache.put_json(key, result.model_dump(mode="json"))

    marked = _apply_mtm(
        result,
        position_quantities=position_quantities,
        portfolio_nav=portfolio_nav,
        reporting_currency=reporting_currency,
        precomputed=mark_result,
    )
    # Benchmark overlay (never cached) — reuse the factor history already fetched
    # and the benchmark prices fetched in the same market batch.
    benchmark_returns = (
        compute_weekly_returns(benchmark_future.result()) if benchmark_future else None
    )
    return _benchmark_overlay(
        marked,
        benchmark_ticker,
        config=config,
        factor_returns=factor_returns,
        factor_history=factor_history,
        benchmark_returns=benchmark_returns,
    )


def adjust_scenario_shocks(
    cache_key: str,
    *,
    overrides: dict[str, float] | None = None,
    adjustment_text: str | None = None,
    config: Config | None = None,
    gemini: GeminiClient | None = None,
    cache: CacheProtocol | None = None,
    benchmark: str | None = None,
) -> ScenarioResult:
    """Apply a structured edit to a cached canonical scenario.

    Exactly one of `overrides` (manual slider mode: full factor->value map) or
    `adjustment_text` (prompt mode) must be set.

    Manual mode skips Gemini entirely and recomputes P&L from the overrides.
    Prompt mode runs ONE patch-only Gemini call (no Google Search) that returns
    a `ShockEditPatch`; if scope is "rerun_required" we raise RuntimeError so
    the API layer can surface the rejection_reason to the user.

    The derived result is NOT cached. It preserves narrative, citations,
    analogs_selected, periphery_shocks, factor_envelope, and the rest of the
    canonical result byte-for-byte via model_copy; only factor_shocks,
    portfolio_pnl, and adjustment_history are updated.

    Raises:
        ValueError:    invalid args (both/neither, validation failures).
        LookupError:   cache_key not found or expired.
        RuntimeError:  prompt scope classified as "rerun_required".
    """
    if (overrides is None) == (adjustment_text is None):
        raise ValueError("Exactly one of `overrides` or `adjustment_text` must be set.")

    config = config or load_config()
    if cache is None:
        cache = CloudStorageCache(config.gcs_bucket, prefix="scenario_cache")

    cached = cache.get_json(cache_key, ttl_hours=24 * config.llm_cache_ttl_days)
    if cached is None:
        raise LookupError(f"Scenario result not found for cache_key={cache_key!r}.")
    canonical = ScenarioResult.model_validate(cached)
    if canonical.engine_mode == "quant_v2":
        raise RuntimeError(
            "Quant V2 derives one joint historical vector; edit the scenario and rerun "
            "instead of adjusting individual factor shocks."
        )

    # Reconstruct the portfolio from the CANONICAL holdings for ALL portfolios
    # (not just custom). The holdings dict is part of the cache-key hash, so it is
    # the trusted as-run book. Rebuilding sample portfolios via get_portfolio would
    # silently recompute against the *current* sample weights, so after a weight
    # refresh an adjustment of an old cached scenario would drift off its canonical.
    portfolio_obj = Portfolio(
        name=canonical.portfolio_name,
        description="Canonical portfolio (reconstructed for adjustment)",
        holdings=dict(canonical.portfolio_holdings),
        benchmark=canonical.benchmark_ticker or sample_benchmark(canonical.portfolio_key),
    )
    # Benchmark for the adjusted result's overlay: explicit (client-resent) wins,
    # else the canonical's own (overlay-only ⇒ not recoverable from cache for
    # custom books, so the client resends it).
    benchmark_ticker = _resolve_benchmark(portfolio_obj, canonical.portfolio_key, benchmark)

    canonical_shocks = {fs.factor: fs.shock for fs in canonical.factor_shocks}

    kind: str
    prompt_text: str | None
    new_reasonings: dict[str, str]

    if overrides is not None:
        kind = "manual"
        prompt_text = None
        errors = validate_factor_overrides(canonical, overrides)
        if errors:
            raise ValueError("Override validation failed: " + " | ".join(errors))
        new_shocks = dict(overrides)
        new_reasonings = {
            f: f"Manual override: {f} set to {v:.4f}."
            for f, v in overrides.items()
            if v != canonical_shocks.get(f)
        }
    else:
        kind = "prompt"
        prompt_text = adjustment_text
        gemini = gemini or GeminiClient(config)
        envelope_df = _envelope_df_from_canonical(canonical)
        factor_universe_desc = [
            {
                "name": f.name,
                "ticker": f.ticker,
                "group": f.group,
                "short_label": f.short_label,
                "display_name": f.display_name,
                "description": f.description,
            }
            for f in FACTORS.values()
        ]
        patch = gemini.propose_shock_edit(
            prior_factor_shocks=[
                {"factor": fs.factor, "shock": fs.shock, "reasoning": fs.reasoning}
                for fs in canonical.factor_shocks
            ],
            adjustment_text=adjustment_text or "",
            envelope=envelope_df,
            factor_universe_descriptions=factor_universe_desc,
        )
        if patch.scope == "rerun_required":
            raise RuntimeError(
                patch.rejection_reason
                or "This adjustment changes the scenario; please rerun with new text."
            )

        # Build overrides by starting from canonical and applying patch edits.
        new_shocks = dict(canonical_shocks)
        new_reasonings = {}
        for edit in patch.edits:
            new_shocks[edit.factor] = edit.new_shock
            new_reasonings[edit.factor] = edit.reasoning

        # Belt-and-braces: the prompt forbids new factors, but the validator
        # double-checks. This catches mis-classified patches before they hit pnl.
        errors = validate_factor_overrides(canonical, new_shocks)
        if errors:
            raise ValueError("Patch validation failed: " + " | ".join(errors))

    # Recompute P&L with the new shocks. Periphery shocks come from canonical untouched.
    periphery_shocks = {ps.ticker: ps.shock for ps in canonical.periphery_shocks}

    # CRITICAL: vintage-control the market fetches. If the canonical scenario was
    # run as-of a past date, the adjustment must refetch using that same as-of —
    # otherwise the new P&L would mix backdated shocks with current betas/factor
    # history, which is a look-ahead leak. Backdated path also bypasses the warm
    # cache (which always returns current data).
    canonical_is_backdated = canonical.market_date < latest_market_date()
    yf_end = (canonical.market_date + timedelta(days=1)) if canonical_is_backdated else None

    with ThreadPoolExecutor(max_workers=2) as pool:
        portfolio_future = pool.submit(
            fetch_weekly_prices,
            _market_tickers(portfolio_obj),
            lookback_weeks=config.beta_lookback_weeks,
            end=yf_end,
        )
        if canonical_is_backdated:
            factors_future = pool.submit(
                fetch_factor_returns_with_history,
                lookback_weeks=config.beta_lookback_weeks,
                end=yf_end,
            )
        else:
            factors_future = pool.submit(
                get_factor_returns_with_history,
                lookback_weeks=config.beta_lookback_weeks,
            )
        ticker_prices = portfolio_future.result()
        factor_returns, factor_history = factors_future.result()
    # Same USD conversion as run_scenario, vintage-correct to the canonical as-of.
    ticker_returns = convert_weekly_returns_to_usd(
        compute_weekly_returns(ticker_prices), end=yf_end
    )

    betas, regression_stats = _estimate_betas_cash_aware(
        portfolio_obj,
        config=config,
        factor_returns=factor_returns,
        ticker_returns=ticker_returns,
    )

    pnl = portfolio_pnl(
        portfolio_obj,
        betas,
        shocks=new_shocks,
        periphery_shocks={t: s for t, s in periphery_shocks.items() if t != CASH_TICKER},
        factor_returns_history=factor_history,
    )

    # Build the new factor_shocks list, preserving reasoning for unchanged factors.
    new_factor_shocks: list[FactorShock] = []
    for fs in canonical.factor_shocks:
        new_value = new_shocks.get(fs.factor, fs.shock)
        new_factor_shocks.append(
            FactorShock(
                factor=fs.factor,
                shock=new_value,
                reasoning=new_reasonings.get(fs.factor, fs.reasoning),
            )
        )

    changed = {
        fs.factor: [canonical_shocks[fs.factor], new_shocks[fs.factor]]
        for fs in canonical.factor_shocks
        if new_shocks.get(fs.factor) != canonical_shocks[fs.factor]
    }

    new_entry = ShockAdjustment(
        kind=kind,
        prompt_text=prompt_text,
        timestamp=datetime.now(UTC),
        changed_factors=changed,
    )

    portfolio_pnl_model = PortfolioPnL(**pnl)
    regression_quality = _regression_quality_block(regression_stats, config)
    pnl_uncertainty = _pnl_uncertainty_block(
        regression_stats,
        canonical.portfolio_holdings,
        [rec.window_calendar_days for rec in (canonical.analog_event_returns or [])],
    )
    severity_ladder = _severity_ladder_block(
        portfolio_obj,
        betas,
        new_factor_shocks,
        canonical.factor_envelope,
        periphery_total=sum(portfolio_pnl_model.by_ticker_periphery.values()),
    )
    risk_diagnostics = generate_risk_diagnostics(
        factor_shocks=new_factor_shocks,
        envelope=_envelope_df_from_canonical(canonical),
        factor_returns_history=factor_history,
        portfolio_pnl=portfolio_pnl_model,
        portfolio_holdings=canonical.portfolio_holdings,
        periphery_shocks=canonical.periphery_shocks,
        regression_quality=regression_quality,
        analog_replay=canonical.analog_replay,
    )

    adjusted = canonical.model_copy(
        update={
            "factor_shocks": new_factor_shocks,
            "portfolio_pnl": portfolio_pnl_model,
            "risk_diagnostics": risk_diagnostics,
            # Freshly recomputed alongside the betas (free — rides the same tuple).
            "regression_quality": regression_quality,
            # Shock-independent; recomputed from the same vintage stats + the
            # canonical's analog windows, so it lands byte-identical.
            "pnl_uncertainty": pnl_uncertainty,
            # Shock-DEPENDENT (unlike the preserved analog_replay): the base and
            # the held low-evidence values move with the new shocks.
            "severity_ladder": severity_ladder,
            "adjustment_history": [*canonical.adjustment_history, new_entry],
        }
    )

    # Re-attach mark-to-market: in quantity mode the canonical carries the cached
    # quantity inputs, so re-mark at the canonical's (vintage-controlled) as-of date
    # to refresh NAV + marks on the adjusted result. Dollars stay client-side
    # (return_field × NAV); only the shocks/P&L changed.
    marked = _apply_mtm(
        adjusted,
        position_quantities=adjusted.position_quantities,
        reporting_currency=adjusted.reporting_currency,
    )
    # Re-attach the benchmark overlay so the adjusted result carries an updated
    # active return (it fetches its own vintage-correct factor + benchmark returns).
    return _benchmark_overlay(marked, benchmark_ticker, config=config)


def _envelope_df_from_canonical(canonical: ScenarioResult):
    """Reconstruct the envelope DataFrame from canonical.factor_envelope dict.

    Used by `propose_shock_edit` which expects the same DataFrame shape that
    `compute_envelope` returns.
    """
    if not canonical.factor_envelope:
        return pd.DataFrame(columns=["mean", "p10", "p90", "count"])
    return pd.DataFrame.from_dict(canonical.factor_envelope, orient="index")
