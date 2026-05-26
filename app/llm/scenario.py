"""End-to-end scenario orchestrator: cache -> analog select -> envelope -> shock propose -> betas -> P&L -> cache write.

Also exposes `adjust_scenario_shocks` for the iterative shock-editing path: given a
canonical scenario's cache key plus either manual slider overrides or a natural-language
adjustment prompt, return a derived ScenarioResult with the same narrative / citations /
analogs / periphery but recomputed factor shocks and P&L.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime

from app.config import Config, load_config
from app.data.cache import CacheProtocol, CloudStorageCache
from app.data.market import compute_weekly_returns, fetch_weekly_prices
from app.data.sample_portfolios import Portfolio, get_portfolio
from app.factors.analogs import (
    compute_envelope,
    event_summaries,
    events_version,
    load_events,
)
from app.factors.regression import estimate_betas_for_portfolio
from app.factors.shocks import portfolio_pnl
from app.factors.universe import FACTORS, factor_universe_version
from app.factors.warm_cache import get_factor_returns_with_history
from app.llm.adjust_validation import validate_factor_overrides
from app.llm.gemini_client import GeminiClient
from app.llm.prompts import PROMPT_VERSION
from app.llm.schemas import (
    FactorShock,
    PortfolioPnL,
    ScenarioResult,
    ShockAdjustment,
)
from app.utils.hashing import scenario_cache_key

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
) -> str:
    """Compute the cache key the same way `run_scenario` does.

    Used by API handlers to surface the key to the client so subsequent
    adjustment requests can reference the canonical cached result.
    """
    config = config or load_config()
    market_date = market_date or date.today()
    portfolio_obj, resolved_key = _resolve_portfolio(portfolio, None)
    return scenario_cache_key(
        scenario_text=scenario_text,
        portfolio_key=resolved_key,
        portfolio_holdings=portfolio_obj.holdings,
        market_date=market_date,
        model_id=config.vertex_model_id,
        prompt_version=PROMPT_VERSION,
        factor_universe_version=factor_universe_version(),
        events_version=events_version(),
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
) -> ScenarioResult:
    """End-to-end pipeline.

    Args:
        scenario_text: natural-language scenario description.
        portfolio: a sample-portfolio key (str), a Portfolio object (custom), or None
            (in which case `portfolio_key` MUST be given). Cannot be combined with
            `portfolio_key`.
        portfolio_key: back-compat keyword equivalent to passing `portfolio=<str>`.
            Cannot be combined with `portfolio`.
        gemini, cache: dependency-injected for tests.
        progress: optional callback invoked at stage boundaries. See ProgressCallback.

    Custom portfolios are stored with `portfolio_key="custom"`; the cache key still
    differentiates them via `portfolio_holdings` (which is part of the SHA256 input).

    Performance: yfinance fetches start at the top of the function in a background
    ThreadPoolExecutor (max_workers=2) and overlap with the entire Gemini chain
    (Call 1 + envelope + Call 2a + Call 2b). yfinance is effectively free on the
    critical path since Gemini ~8-16s >> yfinance ~2-6s.
    """
    portfolio_obj, resolved_key = _resolve_portfolio(portfolio, portfolio_key)

    config = config or load_config()
    gemini = gemini or GeminiClient(config)
    if cache is None:
        cache = CloudStorageCache(config.gcs_bucket, prefix="scenario_cache")
    market_date = market_date or date.today()
    progress = progress or _noop

    progress("cache_check", "start")
    key = scenario_cache_key(
        scenario_text=scenario_text,
        portfolio_key=resolved_key,
        portfolio_holdings=portfolio_obj.holdings,
        market_date=market_date,
        model_id=config.vertex_model_id,
        prompt_version=PROMPT_VERSION,
        factor_universe_version=factor_universe_version(),
        events_version=events_version(),
    )

    if not skip_cache:
        cached = cache.get_json(key, ttl_hours=24 * config.llm_cache_ttl_days)
        if cached is not None:
            progress("cache_hit", "done")
            return ScenarioResult.model_validate(cached)
    progress("cache_check", "done")

    events = load_events()
    factor_universe_desc = [
        {"name": f.name, "group": f.group, "description": f.description} for f in FACTORS.values()
    ]

    # B1: hoist yfinance to the top of the cache-miss path so it overlaps with the
    # entire Gemini chain. The pool stays open until we collect the futures below.
    with ThreadPoolExecutor(max_workers=2) as pool:
        progress("market", "start")
        portfolio_future = pool.submit(
            fetch_weekly_prices,
            portfolio_obj.tickers,
            lookback_weeks=config.beta_lookback_weeks,
        )
        factors_future = pool.submit(
            get_factor_returns_with_history,
            lookback_weeks=config.beta_lookback_weeks,
        )

        progress("analogs", "start")
        analog_out = gemini.select_analogs(scenario_text, event_summaries())
        selected_ids = [a.event_id for a in analog_out.selected_events]
        progress("analogs", "done")

        progress("envelope", "start")
        envelope = compute_envelope(selected_ids, registry=events)
        progress("envelope", "done")

        progress("narrative", "start")
        shock_out, citations = gemini.propose_shocks_with_retry(
            scenario_text=scenario_text,
            portfolio=portfolio_obj,
            factor_universe_descriptions=factor_universe_desc,
            envelope=envelope,
            events_registry=events,
        )
        progress("narrative", "done")

        ticker_prices = portfolio_future.result()
        factor_returns, factor_history = factors_future.result()
        progress("market", "done")

    ticker_returns = compute_weekly_returns(ticker_prices)

    progress("betas", "start")
    betas = estimate_betas_for_portfolio(
        portfolio_obj,
        lookback_weeks=config.beta_lookback_weeks,
        alpha=config.ridge_alpha,
        factor_returns=factor_returns,
        ticker_returns=ticker_returns,
    )
    progress("betas", "done")

    progress("attribution", "start")
    pnl = portfolio_pnl(
        portfolio_obj,
        betas,
        shocks={fs.factor: fs.shock for fs in shock_out.factor_shocks},
        periphery_shocks={ps.ticker: ps.shock for ps in shock_out.periphery_shocks},
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

    result = ScenarioResult(
        scenario_text=scenario_text,
        market_date=market_date,
        portfolio_key=resolved_key,
        portfolio_name=portfolio_obj.name,
        portfolio_holdings=dict(portfolio_obj.holdings),
        analogs_selected=analog_out.selected_events,
        factor_shocks=shock_out.factor_shocks,
        periphery_shocks=shock_out.periphery_shocks,
        narrative=shock_out.narrative,
        citations=citations,
        factor_envelope=factor_envelope,
        portfolio_pnl=PortfolioPnL(**pnl),
    )

    cache.put_json(key, result.model_dump(mode="json"))
    return result


def adjust_scenario_shocks(
    cache_key: str,
    *,
    overrides: dict[str, float] | None = None,
    adjustment_text: str | None = None,
    config: Config | None = None,
    gemini: GeminiClient | None = None,
    cache: CacheProtocol | None = None,
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

    # Reconstruct the portfolio. Sample portfolios round-trip via get_portfolio;
    # custom portfolios are rebuilt from the canonical's holdings dict (which is
    # part of the cache-key hash, so we trust it).
    if canonical.portfolio_key == "custom":
        portfolio_obj = Portfolio(
            key="custom",
            name=canonical.portfolio_name,
            holdings=dict(canonical.portfolio_holdings),
        )
    else:
        portfolio_obj = get_portfolio(canonical.portfolio_key)

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
            {"name": f.name, "group": f.group, "description": f.description}
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

    with ThreadPoolExecutor(max_workers=2) as pool:
        portfolio_future = pool.submit(
            fetch_weekly_prices,
            portfolio_obj.tickers,
            lookback_weeks=config.beta_lookback_weeks,
        )
        factors_future = pool.submit(
            get_factor_returns_with_history,
            lookback_weeks=config.beta_lookback_weeks,
        )
        ticker_prices = portfolio_future.result()
        factor_returns, factor_history = factors_future.result()
    ticker_returns = compute_weekly_returns(ticker_prices)

    betas = estimate_betas_for_portfolio(
        portfolio_obj,
        lookback_weeks=config.beta_lookback_weeks,
        alpha=config.ridge_alpha,
        factor_returns=factor_returns,
        ticker_returns=ticker_returns,
    )

    pnl = portfolio_pnl(
        portfolio_obj,
        betas,
        shocks=new_shocks,
        periphery_shocks=periphery_shocks,
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

    return canonical.model_copy(
        update={
            "factor_shocks": new_factor_shocks,
            "portfolio_pnl": PortfolioPnL(**pnl),
            "adjustment_history": [*canonical.adjustment_history, new_entry],
        }
    )


def _envelope_df_from_canonical(canonical: ScenarioResult):
    """Reconstruct the envelope DataFrame from canonical.factor_envelope dict.

    Used by `propose_shock_edit` which expects the same DataFrame shape that
    `compute_envelope` returns.
    """
    import pandas as pd

    if not canonical.factor_envelope:
        return pd.DataFrame(columns=["mean", "p10", "p90", "count"])
    return pd.DataFrame.from_dict(canonical.factor_envelope, orient="index")
