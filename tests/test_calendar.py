"""Tests for the NYSE trading-calendar helper used by backdated runs."""

from __future__ import annotations

from datetime import date

from app.utils.calendar import is_trading_day, resolve_effective_market_date


def test_weekend_resolves_to_prior_friday():
    # 2024-06-29 is a Saturday.
    assert resolve_effective_market_date(
        date(2024, 6, 29), today_fn=lambda: date(2025, 1, 1)
    ) == date(2024, 6, 28)


def test_sunday_resolves_to_prior_friday():
    # 2024-06-30 is a Sunday.
    assert resolve_effective_market_date(
        date(2024, 6, 30), today_fn=lambda: date(2025, 1, 1)
    ) == date(2024, 6, 28)


def test_christmas_resolves_to_prior_trading_day():
    # 2024-12-25 (Wed) is a market holiday.
    assert resolve_effective_market_date(
        date(2024, 12, 25), today_fn=lambda: date(2025, 6, 1)
    ) == date(2024, 12, 24)


def test_independence_day_resolves_to_july_3():
    assert resolve_effective_market_date(
        date(2024, 7, 4), today_fn=lambda: date(2025, 1, 1)
    ) == date(2024, 7, 3)


def test_current_day_or_future_passes_through():
    assert resolve_effective_market_date(
        date(2025, 6, 15), today_fn=lambda: date(2025, 6, 15)
    ) == date(2025, 6, 15)
    assert resolve_effective_market_date(
        date(2030, 1, 1), today_fn=lambda: date(2025, 6, 15)
    ) == date(2030, 1, 1)


def test_is_trading_day_known_examples():
    assert is_trading_day(date(2024, 6, 28))  # Friday
    assert not is_trading_day(date(2024, 6, 29))  # Saturday
    assert not is_trading_day(date(2024, 12, 25))  # Christmas
    assert is_trading_day(date(2024, 12, 26))  # Day-after, Thursday
