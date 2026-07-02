"""LLM-free engine-replay validation harness.

For each (historical event × sample book) pair: estimate vintage betas as of the
event's start (data ends the trading day before — yfinance `end=` is exclusive),
push the event's REALIZED factor returns through those betas via
`analog_replay_pnl`, and compare against the book's realized buy-and-hold USD
return over the same window. The gap between the two is the engine's stress
tracking error — with no LLM anywhere, it cleanly separates *engine error* from
the scenario pipeline's *shock-severity error*.

Deliberately imports only `app.data.*` / `app.factors.*` / `app.config`: adding
an `app.llm` import here would break the harness's no-LLM guarantee.

Honest-read caveats (also rendered into the markdown artifact): the books are
TODAY'S frozen cap-weight snapshots replayed onto historical windows
(point-in-time drift + survivorship), the modeled side is factor-only (no
idiosyncratic or periphery effects), and both sides use dividend/split-adjusted
closes.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from app.config import Config, load_config
from app.data.fx import convert_weekly_returns_to_usd
from app.data.market import compute_weekly_returns, fetch_daily_prices, fetch_weekly_prices
from app.data.marking import currency_for_ticker, fx_pair_for_currency, major_currency
from app.data.sample_portfolios import (
    CASH_TICKER,
    SAMPLE_PORTFOLIOS,
    Portfolio,
    get_portfolio,
    sample_as_of,
)
from app.factors.analogs import (
    HistoricalEvent,
    events_version,
    fetch_event_returns_matrix,
    load_events,
)
from app.factors.regression import (
    MIN_REGRESSION_WEEKS,
    estimate_betas_for_portfolio,
    fetch_factor_returns,
    regression_spec,
)
from app.factors.shocks import analog_replay_pnl
from app.factors.universe import FACTORS, factor_universe_version

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReplayPairResult:
    """Modeled-vs-realized outcome for one (event, book) pair.

    `modeled_pnl`/`realized_pnl`/`error` are None exactly when `skipped_reason`
    is set (e.g. a book ticker that IPO'd after the event's vintage window).
    `error = modeled − realized`; negative bias means the engine understates.
    """

    event_id: str
    portfolio_key: str
    modeled_pnl: float | None
    realized_pnl: float | None
    error: float | None
    n_factors_used: int
    n_factors_covered: int
    factors_dropped: list[str]
    min_ticker_n_obs: int | None
    skipped_reason: str | None


@dataclass(frozen=True)
class ReplaySummary:
    """Aggregate stats over the computed pairs plus full provenance.

    `regression_spec` / `events_version` / `factor_universe_version` /
    `weights_as_of` make the artifact self-describing: any engine-math, registry,
    universe, or weight-snapshot change shows up as a provenance diff, which is
    the re-run trigger.
    """

    n_pairs: int
    n_computed: int
    n_skipped: int
    mae: float | None
    bias: float | None
    sign_hit_rate: float | None
    pearson_r: float | None
    regression_spec: str
    events_version: str
    factor_universe_version: str
    weights_as_of: str
    generated_at: str


def select_vintage_factors(
    factor_returns: pd.DataFrame,
    *,
    min_obs: int = MIN_REGRESSION_WEEKS,
) -> tuple[pd.DataFrame, list[str]]:
    """Drop factor columns too thin to estimate at this vintage.

    A pre-launch ETF is an all-NaN column; a just-launched one has a handful of
    rows. Keeping them would make the estimator's global any-NaN row drop erase
    the entire window. Dropping them estimates the model a practitioner could
    actually have estimated at that vintage; zero-filling is prohibited for the
    same reason as the SHAP background (it manufactures false correlation).
    Returns `(kept_columns_frame, sorted_dropped_names)`.
    """
    counts = factor_returns.notna().sum(axis=0)
    kept = [str(c) for c in factor_returns.columns if int(counts[c]) >= min_obs]
    dropped = sorted(str(c) for c in factor_returns.columns if int(counts[c]) < min_obs)
    return factor_returns[kept], dropped


def buy_and_hold_return_usd(
    prices: pd.DataFrame,
    holdings: Mapping[str, float],
    fx_total_by_ticker: Mapping[str, float],
) -> float:
    """Weighted buy-and-hold USD return over a price window.

    Per ticker: first-valid to last-valid close return, compounded with that
    ticker's FX total return over the same window (`(1+r)(1+fx)−1`; 0.0 for USD
    listings). Raises RuntimeError naming any holding without at least two valid
    closes — the caller records the pair as skipped rather than renormalizing
    around the hole.
    """
    total = 0.0
    for ticker, weight in holdings.items():
        if ticker == CASH_TICKER:
            continue
        if ticker not in prices.columns:
            raise RuntimeError(f"No realized prices for {ticker} in the event window")
        series = prices[ticker].dropna()
        if len(series) < 2:
            raise RuntimeError(f"Fewer than two valid closes for {ticker} in the event window")
        local = float(series.iloc[-1] / series.iloc[0]) - 1.0
        fx = float(fx_total_by_ticker.get(ticker, 0.0))
        total += weight * ((1.0 + local) * (1.0 + fx) - 1.0)
    return total


def _fx_window_totals(tickers: Sequence[str], event: HistoricalEvent) -> dict[str, float]:
    """Per-ticker FX total return over the event window (0.0 for USD listings).

    Uses the same pair/inversion maps as marking + fx conversion so realized
    returns compare like-for-like with the USD-converted beta inputs. Raises
    RuntimeError when a needed FX series is unavailable (pair skips, reported).
    """
    majors_by_ticker = {t: major_currency(currency_for_ticker(t)) for t in tickers}
    needed = sorted({m for m in majors_by_ticker.values() if m != "USD"})
    totals_by_major: dict[str, float] = {}
    for major in needed:
        symbol, invert = fx_pair_for_currency(major)
        prices = fetch_daily_prices(
            [symbol], start=event.start_date, end=event.end_date + timedelta(days=1)
        )
        series = prices[symbol].dropna() if symbol in prices.columns else pd.Series(dtype=float)
        if len(series) < 2:
            raise RuntimeError(f"FX series unavailable for {major} ({symbol}) in event window")
        rate = 1.0 / series if invert else series
        totals_by_major[major] = float(rate.iloc[-1] / rate.iloc[0]) - 1.0
    return {
        t: totals_by_major.get(m, 0.0) if m != "USD" else 0.0 for t, m in majors_by_ticker.items()
    }


def _replay_pair(
    event: HistoricalEvent,
    portfolio: Portfolio,
    portfolio_key: str,
    vintage_factor_returns: pd.DataFrame,
    event_returns: Mapping[str, float | None],
    config: Config,
) -> ReplayPairResult:
    """One (event, book) modeled-vs-realized comparison; skips are reported, never raised."""

    def _skip(reason: str, dropped: list[str] | None = None, used: int = 0) -> ReplayPairResult:
        return ReplayPairResult(
            event_id=event.id,
            portfolio_key=portfolio_key,
            modeled_pnl=None,
            realized_pnl=None,
            error=None,
            n_factors_used=used,
            n_factors_covered=0,
            factors_dropped=dropped or [],
            min_ticker_n_obs=None,
            skipped_reason=reason,
        )

    if CASH_TICKER in portfolio.holdings:
        return _skip("cash sleeve not supported by the replay harness")

    vintage_end = event.start_date  # yfinance-exclusive → data through the prior trading day
    vintage_factors, _ = select_vintage_factors(vintage_factor_returns)
    # Diff against the FULL universe, not just the fetched frame: an ETF that
    # didn't exist at the vintage never comes back as a column at all, and the
    # dropped list must disclose those too.
    dropped = sorted(set(FACTORS) - {str(c) for c in vintage_factors.columns})
    if vintage_factors.shape[1] == 0:
        return _skip("no factor ETF has enough history at this vintage", dropped)

    try:
        ticker_prices = fetch_weekly_prices(
            portfolio.tickers,
            end=vintage_end,
            lookback_weeks=config.beta_lookback_weeks,
        )
        ticker_returns = convert_weekly_returns_to_usd(
            compute_weekly_returns(ticker_prices), end=vintage_end
        )
        betas, stats = estimate_betas_for_portfolio(
            portfolio,
            lookback_weeks=config.beta_lookback_weeks,
            alpha=config.ridge_alpha,
            factor_returns=vintage_factors,
            ticker_returns=ticker_returns,
        )

        modeled, covered = analog_replay_pnl(portfolio, betas, event_returns)

        realized_prices = fetch_daily_prices(
            portfolio.tickers,
            start=event.start_date,
            end=event.end_date + timedelta(days=1),
        )
        fx_totals = _fx_window_totals(portfolio.tickers, event)
        realized = buy_and_hold_return_usd(realized_prices, portfolio.holdings, fx_totals)
    except RuntimeError as exc:  # incl. InsufficientHistoryError / MarkingError subclasses
        return _skip(f"{type(exc).__name__}: {exc}", dropped, used=vintage_factors.shape[1])

    return ReplayPairResult(
        event_id=event.id,
        portfolio_key=portfolio_key,
        modeled_pnl=modeled,
        realized_pnl=realized,
        error=modeled - realized,
        n_factors_used=vintage_factors.shape[1],
        n_factors_covered=covered,
        factors_dropped=dropped,
        min_ticker_n_obs=min(s.n_obs for s in stats.values()) if stats else None,
        skipped_reason=None,
    )


def summarize_pairs(
    pairs: Sequence[ReplayPairResult],
    *,
    regression_spec: str,
    events_version: str,
    factor_universe_version: str,
    weights_as_of: str,
    generated_at: str,
) -> ReplaySummary:
    """Aggregate MAE / bias / sign-hit-rate / Pearson r over the computed pairs.

    `pearson_r` is None below 3 computed pairs (or on zero variance) — a
    2-point correlation is always ±1 and would read as fake precision.
    """
    computed = [p for p in pairs if p.skipped_reason is None]
    errors = [p.error for p in computed if p.error is not None]
    mae = float(np.mean([abs(e) for e in errors])) if errors else None
    bias = float(np.mean(errors)) if errors else None
    sign_hit_rate = (
        float(
            np.mean(
                [
                    (p.modeled_pnl >= 0) == (p.realized_pnl >= 0)
                    for p in computed
                    if p.modeled_pnl is not None and p.realized_pnl is not None
                ]
            )
        )
        if computed
        else None
    )
    pearson: float | None = None
    if len(computed) >= 3:
        modeled = np.array([p.modeled_pnl for p in computed], dtype=float)
        realized = np.array([p.realized_pnl for p in computed], dtype=float)
        if float(modeled.std()) > 0.0 and float(realized.std()) > 0.0:
            pearson = float(np.corrcoef(modeled, realized)[0, 1])
    return ReplaySummary(
        n_pairs=len(pairs),
        n_computed=len(computed),
        n_skipped=len(pairs) - len(computed),
        mae=mae,
        bias=bias,
        sign_hit_rate=sign_hit_rate,
        pearson_r=pearson,
        regression_spec=regression_spec,
        events_version=events_version,
        factor_universe_version=factor_universe_version,
        weights_as_of=weights_as_of,
        generated_at=generated_at,
    )


def run_engine_replay(
    *,
    event_ids: Sequence[str] | None = None,
    portfolio_keys: Sequence[str] | None = None,
    config: Config | None = None,
    max_workers: int = 4,
) -> tuple[list[ReplayPairResult], ReplaySummary]:
    """Replay every requested (event × book) pair; never aborts on a single pair.

    Defaults to the full registry × all sample books. All fetches ride the
    process-wide market cache, so warm re-runs are cheap. Pair order is
    events-outer (registry order), books-inner.
    """
    config = config or load_config()
    events = load_events()

    ids = list(event_ids) if event_ids is not None else list(events)
    unknown = sorted(set(ids) - set(events))
    if unknown:
        raise ValueError(f"Unknown event ids: {unknown}")
    keys = list(portfolio_keys) if portfolio_keys is not None else list(SAMPLE_PORTFOLIOS)
    books = {key: get_portfolio(key) for key in keys}

    returns_matrix = fetch_event_returns_matrix(ids, registry=events)

    workers = max(1, max_workers)
    with ThreadPoolExecutor(max_workers=min(workers, len(ids))) as pool:
        vintage_factor_frames = dict(
            zip(
                ids,
                pool.map(
                    lambda eid: fetch_factor_returns(
                        end=events[eid].start_date,
                        lookback_weeks=config.beta_lookback_weeks,
                    ),
                    ids,
                ),
                strict=True,
            )
        )

    tasks = [(eid, key) for eid in ids for key in keys]

    def _run(task: tuple[str, str]) -> ReplayPairResult:
        eid, key = task
        return _replay_pair(
            events[eid],
            books[key],
            key,
            vintage_factor_frames[eid],
            returns_matrix.loc[eid].to_dict(),
            config,
        )

    with ThreadPoolExecutor(max_workers=min(workers, len(tasks))) as pool:
        pairs = list(pool.map(_run, tasks))

    summary = summarize_pairs(
        pairs,
        regression_spec=regression_spec(
            lookback_weeks=config.beta_lookback_weeks, alpha=config.ridge_alpha
        ),
        events_version=events_version(),
        factor_universe_version=factor_universe_version(),
        weights_as_of=sample_as_of(),
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    return pairs, summary


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:+.2f}%"


def render_markdown(pairs: Sequence[ReplayPairResult], summary: ReplaySummary) -> str:
    """Fully regenerated markdown artifact (no hand-editing; rerun the script)."""
    lines = [
        "# Engine replay validation",
        "",
        "> **This is not a backtest and not a capability claim.** It measures one",
        "> thing: given an event's REALIZED factor moves, how closely does the",
        "> linear factor engine (vintage betas, no LLM anywhere) reproduce each",
        "> sample book's realized buy-and-hold USD return over the same window?",
        "> The residual is idiosyncratic/periphery return the factor model does",
        "> not claim to capture, plus beta drift. Known caveats: the books are",
        "> TODAY'S frozen cap-weight snapshots replayed onto historical windows",
        f"> (weights as of {summary.weights_as_of} — point-in-time drift and",
        "> survivorship bias), and both sides use dividend/split-adjusted closes.",
        ">",
        f"> Regenerate with `uv run python scripts/run_engine_replay.py`. Generated {summary.generated_at}.",
        "",
        "## Summary",
        "",
        "| metric | value |",
        "|---|---|",
        f"| pairs (computed / skipped) | {summary.n_pairs} ({summary.n_computed} / {summary.n_skipped}) |",
        f"| MAE (modeled vs realized) | {_pct(summary.mae)} |",
        f"| bias (modeled − realized) | {_pct(summary.bias)} |",
        f"| sign hit-rate | {'—' if summary.sign_hit_rate is None else f'{summary.sign_hit_rate:.0%}'} |",
        f"| Pearson r | {'—' if summary.pearson_r is None else f'{summary.pearson_r:.2f}'} |",
        f"| regression spec | `{summary.regression_spec}` |",
        f"| events version | `{summary.events_version}` |",
        f"| factor universe version | `{summary.factor_universe_version}` |",
        "",
        "## Per-pair results",
        "",
        "Positive error = engine overstated the loss/gain; negative = understated.",
        "`factors` is used (estimable at the vintage) / covered (non-NaN event returns).",
        "",
        "| event | book | modeled | realized | error | factors | note |",
        "|---|---|---|---|---|---|---|",
    ]
    for p in pairs:
        note = (
            p.skipped_reason
            if p.skipped_reason
            else (f"dropped: {', '.join(p.factors_dropped)}" if p.factors_dropped else "")
        )
        lines.append(
            f"| {p.event_id} | {p.portfolio_key} | {_pct(p.modeled_pnl)} | "
            f"{_pct(p.realized_pnl)} | {_pct(p.error)} | "
            f"{p.n_factors_used}/{p.n_factors_covered} | {note} |"
        )
    lines.append("")
    return "\n".join(lines)
