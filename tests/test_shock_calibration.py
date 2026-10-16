"""Shock-calibration study: case loading, resumable budgeted runs, offline scoring."""

from __future__ import annotations

import threading
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app.config import Config
from app.factors.analogs import filter_events_as_of, load_events
from app.factors.completion import complete_shocks
from app.factors.completion_study import BookInputs, EventInputs, StudyInputs
from app.llm import shock_calibration as cal
from app.llm.shock_calibration import (
    CalibrationBudgetExceeded,
    RunRecord,
    TallyingGeminiClient,
    execute_runs,
    load_cases,
    plan_runs,
    read_checkpoint,
    render_markdown,
    score_record,
    score_runs,
)


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


def test_every_case_is_leave_one_out_by_construction():
    events = load_events()
    cases = load_cases()
    assert len(cases) == 14
    for case in cases:
        event = events[case.event_id]
        assert case.as_of < event.start_date
        eligible = filter_events_as_of(events, case.as_of)
        assert case.event_id not in eligible
        assert all(e.end_date <= case.as_of for e in eligible.values())


def test_load_cases_rejects_unknown_event(tmp_path: Path):
    path = tmp_path / "prompts.yaml"
    path.write_text("not-an-event: some text\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not-an-event"):
        load_cases(path)


def test_plan_repeats_only_the_primary_book():
    cases = load_cases()
    planned = plan_runs(cases)
    assert len(planned) == len(cases) * (3 + 1 + 1 + 1)
    assert sum(1 for p in planned if p[1] == "msci_world") == 3 * len(cases)


class _StubGemini:
    """Duck-typed stand-in for TallyingGeminiClient (no SDK client)."""

    def __init__(self, spent: float = 0.0) -> None:
        self.spent_usd = spent

    def begin_run(self) -> None:
        return None

    def run_cost(self) -> float:
        return 0.07


def _fake_result(case_event: str) -> SimpleNamespace:
    return SimpleNamespace(
        factor_shocks=[SimpleNamespace(factor="SPY", shock=-0.1)],
        periphery_shocks=[],
        selected_event_ids=["covid-crash-2020", "brexit-2016"],
        analog_event_returns=[
            SimpleNamespace(event_id="covid-crash-2020", factor_returns={"SPY": -0.3}),
            SimpleNamespace(event_id="brexit-2016", factor_returns={"SPY": -0.05}),
        ],
        portfolio_pnl=SimpleNamespace(total_pnl=-0.08),
    )


def test_runs_checkpoint_resume_and_max_runs(tmp_path: Path):
    cases = [c for c in load_cases() if c.event_id == "svb-banking-2023"]
    planned = plan_runs(cases)
    checkpoint = tmp_path / "runs.jsonl"
    calls: list[tuple[str, str]] = []

    def run_fn(prompt, *, portfolio_key, market_date, **kwargs):
        assert kwargs["skip_cache"] is True
        assert kwargs["cache"].get_json("anything") is None
        assert market_date == cases[0].as_of
        calls.append((prompt, portfolio_key))
        return _fake_result(cases[0].event_id)

    first = execute_runs(
        cases,
        planned,
        checkpoint=checkpoint,
        max_runs=2,
        jobs=1,
        config=_config(),
        gemini=_StubGemini(),
        run_fn=run_fn,
    )
    assert len(first) == 2 and len(calls) == 2
    rest = execute_runs(
        cases,
        planned,
        checkpoint=checkpoint,
        jobs=2,
        config=_config(),
        gemini=_StubGemini(),
        run_fn=run_fn,
    )
    assert len(rest) == len(planned) - 2
    again = execute_runs(
        cases,
        planned,
        checkpoint=checkpoint,
        jobs=2,
        config=_config(),
        gemini=_StubGemini(),
        run_fn=run_fn,
    )
    assert again == []
    records = read_checkpoint(checkpoint)
    assert len(records) == len(planned)
    assert all(r.error is None and r.headline_pnl == pytest.approx(-0.08) for r in records)


