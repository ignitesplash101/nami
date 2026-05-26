"""Unit tests for the in-memory Firestore double + list-item conversion."""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.api.schemas import (
    AnalogEventResponse,
    PortfolioSnapshotRecord,
    SavedPortfolioRecord,
    SavedScenarioRecord,
    ScenarioReproducibility,
)
from app.data.firestore_store import InMemoryFirestoreStore
from app.llm.schemas import (
    AnalogSelection,
    Citation,
    FactorShock,
    PortfolioPnL,
    ScenarioResult,
)


def _fake_result() -> ScenarioResult:
    return ScenarioResult(
        scenario_text="x",
        market_date=date(2024, 6, 28),
        portfolio_key="us_tech_growth",
        portfolio_name="US Tech Growth",
        portfolio_holdings={"AAPL": 0.6, "MSFT": 0.4},
        analogs_selected=[AnalogSelection(event_id="evt", why_relevant="r")],
        factor_shocks=[FactorShock(factor="SPY", shock=-0.05, reasoning="z")],
        periphery_shocks=[],
        narrative="n",
        citations=[Citation(url="https://e.com", title="e")],
        factor_envelope={},
        portfolio_pnl=PortfolioPnL(
            total_pnl=-0.01,
            by_factor_naive={"SPY": -0.01},
            by_ticker_factor={"AAPL": -0.01, "MSFT": 0.0},
            by_ticker_periphery={"AAPL": 0.0, "MSFT": 0.0},
            by_ticker_total={"AAPL": -0.01, "MSFT": 0.0},
        ),
        requested_as_of_date=date(2024, 6, 28),
        narrative_mode="analog_only",
        selected_event_ids=["evt"],
    )


def _fake_record() -> SavedScenarioRecord:
    return SavedScenarioRecord(
        id="will_be_overwritten",
        name="Pandemic stress 2024-06-28",
        tags=["pandemic", "backdated"],
        notes="Q2 sign-off",
        created_at=datetime.now(UTC),
        owner_label="rs",
        scenario_text="x",
        portfolio_holdings={"AAPL": 0.6, "MSFT": 0.4},
        portfolio_key="us_tech_growth",
        portfolio_name="US Tech Growth",
        analog_events_snapshot={
            "evt": AnalogEventResponse(
                event_id="evt",
                name="Test event",
                start_date="2018-01-01",
                end_date="2018-06-01",
                tags=["pandemic"],
                description="d",
            )
        },
        result=_fake_result(),
        reproducibility=ScenarioReproducibility(
            model_id="gemini-test",
            prompt_version="v6",
            factor_universe_version="abc",
            events_version="def",
            requested_as_of_date=date(2024, 6, 28),
            effective_as_of_date=date(2024, 6, 28),
            narrative_mode="analog_only",
            beta_lookback_weeks=156,
            ridge_alpha=0.1,
            selected_event_ids=["evt"],
            portfolio_holdings={"AAPL": 0.6, "MSFT": 0.4},
            portfolio_key="us_tech_growth",
            nami_engine_version="test",
        ),
    )


def test_save_and_get_scenario_roundtrips_inline_fields():
    store = InMemoryFirestoreStore()
    sid = store.save_scenario(_fake_record())
    rec = store.get_scenario(sid)
    assert rec is not None
    # Critical invariants from the plan: inline holdings + analog events.
    assert rec.portfolio_holdings == {"AAPL": 0.6, "MSFT": 0.4}
    assert "evt" in rec.analog_events_snapshot
    # Reproducibility metadata preserved.
    assert rec.reproducibility.prompt_version == "v6"
    assert rec.reproducibility.narrative_mode == "analog_only"


def test_list_scenarios_filters_by_tag_and_orders_by_recent():
    store = InMemoryFirestoreStore()
    older = _fake_record().model_copy(
        update={"name": "old", "created_at": datetime(2024, 1, 1, tzinfo=UTC), "tags": ["a"]}
    )
    newer = _fake_record().model_copy(
        update={"name": "new", "created_at": datetime(2025, 1, 1, tzinfo=UTC), "tags": ["b"]}
    )
    store.save_scenario(older)
    store.save_scenario(newer)

    all_items = store.list_scenarios()
    assert [i.name for i in all_items] == ["new", "old"]

    only_a = store.list_scenarios(tag="a")
    assert [i.name for i in only_a] == ["old"]


def test_delete_scenario_removes_it():
    store = InMemoryFirestoreStore()
    sid = store.save_scenario(_fake_record())
    assert store.get_scenario(sid) is not None
    store.delete_scenario(sid)
    assert store.get_scenario(sid) is None


def test_portfolio_snapshot_lifecycle():
    store = InMemoryFirestoreStore()
    pid = store.save_portfolio(
        SavedPortfolioRecord(
            id="pending",
            name="Active book",
            description="My main book",
            created_at=datetime.now(UTC),
            owner_label="rs",
        )
    )
    sid = store.save_snapshot(
        pid,
        PortfolioSnapshotRecord(
            id="pending",
            portfolio_id=pid,
            as_of_date=date(2024, 6, 28),
            holdings={"AAPL": 1.0},
            notes="Post-rebalance",
            created_at=datetime.now(UTC),
        ),
    )
    snap = store.get_snapshot(pid, sid)
    assert snap is not None
    assert snap.holdings == {"AAPL": 1.0}
    assert snap.as_of_date == date(2024, 6, 28)
    assert snap.portfolio_id == pid

    # Listing returns the snapshot.
    snaps = store.list_snapshots(pid)
    assert len(snaps) == 1
    assert snaps[0].id == sid
