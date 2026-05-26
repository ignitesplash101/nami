"""Tests for end-date-based event filtering (no-look-ahead invariant)."""

from __future__ import annotations

from datetime import date

from app.factors.analogs import (
    HistoricalEvent,
    filter_events_as_of,
    summarize_events,
)


def _event(eid: str, start: date, end: date) -> HistoricalEvent:
    return HistoricalEvent(
        id=eid,
        name=eid.upper(),
        start_date=start,
        end_date=end,
        tags=("pandemic",),
        description=f"test event {eid}",
    )


def test_filter_events_as_of_uses_end_date_not_start_date():
    """An event that started BEFORE the as-of date but ENDED AFTER must be
    excluded — its windowed return fetch would otherwise leak post-as-of data.
    """
    events = {
        "pre": _event("pre", date(2018, 1, 1), date(2018, 6, 1)),
        # In-progress at 2018-12-01: started before, ends after.
        "in_progress": _event("in_progress", date(2018, 10, 1), date(2019, 3, 1)),
        # Future event.
        "future": _event("future", date(2020, 1, 1), date(2020, 4, 1)),
    }
    eligible = filter_events_as_of(events, date(2018, 12, 1))
    assert set(eligible.keys()) == {"pre"}, (
        "Strict end-date filter must exclude both future events AND events still "
        "in progress at the as-of date (those would leak post-as-of data)."
    )


def test_filter_events_as_of_inclusive_boundary():
    """An event ending EXACTLY on the as-of date is eligible."""
    events = {"exact": _event("exact", date(2020, 1, 1), date(2020, 6, 1))}
    eligible = filter_events_as_of(events, date(2020, 6, 1))
    assert "exact" in eligible


def test_filter_events_as_of_excludes_one_day_after():
    """An event ending one day AFTER the as-of date must be excluded."""
    events = {"after": _event("after", date(2020, 1, 1), date(2020, 6, 2))}
    eligible = filter_events_as_of(events, date(2020, 6, 1))
    assert "after" not in eligible


def test_summarize_events_preserves_start_date_ordering():
    events = {
        "b": _event("b", date(2020, 1, 1), date(2020, 1, 2)),
        "a": _event("a", date(2018, 1, 1), date(2018, 1, 2)),
        "c": _event("c", date(2022, 1, 1), date(2022, 1, 2)),
    }
    summary = summarize_events(events)
    assert [s["id"] for s in summary] == ["a", "b", "c"]