def test_failed_runs_are_recorded_and_retried(tmp_path: Path):
    cases = [c for c in load_cases() if c.event_id == "svb-banking-2023"]
    planned = plan_runs(cases, ["defensive_mix"])
    checkpoint = tmp_path / "runs.jsonl"

    def boom(*args, **kwargs):
        raise RuntimeError("provider timeout")

    execute_runs(
        cases, planned, checkpoint=checkpoint, config=_config(), gemini=_StubGemini(), run_fn=boom
    )
    assert read_checkpoint(checkpoint)[0].error == "RuntimeError: provider timeout"
    retried = execute_runs(
        cases,
        planned,
        checkpoint=checkpoint,
        config=_config(),
        gemini=_StubGemini(),
        run_fn=lambda *a, **k: _fake_result("x"),
    )
    assert len(retried) == 1 and retried[0].error is None


def test_budget_stops_scheduling(tmp_path: Path):
    cases = [c for c in load_cases() if c.event_id == "svb-banking-2023"]
    called = []
    out = execute_runs(
        cases,
        plan_runs(cases),
        checkpoint=tmp_path / "r.jsonl",
        budget_usd=1.0,
        config=_config(),
        gemini=_StubGemini(spent=0.99),
        run_fn=lambda *a, **k: called.append(1),
    )
    assert out == [] and called == []


def test_tallying_client_books_billed_tokens_and_enforces_cap(monkeypatch: pytest.MonkeyPatch):
    client = TallyingGeminiClient.__new__(TallyingGeminiClient)

    client._config = _config()
    client._budget = 1.0
    client._lock = threading.Lock()
    client._local = threading.local()
    client.spent_usd = 0.0
    response = SimpleNamespace(
        usage_metadata=SimpleNamespace(
            prompt_token_count=100_000, candidates_token_count=10_000, thoughts_token_count=10_000
        )
    )
    monkeypatch.setattr(cal.GeminiClient, "_generate_content", lambda self, **kw: response)
    client.begin_run()
    client._generate_content(contents="x", config=None)
    expected = 0.1 * 1.50 + 0.02 * 7.50
    assert client.run_cost() == pytest.approx(expected)
    assert client.spent_usd == pytest.approx(expected)
    client.spent_usd = 1.0
    with pytest.raises(CalibrationBudgetExceeded):
        client._generate_content(contents="x", config=None)


def _cov() -> pd.DataFrame:
    return pd.DataFrame(
        [[0.0004, 0.0005], [0.0005, 0.0009]], index=["SPY", "XLK"], columns=["SPY", "XLK"]
    )


def _record(**over) -> RunRecord:
    base: dict[str, object] = {
        "event_id": "e",
        "portfolio_key": "b",
        "sample": 0,
        "as_of": "2023-03-07",
        "model_id": "m",
        "prompt_version": "v11",
        "factor_shocks": {"SPY": -0.2},
        "periphery_shocks": {},
        "selected_event_ids": ["a1", "a2", "a3"],
        "analog_event_returns": {
            "a1": {"SPY": -0.1, "XLK": -0.15},
            "a2": {"SPY": -0.3, "XLK": None},
            "a3": {"SPY": -0.5, "XLK": -0.6},
        },
        "headline_pnl": -0.11,
        "cost_usd": 0.05,
        "error": None,
        "generated_at": "t",
    }
    base.update(over)
    return RunRecord(**base)


def test_score_record_variants():
    exposure = pd.Series({"SPY": 0.4, "XLK": 0.8})
    realized = {"SPY": -0.25, "XLK": -0.35}
    out = score_record(_record(), exposure=exposure, cov=_cov(), realized=realized)
    e = np.array([0.4, 0.8])
    assert out["L0"] == pytest.approx(0.4 * -0.2)
    l1 = complete_shocks(_cov(), {"SPY": -0.2}).shocks.to_numpy()
    assert out["L1"] == pytest.approx(float(e @ l1))
    l2 = complete_shocks(_cov(), {"SPY": -0.3}).shocks.to_numpy()  # analog median of SPY
    assert out["L2"] == pytest.approx(float(e @ l2))
    assert out["L3"] == pytest.approx(0.4 * -0.3 + 0.8 * np.mean([-0.15, -0.6]))
    assert out["full_replay"] == pytest.approx(0.4 * -0.25 + 0.8 * -0.35)
    assert out["L0_headline"] == pytest.approx(-0.11)


