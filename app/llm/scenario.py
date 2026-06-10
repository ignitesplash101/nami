"""End-to-end scenario orchestrator: cache -> analog select -> envelope -> shock propose -> betas -> P&L -> cache write.

Also exposes `adjust_scenario_shocks` for the iterative shock-editing path: given a
canonical scenario's cache key plus either manual slider overrides or a natural-language
adjustment prompt, return a derived ScenarioResult with the same narrative / citations /
analogs / periphery but recomputed factor shocks and P&L.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta

import pandas as pd

from app.config import Config, load_config
from app.data.cache import CacheProtocol, CloudStorageCache
from app.data.fx import convert_weekly_returns_to_usd
from app.data.market import compute_weekly_returns, fetch_weekly_prices
from app.data.marking import MarkResult, mark_book
from app.data.sample_portfolios import CASH_TICKER, Portfolio, get_portfolio, sample_benchmark
from app.factors.analogs import (
    HistoricalEvent,
    compute_envelope_from_matrix,
    event_summaries,
    events_version,
    fetch_event_returns_matrix,
    filter_events_as_of,
    load_events,
    summarize_events,
)
from app.factors.regression import (
    MIN_REGRESSION_WEEKS,
    REGRESSION_ESTIMATOR_ID,
    TickerRegressionStats,
    estimate_betas_for_portfolio,
    fetch_factor_returns_with_history,
    regression_spec,
)
from app.factors.shocks import portfolio_pnl
from app.factors.universe import FACTORS, factor_universe_version
from app.factors.warm_cache import get_factor_returns_with_history
from app.llm.adjust_validation import validate_factor_overrides
from app.llm.gemini_client import GeminiClient
from app.llm.prompts import PROMPT_VERSION
from app.llm.risk_diagnostics import generate_risk_diagnostics
from app.llm.schemas import (
    AnalogEventReturns,
    AnalogSelection,
    FactorShock,
    PortfolioPnL,
    RegressionQuality,
    ScenarioResult,
    ShockAdjustment,
    TickerRegressionQuality,
)
from app.utils.calendar import latest_market_date, resolve_effective_market_date
from app.utils.hashing import scenario_cache_key

logger = logging.getLogger(__name__)

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
                r2=s.r2, n_obs=s.n_obs, idio_vol_weekly=s.idio_vol_weekly
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

    The benchmark is run as a one-holding portfolio through the SAME factor history
    and the result's own `factor_shocks` (empty periphery). This is a display
    adornment, so it is best-effort: any failure logs and leaves the benchmark
    fields None rather than failing the run. Pre-fetched returns/history are reused
    on the cache-miss path; the cache-hit path fetches its own (vintage-correct).
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
            factor_returns_history=factor_history,
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
        # Duplicate ids within bounds are caught by fetch_event_returns_matrix.
        unique_ids = set(selected_ids)
        if not (MIN_SELECTED_ANALOGS <= len(unique_ids) <= MAX_SELECTED_ANALOGS):
            raise ValueError(
                f"Analog selection must contain {MIN_SELECTED_ANALOGS} to "
                f"{MAX_SELECTED_ANALOGS} unique events; got {len(unique_ids)}. "
                "Please re-run the scenario."
            )
        progress("analogs", "done")

        progress("envelope", "start")
        returns_matrix = fetch_event_returns_matrix(selected_ids, registry=events)
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
    risk_diagnostics = generate_risk_diagnostics(
        factor_shocks=shock_out.factor_shocks,
        envelope=envelope,
        factor_returns_history=factor_history,
        portfolio_pnl=portfolio_pnl_model,
        portfolio_holdings=portfolio_obj.holdings,
        periphery_shocks=shock_out.periphery_shocks,
        regression_quality=regression_quality,
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
        requested_as_of_date=requested_as_of,
        narrative_mode="analog_only" if use_analog_only else "grounded",
        selected_event_ids=selected_ids,
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
    risk_diagnostics = generate_risk_diagnostics(
        factor_shocks=new_factor_shocks,
        envelope=_envelope_df_from_canonical(canonical),
        factor_returns_history=factor_history,
        portfolio_pnl=portfolio_pnl_model,
        portfolio_holdings=canonical.portfolio_holdings,
        periphery_shocks=canonical.periphery_shocks,
        regression_quality=regression_quality,
    )

    adjusted = canonical.model_copy(
        update={
            "factor_shocks": new_factor_shocks,
            "portfolio_pnl": portfolio_pnl_model,
            "risk_diagnostics": risk_diagnostics,
            # Freshly recomputed alongside the betas (free — rides the same tuple).
            "regression_quality": regression_quality,
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
