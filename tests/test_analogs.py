"""Unit tests for app.factors.analogs. Tests 1-3 and 5 are pure; test 4 hits yfinance."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from app.factors import analogs
from app.factors.analogs import (
    HistoricalEvent,
    compute_envelope,
    compute_envelope_from_matrix,
    fetch_event_returns,
    fetch_event_returns_matrix,
    load_events,
)


def _write_yaml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "events.yaml"
    p.write_text(content, encoding="utf-8")
    return p


def test_load_events_parses_yaml(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """
events:
  alpha-event:
    name: Alpha Event
    start_date: 2020-01-01
    end_date: 2020-01-10
    tags: [banking]
    description: |
      A test event.
  beta-event:
    name: Beta Event
    start_date: 2021-06-01
    end_date: 2021-06-15
    tags: [pandemic, central-bank]
    description: |
      Another test event.
""",
    )
    events = load_events(p)
    assert set(events.keys()) == {"alpha-event", "beta-event"}
    alpha = events["alpha-event"]
    assert alpha.name == "Alpha Event"
    assert alpha.start_date == date(2020, 1, 1)
    assert alpha.end_date == date(2020, 1, 10)
    assert isinstance(alpha.tags, tuple)
    assert alpha.tags == ("banking",)
    assert "A test event" in alpha.description
    assert events["beta-event"].tags == ("pandemic", "central-bank")


def test_load_events_rejects_invalid_tag(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """
events:
  bad-event:
    name: Bad Event
    start_date: 2020-01-01
    end_date: 2020-01-10
    tags: [fake-tag]
    description: nope
""",
    )
    with pytest.raises(ValueError, match="fake-tag"):
        load_events(p)


def test_load_events_rejects_duplicate_event_id(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """
events:
  dup-event:
    name: First
    start_date: 2020-01-01
    end_date: 2020-01-10
    tags: [banking]
    description: first
  dup-event:
    name: Second
    start_date: 2020-02-01
    end_date: 2020-02-10
    tags: [banking]
    description: second