def test_score_runs_end_to_end(monkeypatch: pytest.MonkeyPatch):
    rng = np.random.default_rng(2)
    n = 80
    idx = pd.date_range("2021-01-08", periods=n, freq="W-FRI")
    spy = rng.normal(0, 0.02, n)
    factors = pd.DataFrame({"SPY": spy, "XLK": 1.2 * spy + rng.normal(0, 0.01, n)}, index=idx)
    tickers = pd.DataFrame({"T1": factors["XLK"] + rng.normal(0, 0.005, n)}, index=idx)
    book = SimpleNamespace(holdings={"T1": 1.0}, tickers=["T1"])
    monkeypatch.setattr(cal, "get_portfolio", lambda key: book)
    ev = EventInputs(
        event_id="e",
        start_date=date(2023, 3, 8),
        end_date=date(2023, 4, 7),
        factor_returns=factors,
        dropped=[],
        level_changes=pd.DataFrame(index=idx),
        realized={"SPY": -0.25, "XLK": -0.35},
        realized_levels={},
        start_levels={},
    )
    inputs = StudyInputs(
        events=[ev],
        books=[BookInputs("e", "b", tickers, -0.33, None)],
        reference_tnx_level=None,
        reference_date=None,
        regression_spec="s",
        events_version="v",
        factor_universe_version="f",
        weights_as_of="w",
        gathered_at="g",
    )
    records = [
        _record(sample=0, headline_pnl=-0.10),
        _record(sample=1, headline_pnl=-0.14),
        _record(sample=2, error="RuntimeError: x", headline_pnl=None),
    ]
    pairs, summary = score_runs(records, inputs, config=_config())
    assert len(pairs) == 1
    assert pairs[0].n_samples == 2
    assert pairs[0].modeled["L0_headline"] == pytest.approx(-0.12)
    assert pairs[0].headline_spread == pytest.approx(np.std([-0.10, -0.14], ddof=1))
    assert summary.n_failed == 1 and summary.n_pairs_scored == 1
    assert summary.challenger_legacy_half[0]["horizon"] == 21
    text = render_markdown(pairs, summary)
    assert "## Gate G4 (pre-registered)" in text


def test_prewarm_reports_every_unavailable_fetch(monkeypatch: pytest.MonkeyPatch):
    cases = [c for c in load_cases() if c.event_id == "svb-banking-2023"]
    book = SimpleNamespace(
        holdings={"AAA": 0.5, "BBB": 0.5}, tickers=["AAA", "BBB"], benchmark="BMK"
    )
    ends: list[date] = []

    def prices(tickers, *, lookback_weeks, end):
        ends.append(end)
        present = [t for t in tickers if t != "BBB"]
        return pd.DataFrame({t: [1.0, 1.1] for t in present})

    monkeypatch.setattr(cal, "get_portfolio", lambda key: book)
    monkeypatch.setattr(cal, "fetch_weekly_prices", prices)
    monkeypatch.setattr(cal, "convert_weekly_returns_to_usd", lambda frame, end: frame)
    monkeypatch.setattr(cal, "fetch_factor_returns_with_history", lambda **kw: (None, None))
    monkeypatch.setattr(cal.warm_cache, "get_event_returns_matrix", lambda: None)
    monkeypatch.setattr(cal.warm_cache, "get_cached_event_returns_matrix", lambda: None)

    failures = cal.prewarm_market(cases, ["b"], config=_config())
    assert any("BBB" in f for f in failures)
    assert any("event matrix" in f for f in failures)
    assert set(ends) == {cases[0].as_of + timedelta(days=1)}


def test_paired_comparison_is_signed_and_paired():
    pairs = [
        cal.PairScore(
            event_id=f"e{i}",
            portfolio_key="b",
            n_samples=1,
            realized_pnl=0.10 * i,
            modeled={"A": 0.10 * i + 0.01, "B": 0.10 * i + 0.05},
            headline_spread=None,
            shock_count_range=(1, 1),
            cosine_to_realized=None,
            severity_ratio=None,
        )
        for i in range(10)
    ]
    out = cal.paired_comparison(pairs, "A", "B")
    assert out is not None
    assert out["mean_abs_error_diff"] == pytest.approx(-0.04)
    assert out["ci95_high"] < 0.0 and out["share_a_closer"] == 1.0
    assert cal.paired_comparison(pairs[:2], "A", "B") is None
