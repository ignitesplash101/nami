"""Engine-replay validation harness tests.

Offline tests cover the pure internals (vintage factor selection, buy-and-hold
math, summary stats, markdown render) plus a fully mocked end-to-end run. The
single network test at the bottom is gated on RUN_NETWORK_TESTS=1 and uses
semantic assertions only (per the live-evals convention — no magnitude bounds).
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd
import pytest

from app.config import Config
from app.factors.engine_replay import (
    ReplayPairResult,
    buy_and_hold_return_usd,
    render_markdown,
    run_engine_replay,
    select_vintage_factors,
    summarize_pairs,
)


def _config() -> Config:
    return Config(
        google_cloud_project="test-project",
        vertex_ai_location="global",
        gcs_bucket="test-bucket",
        vertex_model_id="gemini-3.6-flash",
        llm_temperature=0.0,
        market_data_cache_ttl_hours=24,
        llm_cache_ttl_days=7,
        beta_lookback_weeks=104,
        ridge_alpha=0.1,
        log_level="INFO",
        environment="test",
    )


def test_select_vintage_factors_drops_thin_columns():
    idx = pd.date_range("2019-01-07", periods=60, freq="W")
    frame = pd.DataFrame(
        {
            "SPY": np.linspace(-0.01, 0.01, 60),
            "XLK": np.linspace(-0.02, 0.02, 60),
            "XLC": [np.nan] * 60,  # ETF not launched yet
            "MTUM": [np.nan] * 50 + [0.01] * 10,  # just launched — 10 obs
        },
        index=idx,
    )

    kept, dropped = select_vintage_factors(frame, min_obs=40)

    assert list(kept.columns) == ["SPY", "XLK"]
    assert dropped == ["MTUM", "XLC"]


def test_select_vintage_factors_keeps_all_when_complete():
    idx = pd.date_range("2019-01-07", periods=45, freq="W")
    frame = pd.DataFrame({"SPY": 0.01, "XLK": -0.01}, index=idx)

    kept, dropped = select_vintage_factors(frame, min_obs=40)

    assert list(kept.columns) == ["SPY", "XLK"]
    assert dropped == []


def test_buy_and_hold_return_usd_compounds_fx():
    idx = pd.date_range("2020-02-19", periods=5, freq="B")
    prices = pd.DataFrame(
        {
            "AAPL": [100.0, 98.0, 95.0, 92.0, 90.0],
            # Leading NaN: the first VALID close anchors the window return.
            "7203.T": [np.nan, 2000.0, 1950.0, 1900.0, 1800.0],
        },
        index=idx,
    )
    holdings = {"AAPL": 0.5, "7203.T": 0.5}
    fx_totals = {"AAPL": 0.0, "7203.T": 0.04}  # JPY appreciated 4% over the window

    realized = buy_and_hold_return_usd(prices, holdings, fx_totals)

    aapl = 90.0 / 100.0 - 1.0
    toyota_local = 1800.0 / 2000.0 - 1.0
    toyota_usd = (1.0 + toyota_local) * 1.04 - 1.0
    np.testing.assert_allclose(realized, 0.5 * aapl + 0.5 * toyota_usd, atol=1e-12)


def test_buy_and_hold_return_usd_raises_on_missing_ticker():
    idx = pd.date_range("2020-02-19", periods=3, freq="B")
    prices = pd.DataFrame({"AAPL": [100.0, 99.0, 98.0]}, index=idx)

    with pytest.raises(RuntimeError, match="GHOST"):
        buy_and_hold_return_usd(prices, {"AAPL": 0.5, "GHOST": 0.5}, {})


def _pair(
    event_id: str,
    modeled: float | None,
    realized: float | None,
    skipped: str | None = None,
) -> ReplayPairResult:
    return ReplayPairResult(
        event_id=event_id,
        portfolio_key="defensive_mix",
        modeled_pnl=modeled,
        realized_pnl=realized,
        error=(modeled - realized) if modeled is not None and realized is not None else None,
        n_factors_used=20,
        n_factors_covered=20,
        factors_dropped=["XLC"],
        min_ticker_n_obs=104,
        skipped_reason=skipped,
    )


def test_summarize_pairs_stats():
    pairs = [
        _pair("a", -0.10, -0.20),  # error +0.10, signs agree
        _pair("b", -0.05, -0.10),  # error +0.05, signs agree
        _pair("c", 0.02, -0.04),  # error +0.06, signs disagree
        _pair("d", None, None, skipped="InsufficientHistoryError: T (n=0)"),
    ]

    summary = summarize_pairs(
        pairs,
        regression_spec="ridge-std-v2|lookback=104|alpha=0.1|min_obs=40",
        events_version="abc123",
        factor_universe_version="def456",
        weights_as_of="2026-05-30",
        generated_at="2026-07-02T00:00:00+00:00",
    )

    assert summary.n_pairs == 4
    assert summary.n_computed == 3
    assert summary.n_skipped == 1
    np.testing.assert_allclose(summary.mae, (0.10 + 0.05 + 0.06) / 3, atol=1e-12)
    np.testing.assert_allclose(summary.bias, (0.10 + 0.05 + 0.06) / 3, atol=1e-12)
    np.testing.assert_allclose(summary.sign_hit_rate, 2 / 3, atol=1e-12)
    assert summary.pearson_r is not None
    assert summary.regression_spec.startswith("ridge-std-v2")


def test_summarize_pairs_pearson_none_below_three_computed():
    pairs = [_pair("a", -0.10, -0.20), _pair("b", None, None, skipped="x")]
    summary = summarize_pairs(
        pairs,
        regression_spec="spec",
        events_version="v",
        factor_universe_version="u",
        weights_as_of="2026-05-30",
        generated_at="t",
    )
    assert summary.pearson_r is None
    assert summary.n_computed == 1


def test_render_markdown_smoke():
    pairs = [
        _pair("covid-crash-2020", -0.10, -0.20),
        _pair("lehman-gfc-2008", None, None, skipped="InsufficientHistoryError: META (n=0)"),
    ]
    summary = summarize_pairs(
        pairs,
        regression_spec="ridge-std-v2|lookback=104|alpha=0.1|min_obs=40",
        events_version="abc123",
        factor_universe_version="def456",
        weights_as_of="2026-05-30",
        generated_at="2026-07-02T00:00:00+00:00",
    )

    doc = render_markdown(pairs, summary)

    assert "not a backtest" in doc.lower()
    assert "covid-crash-2020" in doc
    assert "InsufficientHistoryError" in doc
    assert "ridge-std-v2" in doc
    assert "2026-05-30" in doc  # weights vintage disclosed


def test_run_engine_replay_end_to_end_with_mocks(monkeypatch):
    factor_names: list[str] = []

    def _fake_fetch_event_returns(event):
        return pd.Series(dict.fromkeys(factor_names, -0.05), name=event.id)

    def _fake_fetch_factor_returns(start=None, end=None, lookback_weeks=None):
        idx = pd.date_range("2018-01-01", periods=60, freq="W")
        return pd.DataFrame(
            {name: np.linspace(-0.01, 0.01, 60) for name in factor_names}, index=idx
        )

    def _fake_estimate_betas(portfolio, lookback_weeks=156, alpha=0.1, end=None, **_kwargs):
        from app.factors.regression import TickerRegressionStats

        data = np.zeros((len(portfolio.tickers), len(factor_names)))
        data[:, 0] = 1.0
        betas = pd.DataFrame(data, index=portfolio.tickers, columns=factor_names)
        stats = {
            t: TickerRegressionStats(r2=0.9, n_obs=104, idio_vol_weekly=0.01)
            for t in portfolio.tickers
        }
        return betas, stats

    def _fake_fetch_weekly_prices(tickers, *args, **kwargs):
        return pd.DataFrame(
            {t: [100.0, 101.0, 102.0] for t in tickers},
            index=pd.date_range("2019-01-01", periods=3, freq="W"),
        )

    def _fake_fetch_daily_prices(tickers, start=None, end=None, **kwargs):
        # Every ticker drops 10% over the realized window.
        return pd.DataFrame(
            {t: [100.0, 95.0, 90.0] for t in tickers},
            index=pd.date_range(start or "2020-02-19", periods=3, freq="B"),
        )

    from app.factors.universe import FACTORS

    factor_names.extend(FACTORS.keys())

    monkeypatch.setattr("app.factors.analogs.fetch_event_returns", _fake_fetch_event_returns)
    monkeypatch.setattr(
        "app.factors.engine_replay.fetch_factor_returns", _fake_fetch_factor_returns
    )
    monkeypatch.setattr(
        "app.factors.engine_replay.estimate_betas_for_portfolio", _fake_estimate_betas
    )
    monkeypatch.setattr("app.factors.engine_replay.fetch_weekly_prices", _fake_fetch_weekly_prices)
    monkeypatch.setattr("app.factors.engine_replay.fetch_daily_prices", _fake_fetch_daily_prices)
    monkeypatch.setattr(
        "app.factors.engine_replay.convert_weekly_returns_to_usd",
        lambda returns, **_kwargs: returns,
    )

    pairs, summary = run_engine_replay(
        event_ids=["covid-crash-2020"],
        portfolio_keys=["defensive_mix"],
        config=_config(),
        max_workers=1,
    )

    assert len(pairs) == 1
    pair = pairs[0]
    assert pair.skipped_reason is None
    # Mock betas: 1.0 on the first factor; mock event return -0.05 everywhere.
    np.testing.assert_allclose(pair.modeled_pnl, -0.05, atol=1e-12)
    # Mock daily closes: 100 -> 90 for every name (all-USD book, no FX leg).
    np.testing.assert_allclose(pair.realized_pnl, -0.10, atol=1e-12)
    np.testing.assert_allclose(pair.error, 0.05, atol=1e-12)
    assert pair.n_factors_covered == len(FACTORS)
    assert summary.n_computed == 1
    assert summary.n_skipped == 0


@pytest.mark.skipif(
    os.environ.get("RUN_NETWORK_TESTS") != "1",
    reason="network-gated: set RUN_NETWORK_TESTS=1 to run against live yfinance",
)
def test_engine_replay_network_subset_semantic():
    """2×2 subset against live market data — semantic assertions only.

    Sign assertions are limited to the unambiguous pairs: us_tech_growth was
    clearly negative in both windows, defensive_mix clearly negative in the
    COVID crash. q4-trade-war-2018 × defensive_mix is deliberately UNASSERTED
    (defensives were roughly flat that quarter — either sign is plausible).
    """
    pairs, summary = run_engine_replay(
        event_ids=["covid-crash-2020", "q4-trade-war-2018"],
        portfolio_keys=["defensive_mix", "us_tech_growth"],
        max_workers=2,
    )

    assert summary.n_pairs == 4
    computed = [p for p in pairs if p.skipped_reason is None]
    assert len(computed) >= 3  # tolerate one transient-fetch skip

    from app.factors.universe import FACTORS

    for pair in computed:
        assert pair.error == pytest.approx(pair.modeled_pnl - pair.realized_pnl)
        assert 0 < pair.n_factors_covered <= pair.n_factors_used <= len(FACTORS)

    unambiguous = [
        p
        for p in computed
        if p.portfolio_key == "us_tech_growth"
        or (p.portfolio_key == "defensive_mix" and p.event_id == "covid-crash-2020")
    ]
    for pair in unambiguous:
        assert pair.modeled_pnl < 0, f"{pair.event_id}×{pair.portfolio_key} modeled sign"
        assert pair.realized_pnl < 0, f"{pair.event_id}×{pair.portfolio_key} realized sign"


def test_replay_pair_result_shape_is_stable():
    # The artifact JSON serializes these dataclasses; renaming a field silently
    # breaks downstream diffs of scripts/engine_replay_output.json.
    pair = _pair("covid-crash-2020", -0.1, -0.2)
    assert set(pair.__dataclass_fields__) == {
        "event_id",
        "portfolio_key",
        "modeled_pnl",
        "realized_pnl",
        "error",
        "n_factors_used",
        "n_factors_covered",
        "factors_dropped",
        "min_ticker_n_obs",
        "skipped_reason",
    }