""",
    )
    with pytest.raises((yaml.constructor.ConstructorError, ValueError), match="duplicate"):
        load_events(p)


@pytest.mark.skipif(
    not os.environ.get("RUN_NETWORK_TESTS"),
    reason="set RUN_NETWORK_TESTS=1 to enable yfinance-backed tests",
)
def test_fetch_event_returns_covid_sanity() -> None:
    event = HistoricalEvent(
        id="covid-crash-2020",
        name="COVID-19 Crash",
        start_date=date(2020, 2, 19),
        end_date=date(2020, 3, 23),
        tags=("pandemic",),
        description="Test COVID window",
    )
    returns = fetch_event_returns(event)

    assert -0.38 <= returns["SPY"] <= -0.28, f"SPY return {returns['SPY']} outside [-0.38, -0.28]"
    assert returns["VIX"] > 2.5, f"VIX return {returns['VIX']} not > 2.5"
    assert returns["TNX"] < -0.30, f"TNX return {returns['TNX']} not < -0.30"
    assert returns["XLF"] < -0.30, f"XLF return {returns['XLF']} not < -0.30"
    assert not pd.isna(returns["XLRE"]), "XLRE should have data (launched 2015)"
    for style in ("MTUM", "QUAL", "VLUE", "SIZE", "USMV"):
        assert not pd.isna(returns[style]), f"{style} should have data (launched 2013)"


def test_compute_envelope_validates_inputs_and_aggregates(monkeypatch) -> None:
    fake_registry = {
        "e1": HistoricalEvent(
            id="e1",
            name="E1",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 1, 10),
            tags=("banking",),
            description="x",
        ),
        "e2": HistoricalEvent(
            id="e2",
            name="E2",
            start_date=date(2021, 1, 1),
            end_date=date(2021, 1, 10),
            tags=("banking",),
            description="x",
        ),
        "e3": HistoricalEvent(
            id="e3",
            name="E3",
            start_date=date(2022, 1, 1),
            end_date=date(2022, 1, 10),
            tags=("banking",),
            description="x",
        ),
    }

    with pytest.raises(ValueError, match="non-empty"):
        compute_envelope([], registry=fake_registry)

    with pytest.raises(ValueError, match="duplicate"):
        compute_envelope(["e1", "e1"], registry=fake_registry)

    with pytest.raises(KeyError, match="unknown"):
        compute_envelope(["e1", "ghost"], registry=fake_registry)

    fake_returns = {
        "e1": pd.Series({"SPY": -0.10, "VIX": 0.40, "XLC": np.nan}, name="e1"),
        "e2": pd.Series({"SPY": -0.20, "VIX": 0.80, "XLC": np.nan}, name="e2"),
        "e3": pd.Series({"SPY": -0.05, "VIX": 0.20, "XLC": 0.30}, name="e3"),
    }

    def _fake_fetch(event: HistoricalEvent) -> pd.Series:
        return fake_returns[event.id]

    monkeypatch.setattr(analogs, "fetch_event_returns", _fake_fetch)

    env = compute_envelope(["e1", "e2", "e3"], registry=fake_registry)

    np.testing.assert_allclose(env.loc["SPY", "mean"], -0.1166666, atol=1e-6)
    np.testing.assert_allclose(env.loc["VIX", "mean"], 0.4666666, atol=1e-6)
    np.testing.assert_allclose(env.loc["XLC", "mean"], 0.30, atol=1e-6)

    assert env.loc["SPY", "count"] == 3
    assert env.loc["VIX", "count"] == 3
    assert env.loc["XLC", "count"] == 1

    assert env.loc["SPY", "p10"] == pytest.approx(-0.180, abs=1e-6)
    assert env.loc["SPY", "p90"] == pytest.approx(-0.060, abs=1e-6)


def test_fetch_event_returns_matrix_preserves_order_and_matches_envelope(monkeypatch) -> None:
    """`compute_envelope` is a wrapper over matrix-fetch + aggregate; callers that
    also need per-event rows use the two pieces directly without a duplicate fetch."""
    fake_registry = {
        "e1": HistoricalEvent(
            id="e1",
            name="E1",
            start_date=date(2020, 1, 1),
            end_date=date(2020, 1, 10),
            tags=("banking",),
            description="x",
        ),
        "e2": HistoricalEvent(
            id="e2",
            name="E2",
            start_date=date(2021, 1, 1),
            end_date=date(2021, 1, 31),
            tags=("banking",),
            description="x",
        ),
    }
    fake_returns = {
        "e1": pd.Series({"SPY": -0.10, "VIX": 0.40, "XLC": np.nan}, name="e1"),
        "e2": pd.Series({"SPY": -0.20, "VIX": 0.80, "XLC": 0.30}, name="e2"),
    }
    monkeypatch.setattr(analogs, "fetch_event_returns", lambda e: fake_returns[e.id])

    matrix = fetch_event_returns_matrix(["e2", "e1"], registry=fake_registry)
    assert list(matrix.index) == ["e2", "e1"], "input order must be preserved"
    assert pd.isna(matrix.loc["e1", "XLC"])
    assert matrix.loc["e2", "SPY"] == pytest.approx(-0.20)

    env_via_matrix = compute_envelope_from_matrix(matrix)
    env_direct = compute_envelope(["e2", "e1"], registry=fake_registry)
    pd.testing.assert_frame_equal(env_via_matrix, env_direct)

    with pytest.raises(ValueError, match="non-empty"):
        fetch_event_returns_matrix([], registry=fake_registry)
    with pytest.raises(ValueError, match="duplicate"):
        fetch_event_returns_matrix(["e1", "e1"], registry=fake_registry)
    with pytest.raises(KeyError, match="unknown"):
        fetch_event_returns_matrix(["ghost"], registry=fake_registry)
