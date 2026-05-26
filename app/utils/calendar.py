"""US/Eastern NYSE trading-calendar helpers for backdated scenario resolution.

For v1 we hand-curate a 5-year window of NYSE full-day closures. When the requested
as-of date is a weekend or a market holiday, we resolve back to the prior trading day.
Today-or-future requests pass through unchanged (live runs).

For longer / pre-2020 / post-2030 coverage, swap in `pandas_market_calendars` later —
not added as a dependency in v1.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

# NYSE full-day closures, 2020-2030. Source: NYSE published calendars.
# Half-days (1pm close) are NOT included — for as-of resolution the daily close
# still occurs and the date is a valid trading day.
NYSE_HOLIDAYS: frozenset[date] = frozenset(
    {
        # 2020
        date(2020, 1, 1),
        date(2020, 1, 20),
        date(2020, 2, 17),
        date(2020, 4, 10),
        date(2020, 5, 25),
        date(2020, 7, 3),
        date(2020, 9, 7),
        date(2020, 11, 26),
        date(2020, 12, 25),
        # 2021
        date(2021, 1, 1),
        date(2021, 1, 18),
        date(2021, 2, 15),
        date(2021, 4, 2),
        date(2021, 5, 31),
        date(2021, 7, 5),
        date(2021, 9, 6),
        date(2021, 11, 25),
        date(2021, 12, 24),
        # 2022
        date(2022, 1, 17),
        date(2022, 2, 21),
        date(2022, 4, 15),
        date(2022, 5, 30),
        date(2022, 6, 20),
        date(2022, 7, 4),
        date(2022, 9, 5),
        date(2022, 11, 24),
        date(2022, 12, 26),
        # 2023
        date(2023, 1, 2),
        date(2023, 1, 16),
        date(2023, 2, 20),
        date(2023, 4, 7),
        date(2023, 5, 29),
        date(2023, 6, 19),
        date(2023, 7, 4),
        date(2023, 9, 4),
        date(2023, 11, 23),
        date(2023, 12, 25),
        # 2024
        date(2024, 1, 1),
        date(2024, 1, 15),
        date(2024, 2, 19),
        date(2024, 3, 29),
        date(2024, 5, 27),
        date(2024, 6, 19),
        date(2024, 7, 4),
        date(2024, 9, 2),
        date(2024, 11, 28),
        date(2024, 12, 25),
        # 2025
        date(2025, 1, 1),
        date(2025, 1, 9),  # National Day of Mourning, Jimmy Carter
        date(2025, 1, 20),
        date(2025, 2, 17),
        date(2025, 4, 18),
        date(2025, 5, 26),
        date(2025, 6, 19),
        date(2025, 7, 4),
        date(2025, 9, 1),
        date(2025, 11, 27),
        date(2025, 12, 25),
        # 2026
        date(2026, 1, 1),
        date(2026, 1, 19),
        date(2026, 2, 16),
        date(2026, 4, 3),
        date(2026, 5, 25),
        date(2026, 6, 19),
        date(2026, 7, 3),
        date(2026, 9, 7),
        date(2026, 11, 26),
        date(2026, 12, 25),
        # 2027
        date(2027, 1, 1),
        date(2027, 1, 18),
        date(2027, 2, 15),
        date(2027, 3, 26),
        date(2027, 5, 31),
        date(2027, 6, 18),
        date(2027, 7, 5),
        date(2027, 9, 6),
        date(2027, 11, 25),
        date(2027, 12, 24),
        # 2028
        date(2028, 1, 17),
        date(2028, 2, 21),
        date(2028, 4, 14),
        date(2028, 5, 29),
        date(2028, 6, 19),
        date(2028, 7, 4),
        date(2028, 9, 4),
        date(2028, 11, 23),
        date(2028, 12, 25),
        # 2029
        date(2029, 1, 1),
        date(2029, 1, 15),
        date(2029, 2, 19),
        date(2029, 3, 30),
        date(2029, 5, 28),
        date(2029, 6, 19),
        date(2029, 7, 4),
        date(2029, 9, 3),
        date(2029, 11, 22),
        date(2029, 12, 25),
        # 2030
        date(2030, 1, 1),
        date(2030, 1, 21),
        date(2030, 2, 18),
        date(2030, 4, 19),
        date(2030, 5, 27),
        date(2030, 6, 19),
        date(2030, 7, 4),
        date(2030, 9, 2),
        date(2030, 11, 28),
        date(2030, 12, 25),
    }
)


def is_trading_day(d: date) -> bool:
    """True when NYSE is open for regular trading on `d` (Mon-Fri, non-holiday)."""
    if d.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    return d not in NYSE_HOLIDAYS


def resolve_effective_market_date(
    requested: date, *, today_fn: Callable[[], date] = date.today
) -> date:
    """Resolve a user-requested as-of date to the last NYSE trading day on or
    before it.

    - Current-day or future requests pass through unchanged (the live-fetch
      path handles whatever yfinance has).
    - Past requests step backward day-by-day until a non-weekend, non-holiday
      date is found. The pre-curated holiday window (2020-2030) covers any
      realistic backdated request; pre-2020 requests just fall through to
      weekend logic (acceptable for v1).
    """
    today = today_fn()
    if requested >= today:
        return requested

    candidate = requested
    while not is_trading_day(candidate):
        candidate -= timedelta(days=1)
    return candidate
