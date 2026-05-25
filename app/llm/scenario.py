"""End-to-end scenario orchestrator: cache -> analog select -> envelope -> shock propose -> betas -> P&L -> cache write."""

from __future__ import annotations

from datetime import date

from app.config import Config, load_config
from app.data.cache import CacheProtocol, CloudStorageCache
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
from app.llm.gemini_client import GeminiClient
from app.llm.prompts import PROMPT_VERSION
from app.llm.schemas import PortfolioPnL, ScenarioResult
from app.utils.hashing import scenario_cache_key


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

    Custom portfolios are stored with `portfolio_key="custom"`; the cache key still
    differentiates them via `portfolio_holdings` (which is part of the SHA256 input).
    """
    if portfolio is not None and portfolio_key is not None:
        raise ValueError("Pass either `portfolio` or `portfolio_key`, not both")
    if portfolio is None and portfolio_key is None:
        raise ValueError("Must pass `portfolio` (str|Portfolio) or `portfolio_key` (str)")

    if isinstance(portfolio, Portfolio):
        portfolio_obj = portfolio
        resolved_key = "custom"
    elif isinstance(portfolio, str):
        portfolio_obj = get_portfolio(portfolio)
        resolved_key = portfolio
    else:
        assert portfolio_key is not None  # narrowed by the guards above
        portfolio_obj = get_portfolio(portfolio_key)
        resolved_key = portfolio_key

    config = config or load_config()
    gemini = gemini or GeminiClient(config)
    if cache is None:
        cache = CloudStorageCache(config.gcs_bucket, prefix="scenario_cache")
    market_date = market_date or date.today()

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
            return ScenarioResult.model_validate(cached)

    events = load_events()
    factor_universe_desc = [
        {"name": f.name, "group": f.group, "description": f.description} for f in FACTORS.values()
    ]

    analog_out = gemini.select_analogs(scenario_text, event_summaries())
    selected_ids = [a.event_id for a in analog_out.selected_events]
    envelope = compute_envelope(selected_ids, registry=events)

    shock_out, citations = gemini.propose_shocks_with_retry(
        scenario_text=scenario_text,
        portfolio=portfolio_obj,
        factor_universe_descriptions=factor_universe_desc,
        envelope=envelope,
        events_registry=events,
    )

    betas = estimate_betas_for_portfolio(
        portfolio_obj,
        lookback_weeks=config.beta_lookback_weeks,
        alpha=config.ridge_alpha,
    )

    pnl = portfolio_pnl(
        portfolio_obj,
        betas,
        shocks={fs.factor: fs.shock for fs in shock_out.factor_shocks},
        periphery_shocks={ps.ticker: ps.shock for ps in shock_out.periphery_shocks},
    )

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
