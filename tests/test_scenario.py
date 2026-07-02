"""Orchestrator tests using injected mocks — no network, no GCS, no Vertex AI."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app.config import Config
from app.data.marking import MarkingError, MarkResult
from app.data.sample_portfolios import Portfolio, get_portfolio
from app.factors.regression import TickerRegressionStats
from app.factors.universe import FACTORS
from app.llm.gemini_client import GeminiClient
from app.llm.scenario import run_scenario
from app.llm.schemas import (
    AnalogSelection,
    AnalogSelectionOutput,
    Citation,
    FactorShock,
    PeripheryShock,
    ShockProposalOutput,
)
from tests.conftest import InMemoryCache


@dataclass
class _MockGeminiClient:
    """Records calls and returns canned outputs."""

    analog_calls: int = 0
    shock_calls: int = 0
    citations: list[Citation] = field(
        default_factory=lambda: [Citation(url="https://example.com", title="Sample")]
    )

    def select_analogs(self, scenario_text, event_summaries) -> AnalogSelectionOutput:
        self.analog_calls += 1
        return AnalogSelectionOutput(
            selected_events=[
                AnalogSelection(event_id="covid-crash-2020", why_relevant="pandemic stress"),
                AnalogSelection(event_id="lehman-gfc-2008", why_relevant="liquidity freeze"),
            ],
            reasoning="picked two stress analogs",
        )

    last_analog_grounded: bool = False

    def propose_shocks_with_retry(
        self,
        *,
        scenario_text,
        portfolio,
        factor_universe_descriptions,
        envelope,
        events_registry,
        max_retries=1,
        analog_grounded: bool = False,
        as_of_date=None,
        selected_analog_events=None,
        per_event_returns=None,
    ):
        # Capture the analog_grounded flag so backdating tests can assert that
        # run_scenario routed through the no-Search path. `last_analog_grounded`
        # is class-shared so the assertion site can read it without holding the
        # instance.
        type(self).last_analog_grounded = analog_grounded
        self.shock_calls += 1
        # Pick the first 3 factors so they line up with the real envelope
        factor_names = list(FACTORS.keys())[:3]
        # Backdated runs return empty citations (no Google Search); live runs
        # return the mock citations.
        citations = [] if analog_grounded else self.citations
        narrative = (
            "Analog-grounded test narrative."
            if analog_grounded
            else "A test narrative grounded in current events."
        )
        return (
            ShockProposalOutput(
                factor_shocks=[
                    FactorShock(factor=factor_names[0], shock=-0.05, reasoning="r0"),
                    FactorShock(factor=factor_names[1], shock=-0.03, reasoning="r1"),
                    FactorShock(factor=factor_names[2], shock=-0.02, reasoning="r2"),
                ],
                periphery_shocks=[
                    PeripheryShock(
                        ticker=next(iter(portfolio.holdings)),
                        shock=-0.10,
                        reasoning="periphery on first holding",
                    )
                ],
                narrative=narrative,
            ),
            citations,
        )


def _config() -> Config:
    return Config(
        google_cloud_project="test-project",
        vertex_ai_location="global",
        gcs_bucket="test-bucket",
        vertex_model_id="gemini-3.5-flash",
        llm_temperature=0.0,
        market_data_cache_ttl_hours=24,
        llm_cache_ttl_days=7,
        beta_lookback_weeks=104,
        ridge_alpha=0.1,
        log_level="INFO",
        environment="test",
    )


def _patch_market_layer(monkeypatch):
    """Replace yfinance-backed pieces with synthetic deterministic data."""
    factor_names = list(FACTORS.keys())

    def _fake_fetch_event_returns(event):
        # Return a simple pattern: each factor's "event return" = -0.05.
        return pd.Series(dict.fromkeys(factor_names, -0.05), name=event.id)

    def _fake_estimate_betas(portfolio, lookback_weeks=156, alpha=0.1, end=None, **_kwargs):
        # Beta of 1.0 to first factor, 0 elsewhere. `factor_returns` /
        # `ticker_returns` may be passed pre-fetched in the parallel-fetch path;
        # the mock ignores them since the betas are hardcoded. Returns the
        # (betas, stats) tuple matching the real estimator's contract.
        data = np.zeros((len(portfolio.tickers), len(factor_names)))
        data[:, 0] = 1.0
        betas = pd.DataFrame(data, index=portfolio.tickers, columns=factor_names)
        stats = {
            t: TickerRegressionStats(r2=0.9, n_obs=104, idio_vol_weekly=0.01)
            for t in portfolio.tickers
        }
        return betas, stats

    # Capture `end=` arg so backdating tests can assert the vintage threading.
    captured: dict[str, object] = {}

    def _fake_fetch_weekly_prices(tickers, *args, **kwargs):
        captured["weekly_prices_end"] = kwargs.get("end")
        return pd.DataFrame(
            {t: [100.0, 101.0, 102.0] for t in tickers},
            index=pd.date_range("2024-01-01", periods=3, freq="W"),
        )

    def _fake_factor_returns_with_history(lookback_weeks=156, end=None):
        captured["factor_history_end"] = end
        n_rows = 60
        idx = pd.date_range("2024-01-01", periods=n_rows, freq="W")
        data = {name: np.linspace(-0.01, 0.01, n_rows) for name in factor_names}
        raw = pd.DataFrame(data, index=idx)
        return raw, raw - raw.mean(axis=0)

    def _fake_get_factor_returns_with_history(lookback_weeks=156):
        # Warm cache wrapper (live runs only — does not accept end=).
        captured["warm_cache_called"] = True
        return _fake_factor_returns_with_history(lookback_weeks=lookback_weeks)

    def _fake_convert_to_usd(returns, *, end=None, cache="default"):
        # Identity stand-in for app.data.fx.convert_weekly_returns_to_usd so
        # orchestrator tests stay network-free even for non-USD books; captures
        # the vintage end= so wiring tests can assert it.
        captured["fx_convert_called"] = True
        captured["fx_convert_end"] = end
        return returns

    monkeypatch.setattr("app.llm.scenario.convert_weekly_returns_to_usd", _fake_convert_to_usd)
    monkeypatch.setattr("app.factors.analogs.fetch_event_returns", _fake_fetch_event_returns)
    monkeypatch.setattr("app.llm.scenario.estimate_betas_for_portfolio", _fake_estimate_betas)
    monkeypatch.setattr("app.llm.scenario.fetch_weekly_prices", _fake_fetch_weekly_prices)
    monkeypatch.setattr(
        "app.llm.scenario.get_factor_returns_with_history",
        _fake_get_factor_returns_with_history,
    )
    monkeypatch.setattr(
        "app.llm.scenario.fetch_factor_returns_with_history",
        _fake_factor_returns_with_history,
    )
    return captured


def test_run_scenario_calls_gemini_and_assembles_result(monkeypatch):
    _patch_market_layer(monkeypatch)

    cache = InMemoryCache()
    gemini = _MockGeminiClient()

    result = run_scenario(
        scenario_text="A pandemic-like risk-off",
        portfolio_key="us_tech_growth",
        config=_config(),
        gemini=gemini,
        cache=cache,
        market_date=date(2026, 5, 25),
    )

    assert gemini.analog_calls == 1
    assert gemini.shock_calls == 1
    assert result.scenario_text == "A pandemic-like risk-off"
    assert len(result.analogs_selected) == 2
    assert len(result.factor_shocks) == 3
    assert len(result.periphery_shocks) == 1
    # Citations: live runs (market_date >= today) carry Google Search citations;
    # backdated runs return empty citations because the analog-grounded path
    # does not invoke Google Search.
    if result.market_date >= date.today():
        assert result.citations
    else:
        assert result.citations == []
    assert result.portfolio_pnl.total_pnl != 0  # SPY beta=1, shock=-0.05 → negative
    assert len(cache.store) == 1


def test_run_scenario_attaches_analog_replay(monkeypatch):
    _patch_market_layer(monkeypatch)
    cache = InMemoryCache()
    gemini = _MockGeminiClient()

    result = run_scenario(
        scenario_text="A pandemic-like risk-off",
        portfolio_key="us_tech_growth",
        config=_config(),
        gemini=gemini,
        cache=cache,
        market_date=date(2026, 5, 25),
    )

    replay = result.analog_replay
    assert replay is not None
    assert [e.event_id for e in replay.per_event] == result.selected_event_ids
    # Mock layer: betas are 1.0 on the first factor only and every event factor
    # return is -0.05, so each analog replays to exactly -0.05 with full coverage.
    for entry in replay.per_event:
        assert entry.replay_pnl == pytest.approx(-0.05)
        assert entry.n_factors_covered == len(FACTORS)
        assert entry.n_factors_total == len(FACTORS)
    assert replay.min_pnl == pytest.approx(-0.05)
    assert replay.median_pnl == pytest.approx(-0.05)
    assert replay.max_pnl == pytest.approx(-0.05)


def test_run_scenario_cache_hit_round_trips_analog_replay(monkeypatch):
    _patch_market_layer(monkeypatch)
    cache = InMemoryCache()
    gemini = _MockGeminiClient()

    first = run_scenario(
        scenario_text="Same scenario",
        portfolio_key="us_tech_growth",
        config=_config(),
        gemini=gemini,
        cache=cache,
        market_date=date(2026, 5, 25),
    )
    second = run_scenario(
        scenario_text="Same scenario",
        portfolio_key="us_tech_growth",
        config=_config(),
        gemini=gemini,
        cache=cache,
        market_date=date(2026, 5, 25),
    )

    assert first.analog_replay is not None
    assert second.analog_replay == first.analog_replay


def test_run_scenario_cache_hit_skips_gemini(monkeypatch):
    _patch_market_layer(monkeypatch)
    cache = InMemoryCache()
    gemini = _MockGeminiClient()

    run_scenario(
        scenario_text="Same scenario",
        portfolio_key="us_tech_growth",
        config=_config(),
        gemini=gemini,
        cache=cache,
        market_date=date(2026, 5, 25),
    )
    first_calls = (gemini.analog_calls, gemini.shock_calls)

    # Second run — should hit cache and not call gemini.
    run_scenario(
        scenario_text="Same scenario",
        portfolio_key="us_tech_growth",
        config=_config(),
        gemini=gemini,
        cache=cache,
        market_date=date(2026, 5, 25),
    )
    assert (gemini.analog_calls, gemini.shock_calls) == first_calls


def test_run_scenario_cache_key_changes_when_market_date_changes(monkeypatch):
    _patch_market_layer(monkeypatch)
    cache = InMemoryCache()
    gemini = _MockGeminiClient()

    run_scenario(
        scenario_text="Same scenario",
        portfolio_key="us_tech_growth",
        config=_config(),
        gemini=gemini,
        cache=cache,
        market_date=date(2026, 5, 25),
    )
    run_scenario(
        scenario_text="Same scenario",
        portfolio_key="us_tech_growth",
        config=_config(),
        gemini=gemini,
        cache=cache,
        market_date=date(2026, 5, 26),
    )

    assert len(cache.store) == 2, "Different market_date must produce a fresh cache entry"


def test_run_scenario_skip_cache_forces_fresh_call(monkeypatch):
    _patch_market_layer(monkeypatch)
    cache = InMemoryCache()
    gemini = _MockGeminiClient()

    run_scenario(
        scenario_text="x",
        portfolio_key="us_tech_growth",
        config=_config(),
        gemini=gemini,
        cache=cache,
        market_date=date(2026, 5, 25),
    )

    # skip_cache=True should re-call gemini even though cache has the entry
    run_scenario(
        scenario_text="x",
        portfolio_key="us_tech_growth",
        config=_config(),
        gemini=gemini,
        cache=cache,
        market_date=date(2026, 5, 25),
        skip_cache=True,
    )

    assert gemini.analog_calls == 2
    assert gemini.shock_calls == 2


def test_run_scenario_rejects_unknown_analog_id(monkeypatch):
    """A hallucinated analog id from the selector must raise ValueError (the API
    maps it to 422), not bubble up as a raw KeyError from compute_envelope (500)."""
    _patch_market_layer(monkeypatch)

    class _BogusAnalogClient(_MockGeminiClient):
        def select_analogs(self, scenario_text, event_summaries) -> AnalogSelectionOutput:
            self.analog_calls += 1
            return AnalogSelectionOutput(
                selected_events=[
                    AnalogSelection(event_id="not-a-real-event", why_relevant="hallucinated"),
                    AnalogSelection(event_id="covid-crash-2020", why_relevant="real"),
                ],
                reasoning="one bogus id",
            )

    with pytest.raises(ValueError, match="not in the"):
        run_scenario(
            scenario_text="x",
            portfolio_key="us_tech_growth",
            config=_config(),
            gemini=_BogusAnalogClient(),
            cache=InMemoryCache(),
            market_date=date(2026, 5, 25),
        )


def test_benchmark_overlay_attached_on_miss_and_hit(monkeypatch):
    """Sample portfolios carry a benchmark; the overlay attaches benchmark P&L +
    active return, and a cache hit re-attaches it (it is never cached)."""
    _patch_market_layer(monkeypatch)
    cache = InMemoryCache()
    gemini = _MockGeminiClient()

    result = run_scenario(
        scenario_text="risk-off",
        portfolio_key="us_tech_growth",
        config=_config(),
        gemini=gemini,
        cache=cache,
        market_date=date(2026, 5, 25),
    )
    assert result.benchmark_ticker == "QQQ"
    assert result.benchmark_pnl is not None
    assert result.active_return is not None
    expected_active = result.portfolio_pnl.total_pnl - result.benchmark_pnl.total_pnl
    assert result.active_return == pytest.approx(expected_active)

    # The cached canonical must NOT carry the overlay (return-space only).
    (cached_blob,) = cache.store.values()
    assert cached_blob.get("benchmark_ticker") is None
    assert cached_blob.get("active_return") is None

    # Cache hit re-derives the benchmark.
    hit = run_scenario(
        scenario_text="risk-off",
        portfolio_key="us_tech_growth",
        config=_config(),
        gemini=gemini,
        cache=cache,
        market_date=date(2026, 5, 25),
    )
    assert hit.benchmark_ticker == "QQQ"
    assert hit.benchmark_pnl is not None
    assert hit.active_return is not None


def test_explicit_benchmark_overrides_sample(monkeypatch):
    _patch_market_layer(monkeypatch)
    result = run_scenario(
        scenario_text="risk-off",
        portfolio_key="us_tech_growth",
        config=_config(),
        gemini=_MockGeminiClient(),
        cache=InMemoryCache(),
        market_date=date(2026, 5, 25),
        benchmark="SPY",
    )
    assert result.benchmark_ticker == "SPY"


def test_cash_sleeve_contributes_zero_and_dilutes(monkeypatch):
    """A CASH sleeve is zero-beta/zero-return: it appears in by_ticker_total at 0
    and its weight dilutes the rest (never sent to yfinance)."""
    _patch_market_layer(monkeypatch)
    book = Portfolio(
        name="Cash test",
        description="60/30/10 with cash",
        holdings={"AAPL": 0.6, "MSFT": 0.3, "CASH": 0.1},
    )
    result = run_scenario(
        scenario_text="risk-off",
        portfolio=book,
        config=_config(),
        gemini=_MockGeminiClient(),
        cache=InMemoryCache(),
        market_date=date(2026, 5, 25),
    )
    assert result.portfolio_pnl.by_ticker_total["CASH"] == 0.0
    # All factor P&L comes from the 0.9 non-cash sleeve; cash drags toward zero.
    no_cash = Portfolio(
        name="No cash",
        description="2/3 1/3",
        holdings={"AAPL": 2 / 3, "MSFT": 1 / 3},
    )
    result_full = run_scenario(
        scenario_text="risk-off",
        portfolio=no_cash,
        config=_config(),
        gemini=_MockGeminiClient(),
        cache=InMemoryCache(),
        market_date=date(2026, 5, 25),
    )
    # The cash book's |total| should be ~0.9× the fully-invested book's |total|.
    assert abs(result.portfolio_pnl.total_pnl) < abs(result_full.portfolio_pnl.total_pnl)


def test_run_scenario_rejects_out_of_range_analog_selection(monkeypatch):
    """The '2 to 5' cardinality lives in code, not just the selection prompt."""
    _patch_market_layer(monkeypatch)

    class _OneAnalogClient(_MockGeminiClient):
        def select_analogs(self, scenario_text, event_summaries):
            self.analog_calls += 1
            return AnalogSelectionOutput(
                selected_events=[
                    AnalogSelection(event_id="covid-crash-2020", why_relevant="only one")
                ],
                reasoning="one only",
            )

    with pytest.raises(ValueError, match="2 to 5"):
        run_scenario(
            scenario_text="risk-off",
            portfolio_key="us_tech_growth",
            config=_config(),
            gemini=_OneAnalogClient(),
            cache=InMemoryCache(),
            market_date=date(2026, 5, 25),
        )

    class _SixAnalogClient(_MockGeminiClient):
        def select_analogs(self, scenario_text, event_summaries):
            self.analog_calls += 1
            ids = [
                "covid-crash-2020",
                "lehman-gfc-2008",
                "brexit-2016",
                "svb-banking-2023",
                "china-deval-2015",
                "taper-tantrum-2013",
            ]
            return AnalogSelectionOutput(
                selected_events=[AnalogSelection(event_id=i, why_relevant="breadth") for i in ids],
                reasoning="six",
            )

    with pytest.raises(ValueError, match="2 to 5"):
        run_scenario(
            scenario_text="risk-off",
            portfolio_key="us_tech_growth",
            config=_config(),
            gemini=_SixAnalogClient(),
            cache=InMemoryCache(),
            market_date=date(2026, 5, 25),
        )


def test_run_scenario_rejects_out_of_range_pinned_ids(monkeypatch):
    """The cardinality guard also covers the pinned-decomposition path, which
    bypasses the LLM selector entirely."""
    _patch_market_layer(monkeypatch)
    with pytest.raises(ValueError, match="2 to 5"):
        run_scenario(
            scenario_text="risk-off",
            portfolio_key="us_tech_growth",
            config=_config(),
            gemini=_MockGeminiClient(),
            cache=InMemoryCache(),
            market_date=date(2026, 5, 25),
            pinned_event_ids=["covid-crash-2020"],
        )


def test_run_scenario_attaches_analog_event_returns(monkeypatch):
    """Per-analog returns + window lengths ride the result and the cache."""
    _patch_market_layer(monkeypatch)
    cache = InMemoryCache()

    result = run_scenario(
        scenario_text="risk-off",
        portfolio_key="us_tech_growth",
        config=_config(),
        gemini=_MockGeminiClient(),
        cache=cache,
        market_date=date(2026, 5, 25),
    )
    assert result.analog_event_returns is not None
    assert [r.event_id for r in result.analog_event_returns] == [
        "covid-crash-2020",
        "lehman-gfc-2008",
    ]
    covid = result.analog_event_returns[0]
    assert covid.window_calendar_days == 33  # 2020-02-19 -> 2020-03-23
    assert set(covid.factor_returns) == set(FACTORS.keys())
    assert covid.factor_returns["SPY"] == pytest.approx(-0.05)

    hit = run_scenario(
        scenario_text="risk-off",
        portfolio_key="us_tech_growth",
        config=_config(),
        gemini=_MockGeminiClient(),
        cache=cache,
        market_date=date(2026, 5, 25),
    )
    assert hit.analog_event_returns is not None
    assert len(hit.analog_event_returns) == 2


def test_run_scenario_routes_ticker_returns_through_usd_conversion(monkeypatch):
    """The beta-estimation return history passes through the USD converter with
    the vintage-correct exclusive-end bound (backdated run here)."""
    captured = _patch_market_layer(monkeypatch)
    result = run_scenario(
        scenario_text="risk-off",
        portfolio_key="us_tech_growth",
        config=_config(),
        gemini=_MockGeminiClient(),
        cache=InMemoryCache(),
        market_date=date(2026, 5, 25),
    )
    assert captured["fx_convert_called"] is True
    assert captured["fx_convert_end"] == result.market_date + timedelta(days=1)


def test_run_scenario_attaches_and_caches_regression_quality(monkeypatch):
    """The fit-quality block is set on fresh runs, excludes CASH, and — unlike the
    NAV/benchmark overlays — round-trips the scenario cache."""
    _patch_market_layer(monkeypatch)
    cache = InMemoryCache()
    book = Portfolio(
        name="Cash test",
        description="60/30/10 with cash",
        holdings={"AAPL": 0.6, "MSFT": 0.3, "CASH": 0.1},
    )

    result = run_scenario(
        scenario_text="risk-off",
        portfolio=book,
        config=_config(),
        gemini=_MockGeminiClient(),
        cache=cache,
        market_date=date(2026, 5, 25),
    )
    assert result.regression_quality is not None
    assert result.regression_quality.estimator == "ridge-std-v2"
    # No regression runs for the CASH sentinel — no stats entry for it.
    assert set(result.regression_quality.by_ticker) == {"AAPL", "MSFT"}
    assert result.regression_quality.by_ticker["AAPL"].r2 == 0.9

    hit = run_scenario(
        scenario_text="risk-off",
        portfolio=book,
        config=_config(),
        gemini=_MockGeminiClient(),
        cache=cache,
        market_date=date(2026, 5, 25),
    )
    assert hit.regression_quality is not None
    assert set(hit.regression_quality.by_ticker) == {"AAPL", "MSFT"}


def _fake_mark_book(nav: float = 1_000_000.0):
    """Return a stand-in mark_book that derives weights from quantities, no network."""

    def fake(quantities, *, as_of, reporting_currency="USD", cache="default"):
        total = sum(quantities.values())
        weights = {t: q / total for t, q in quantities.items()}
        return MarkResult(
            nav=nav,
            weights=weights,
            position_values={t: nav * w for t, w in weights.items()},
            mark_prices=dict.fromkeys(quantities, 100.0),
            price_date_by_ticker=dict.fromkeys(quantities, as_of.isoformat()),
            fx_rates={"USD": 1.0},
            fx_date_by_currency={"USD": as_of.isoformat()},
            reporting_currency=reporting_currency,
        )

    return fake


def test_run_scenario_quantity_mode_attaches_nav_and_caches_return_space_only(monkeypatch):
    _patch_market_layer(monkeypatch)
    monkeypatch.setattr("app.llm.scenario.mark_book", _fake_mark_book(1_000_000.0))
    cache = InMemoryCache()
    gemini = _MockGeminiClient()
    provisional = Portfolio(name="MTM book", description="x", holdings={"AAPL": 0.5, "MSFT": 0.5})

    result = run_scenario(
        "stress",
        provisional,
        config=_config(),
        gemini=gemini,
        cache=cache,
        market_date=date(2026, 5, 25),
        position_quantities={"AAPL": 10, "MSFT": 5},
    )

    assert result.portfolio_nav == 1_000_000.0
    assert result.reporting_currency == "USD"
    assert result.position_quantities == {"AAPL": 10, "MSFT": 5}
    assert result.position_values is not None
    # The price-derived marks (not the provisional 0.5/0.5) drive P&L.
    assert result.portfolio_holdings["AAPL"] == pytest.approx(10 / 15)

    # The GCS cache holds the RETURN-SPACE canonical only: NAV / marks are never
    # persisted (so a different NAV can never serve stale dollars), but the
    # quantity INPUTS are kept so a hit / adjustment can re-mark.
    (cached,) = cache.store.values()
    assert cached["portfolio_nav"] is None
    assert cached["position_values"] is None
    assert cached["position_quantities"] == {"AAPL": 10, "MSFT": 5}


def test_run_scenario_quantity_mode_cache_hit_remarks(monkeypatch):
    _patch_market_layer(monkeypatch)
    calls = {"n": 0}

    def counting_mark(quantities, *, as_of, reporting_currency="USD", cache="default"):
        calls["n"] += 1
        return _fake_mark_book(2_000_000.0)(
            quantities, as_of=as_of, reporting_currency=reporting_currency, cache=cache
        )

    monkeypatch.setattr("app.llm.scenario.mark_book", counting_mark)
    cache = InMemoryCache()
    gemini = _MockGeminiClient()
    prov = Portfolio(name="m", description="x", holdings={"AAPL": 1.0})
    kwargs = {
        "config": _config(),
        "gemini": gemini,
        "cache": cache,
        "market_date": date(2026, 5, 25),
        "position_quantities": {"AAPL": 7},
    }

    r1 = run_scenario("s", prov, **kwargs)
    r2 = run_scenario("s", prov, **kwargs)  # cache hit on the return-space canonical
    assert gemini.shock_calls == 1, "second run must hit the return-space cache"
    assert calls["n"] == 2, "MTM is re-marked on the hit (NAV is never cached)"
    assert r1.portfolio_nav == r2.portfolio_nav == 2_000_000.0


def test_run_scenario_quantity_mode_fail_closed(monkeypatch):
    _patch_market_layer(monkeypatch)

    def boom(*args, **kwargs):
        raise MarkingError("no price for FOO")

    monkeypatch.setattr("app.llm.scenario.mark_book", boom)
    with pytest.raises(MarkingError):
        run_scenario(
            "s",
            Portfolio(name="m", description="x", holdings={"AAPL": 1.0}),
            config=_config(),
            gemini=_MockGeminiClient(),
            cache=InMemoryCache(),
            market_date=date(2026, 5, 25),
            position_quantities={"AAPL": 10},
        )


def test_run_scenario_nav_scalar_mode_not_cached(monkeypatch):
    _patch_market_layer(monkeypatch)
    cache = InMemoryCache()
    result = run_scenario(
        "s",
        "us_tech_growth",
        config=_config(),
        gemini=_MockGeminiClient(),
        cache=cache,
        market_date=date(2026, 5, 25),
        portfolio_nav=500_000.0,
    )
    assert result.portfolio_nav == 500_000.0
    assert result.reporting_currency == "USD"
    # NAV scalar is a pure post-cache overlay; the canonical must not carry it.
    (cached,) = cache.store.values()
    assert cached["portfolio_nav"] is None


def test_run_scenario_pinned_event_ids_skip_selection_and_force_analog_only(monkeypatch):
    """Fixed-context decomposition: pinned analogs skip select_analogs and force the
    analog-only (no-Search) narrative path even on a LIVE run."""
    _patch_market_layer(monkeypatch)

    class _NoSelectClient(_MockGeminiClient):
        def select_analogs(self, scenario_text, event_summaries):
            raise AssertionError("select_analogs must not be called when analogs are pinned")

    gemini = _NoSelectClient()
    result = run_scenario(
        "stress",
        "us_tech_growth",
        config=_config(),
        gemini=gemini,
        cache=InMemoryCache(),
        market_date=None,  # live — isolate pinned's effect from backdating
        pinned_event_ids=["covid-crash-2020", "lehman-gfc-2008"],
    )

    assert result.narrative_mode == "analog_only"
    assert type(gemini).last_analog_grounded is True
    assert result.selected_event_ids == ["covid-crash-2020", "lehman-gfc-2008"]
    assert result.citations == []  # analog-only path returns no Google-Search citations


def test_run_scenario_pinned_unknown_id_raises(monkeypatch):
    _patch_market_layer(monkeypatch)
    with pytest.raises(ValueError, match="not in the"):
        run_scenario(
            "x",
            "us_tech_growth",
            config=_config(),
            gemini=_MockGeminiClient(),
            cache=InMemoryCache(),
            market_date=None,
            pinned_event_ids=["not-a-real-event"],
        )


def test_get_portfolio_smoke():
    # Sanity check the imports work; placeholder for future portfolio-tests file.
    assert get_portfolio("us_tech_growth") is not None


def test_run_scenario_accepts_portfolio_object_positional(monkeypatch):
    """Passing a Portfolio object as the second positional arg uses 'custom' as resolved_key
    and populates portfolio_name + portfolio_holdings on the result."""
    _patch_market_layer(monkeypatch)
    cache = InMemoryCache()
    gemini = _MockGeminiClient()

    custom = Portfolio(
        name="My Custom",
        description="test custom",
        holdings={"AAPL": 0.6, "MSFT": 0.4},
    )

    result = run_scenario(
        "stress",
        custom,
        config=_config(),
        gemini=gemini,
        cache=cache,
        market_date=date(2026, 5, 25),
    )

    assert result.portfolio_key == "custom"
    assert result.portfolio_name == "My Custom"
    assert result.portfolio_holdings == {"AAPL": 0.6, "MSFT": 0.4}


def test_run_scenario_rejects_both_portfolio_and_portfolio_key():
    with pytest.raises(ValueError, match="not both"):
        run_scenario(
            "x",
            "us_tech_growth",
            portfolio_key="msci_world",
            config=_config(),
            gemini=_MockGeminiClient(),
            cache=InMemoryCache(),
            market_date=date(2026, 5, 25),
        )


def test_run_scenario_rejects_neither_portfolio_nor_portfolio_key():
    with pytest.raises(ValueError, match="Must pass"):
        run_scenario(
            "x",
            config=_config(),
            gemini=_MockGeminiClient(),
            cache=InMemoryCache(),
            market_date=date(2026, 5, 25),
        )


def test_propose_shocks_raises_when_grounded_narrative_returns_no_citations(monkeypatch):
    """Production guard: do not proceed when Google Search grounding did not fire."""
    client = GeminiClient.__new__(GeminiClient)
    portfolio = get_portfolio("us_tech_growth")
    envelope = pd.DataFrame(
        {"mean": [-0.05], "p10": [-0.10], "p90": [0.0], "count": [2]},
        index=["SPY"],
    )

    def _grounded_narrative_without_citations(**kwargs):
        return "A current-market narrative with no citation metadata.", []

    def _extract_should_not_run(**kwargs):
        raise AssertionError("structured extraction should not run without citations")

    monkeypatch.setattr(client, "_grounded_narrative", _grounded_narrative_without_citations)
    monkeypatch.setattr(client, "_extract_structured_shocks", _extract_should_not_run)

    with pytest.raises(RuntimeError, match="no citations|Google Search"):
        client.propose_shocks_with_retry(
            scenario_text="latest market news",
            portfolio=portfolio,
            factor_universe_descriptions=[],
            envelope=envelope,
            events_registry={},
        )
