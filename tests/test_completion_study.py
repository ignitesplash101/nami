"""Completion study: unit transforms plus an offline end-to-end evaluation."""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.config import Config
from app.data.sample_portfolios import Portfolio
from app.factors import completion_study as study
from app.factors.completion_study import (
    BookInputs,
    EventInputs,
    StudyInputs,
    _level_changes,
    _level_moves,
    evaluate,
    render_markdown,
)

FACTOR_NAMES = ["SPY", "XLK", "XLF", "TNX", "VIX"]
BOOK = Portfolio(name="toy", description="toy", holdings={"T1": 0.5, "T2": 0.3, "T3": 0.2})


def _config() -> Config:
    return Config(
        google_cloud_project="test-project",
        vertex_ai_location="global",
        gcs_bucket="test-bucket",
        vertex_model_id="gemini-3.8-flash",
        market_data_cache_ttl_hours=24,
        llm_cache_ttl_days=7,
        beta_lookback_weeks=104,
        ridge_alpha=0.1,
        log_level="INFO",
        environment="test",
    )


def test_level_changes_use_yield_points_and_logs():
    idx = pd.date_range("2024-01-05", periods=3, freq="W-FRI")
    levels = pd.DataFrame({"TNX": [4.0, 4.2, 4.1], "VIX": [15.0, 30.0, 15.0]}, index=idx)
    out = _level_changes(levels, idx)
    assert out["TNX"].iloc[1] == pytest.approx(0.002)
    assert out["VIX"].iloc[1] == pytest.approx(math.log(2.0))
    assert np.isnan(out["TNX"].iloc[0])


def test_level_moves_report_start_levels_and_skip_non_positive_logs():
    daily = pd.DataFrame({"TNX": [1.63, 2.10, 2.98], "OIL": [20.0, -5.0, -1.0]})
    moves, starts = _level_moves(daily)
    assert moves["TNX"] == pytest.approx(0.0135)
    assert starts["TNX"] == pytest.approx(1.63)
    assert "OIL" not in moves  # a log change through a negative price is undefined


def _synthetic_inputs(seed: int = 1) -> StudyInputs:
    rng = np.random.default_rng(seed)
    n = 120
    idx = pd.date_range("2018-01-05", periods=n, freq="W-FRI")
    spy = rng.normal(0.0, 0.02, n)
    factors = pd.DataFrame(
        {
            "SPY": spy,
            "XLK": 1.3 * spy + rng.normal(0.0, 0.008, n),
            "XLF": 1.1 * spy + rng.normal(0.0, 0.01, n),
            "TNX": 0.8 * spy + rng.normal(0.0, 0.02, n),
            "VIX": -4.0 * spy + rng.normal(0.0, 0.05, n),
        },
        index=idx,
    )
    tickers = pd.DataFrame(
        {
            "T1": 0.3 * factors["SPY"] + 0.9 * factors["XLK"] + rng.normal(0, 0.01, n),
            "T2": 1.0 * factors["XLF"] + rng.normal(0, 0.01, n),
            "T3": 0.8 * factors["SPY"] - 0.1 * factors["TNX"] + rng.normal(0, 0.01, n),
        },
        index=idx,
    )
    tnx_level = 2.0 * np.cumprod(1.0 + factors["TNX"].to_numpy())
    vix_level = 15.0 * np.cumprod(1.0 + factors["VIX"].to_numpy())
    levels = pd.DataFrame({"TNX": tnx_level, "VIX": vix_level}, index=idx)
    level_changes = _level_changes(levels, idx)

    # A crash whose non-market moves follow the market as the history says they do.
    realized = {"SPY": -0.20, "XLK": -0.26, "XLF": -0.22, "TNX": -0.16, "VIX": 0.80}
    ev = EventInputs(
        event_id="toy-crash",
        start_date=date(2020, 5, 1),
        end_date=date(2020, 6, 12),
        factor_returns=factors,
        dropped=[],
        level_changes=level_changes,
        realized=realized,
        realized_levels={"TNX": -0.0032, "VIX": math.log(1.8)},
        start_levels={"TNX": 2.0, "VIX": 15.0},
    )
    realized_book = 0.5 * (0.3 * -0.20 + 0.9 * -0.26) + 0.3 * -0.22 + 0.2 * (0.8 * -0.20 + 0.016)
    books = [
        BookInputs("toy-crash", "toy", tickers, realized_book, None),
        BookInputs("toy-crash", "skipped", None, None, "cash sleeve not supported"),
    ]
    return StudyInputs(
        events=[ev],
        books=books,
        reference_tnx_level=5.0,
        reference_date="2026-10-09",
        regression_spec="spec",
        events_version="ev",
        factor_universe_version="fu",
        weights_as_of="2026-05-30",
        gathered_at="2026-10-16T00:00:00+00:00",
    )


@pytest.fixture
def toy_book(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(study, "get_portfolio", lambda key: BOOK)


def test_completion_recovers_more_than_zero_fill(toy_book: None):
    pairs, summary = evaluate(_synthetic_inputs(), config=_config(), bootstrap=5)
    computed = [p for p in pairs if p.skipped_reason is None]
    assert len(computed) == 1 and len(pairs) == 2
    pair = computed[0]
    err = {v: abs(pair.modeled[f"market:{v}"] - pair.realized_pnl) for v in ("V0", "V1", "V3")}
    assert err["V1"] < err["V0"]
    assert err["V3"] < err["V0"]
    # Span-invariant reparametrization: the full vector gives the same P&L in both bases.
    assert pair.full_replay["raw"] == pytest.approx(pair.full_replay["rel"], abs=2e-3)
    assert pair.sigma["market:V1"] > 0.0
    assert {g.key for g in summary.gates} == {"G1_completion", "G2_relative_basis", "G3_units"}
    assert summary.n_computed == 1


def test_relative_zero_fill_moves_sectors_with_the_market(toy_book: None):
    pairs, _ = evaluate(_synthetic_inputs(), config=_config(), bootstrap=0)
    pair = next(p for p in pairs if p.skipped_reason is None)
    # Anchoring only SPY: raw zero-fill drops every sector move, relative zero-fill keeps
    # each sector's usual co-move with the market.
    assert abs(pair.modeled["market:V2"] - pair.realized_pnl) < abs(
        pair.modeled["market:V0"] - pair.realized_pnl
    )


def test_evaluation_is_deterministic_for_a_seed(toy_book: None):
    a, _ = evaluate(_synthetic_inputs(), config=_config(), bootstrap=8, seed=3)
    b, _ = evaluate(_synthetic_inputs(), config=_config(), bootstrap=8, seed=3)
    assert a[0].modeled == b[0].modeled
    assert a[0].attribution == b[0].attribution


def test_render_markdown_has_every_section(toy_book: None):
    pairs, summary = evaluate(
        _synthetic_inputs(),
        config=_config(),
        bootstrap=5,
        replay_reference={("toy-crash", "toy"): 0.0},
    )
    text = render_markdown(pairs, summary)
    for heading in (
        "## Gates (pre-registered before the first run)",
        "## By anchor set",
        "## Attribution stability",
        "## Collinearity of the factor basis",
        "## Rate units",
        "## Cross-check against the engine replay",
        "## Skipped pairs",
        "## Provenance",
    ):
        assert heading in text
    assert summary.replay_crosscheck["n_compared"] == 1
