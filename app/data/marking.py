"""Mark-to-market valuation: turn share quantities into a USD-marked book.

nami's factor engine is linear in weights, so once we know the portfolio NAV and
the price-derived weights, every dollar figure is just `return_field × NAV`
(computed client-side). This module owns the *marking* step only:

    quantities {ticker: shares}
        ──fetch RAW daily close (auto_adjust=False) ≤ as_of, per instrument──►
        ──fetch as-of FX rates (explicit pairs, inverted as needed) → USD──►
        position_value_usd[t] = shares[t] · raw_close[t] · pence_scale · usd_per_unit[ccy(t)]
        NAV = Σ ;  weights[t] = MV[t] / NAV

It is **fail-closed**: any missing/stale price or FX rate raises, because a
requested valuation must never silently fall back to a percentage-only view.

Currency for v1 is inferred from the Yahoo exchange suffix (sufficient for the
sample universe); the reporting currency is USD. `fast_info.currency` and a
user-selectable base currency are documented follow-ups.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

from app.data.market import fetch_daily_prices
from app.data.market_cache import MarketCacheProtocol
from app.data.sample_portfolios import CASH_TICKER

logger = logging.getLogger(__name__)


class MarkingError(RuntimeError):
    """Raised when a requested mark-to-market valuation cannot be produced —
    a missing/stale price or FX rate. Distinct from generic RuntimeError so the
    API maps it to 503 (valuation data unavailable) and the run **fails closed**
    rather than silently returning a percentage-only result."""


# Bounded fetch windows (calendar days) — enough to clear a long holiday weekend
# without pulling excessive history.
MARK_LOOKBACK_DAYS = 10
FX_LOOKBACK_DAYS = 10
# A mark older than this (calendar days before as_of) is treated as stale /
# delisted / halted and rejected rather than silently valuing on a stale price.
MAX_STALENESS_DAYS = 7

# Yahoo exchange suffix → quote-currency UNIT. "GBp" is London pence (1/100 GBP).
_CCY_BY_SUFFIX: dict[str, str] = {
    "T": "JPY",
    "HK": "HKD",
    "TO": "CAD",
    "SW": "CHF",
    "PA": "EUR",
    "DE": "EUR",
    "AS": "EUR",
    "MI": "EUR",
    "L": "GBp",
}

# Quote units that are minor (sub-) units: unit -> (major currency, price scale to major).
_MINOR_UNIT: dict[str, tuple[str, float]] = {"GBp": ("GBP", 0.01)}

# Explicit Yahoo FX symbols, major currency → (symbol, invert?). We want USD per
# 1 unit of the major currency; `invert` flips a "USD-base" quote (e.g. USDJPY=X
# gives JPY per USD → invert → USD per JPY).
_FX_PAIR: dict[str, tuple[str, bool]] = {
    "JPY": ("USDJPY=X", True),
    "HKD": ("USDHKD=X", True),
    "CAD": ("USDCAD=X", True),
    "CHF": ("USDCHF=X", True),
    "EUR": ("EURUSD=X", False),
    "GBP": ("GBPUSD=X", False),
}


@dataclass(frozen=True)
class MarkResult:
    """A USD-marked book. `weights` sum to 1.0 and feed the unchanged engine;
    everything else is metadata attached to the result for display + reproducibility."""

    nav: float
    weights: dict[str, float]
    position_values: dict[str, float]  # USD market value per ticker
    mark_prices: dict[str, float]  # raw close in the ticker's native quote unit
    price_date_by_ticker: dict[str, str]  # ISO date of the close actually used
    fx_rates: dict[str, float]  # major currency -> USD per unit (includes "USD": 1.0)
    fx_date_by_currency: dict[str, str]  # ISO date of the FX close used
    reporting_currency: str


def currency_for_ticker(ticker: str) -> str:
    """Quote-currency unit for a ticker, inferred from its Yahoo exchange suffix.

    Returns a currency code (e.g. "JPY") or the pence unit "GBp" for London.
    Unknown suffixes default to USD with a warning.
    """
    if "." in ticker:
        suffix = ticker.rsplit(".", 1)[1].upper()
        unit = _CCY_BY_SUFFIX.get(suffix)
        if unit is None:
            logger.warning("Unknown exchange suffix '.%s' for %s; assuming USD.", suffix, ticker)
            return "USD"
        return unit
    return "USD"


def _major_currency(unit: str) -> str:
    return _MINOR_UNIT[unit][0] if unit in _MINOR_UNIT else unit


def fetch_marks(
    tickers: list[str],
    *,
    as_of: date,
    cache: MarketCacheProtocol | None | str = "default",
) -> dict[str, tuple[float, date]]:
    """Last valid RAW close ≤ as_of per ticker, with its date. Fails closed."""
    unique = sorted(set(tickers))
    end = as_of + timedelta(days=1)  # yfinance end= is exclusive
    start = as_of - timedelta(days=MARK_LOOKBACK_DAYS)
    prices = fetch_daily_prices(unique, start=start, end=end, auto_adjust=False, cache=cache)

    out: dict[str, tuple[float, date]] = {}
    for ticker in unique:
        if ticker not in prices.columns:
            raise MarkingError(f"No price data to mark {ticker} as-of {as_of.isoformat()}.")
        col = prices[ticker].dropna()
        if col.empty:
            raise MarkingError(f"No close for {ticker} on or before {as_of.isoformat()}.")
        price_date = col.index[-1].date()
        if (as_of - price_date).days > MAX_STALENESS_DAYS:
            raise MarkingError(
                f"Stale mark for {ticker}: latest close {price_date.isoformat()} is more "
                f"than {MAX_STALENESS_DAYS} days before {as_of.isoformat()}."
            )
        out[ticker] = (float(col.iloc[-1]), price_date)
    return out


def fetch_fx_to_usd(
    currencies: set[str],
    *,
    as_of: date,
    cache: MarketCacheProtocol | None | str = "default",
) -> dict[str, tuple[float, date]]:
    """USD-per-unit FX rate (+ date) for each MAJOR currency. Fails closed."""
    out: dict[str, tuple[float, date]] = {"USD": (1.0, as_of)}
    need = sorted(c for c in currencies if c != "USD")
    if not need:
        return out

    unsupported = [c for c in need if c not in _FX_PAIR]
    if unsupported:
        raise MarkingError(f"No FX pair configured for currencies: {unsupported}.")

    symbols = [_FX_PAIR[c][0] for c in need]
    end = as_of + timedelta(days=1)
    start = as_of - timedelta(days=FX_LOOKBACK_DAYS)
    prices = fetch_daily_prices(symbols, start=start, end=end, auto_adjust=False, cache=cache)

    for ccy in need:
        symbol, invert = _FX_PAIR[ccy]
        if symbol not in prices.columns:
            raise MarkingError(
                f"FX rate unavailable for {ccy} ({symbol}) as-of {as_of.isoformat()}."
            )
        col = prices[symbol].dropna()
        if col.empty:
            raise MarkingError(f"No FX close for {ccy} on or before {as_of.isoformat()}.")
        fx_date = col.index[-1].date()
        if (as_of - fx_date).days > MAX_STALENESS_DAYS:
            raise MarkingError(
                f"Stale FX for {ccy}: latest rate {fx_date.isoformat()} is more than "
                f"{MAX_STALENESS_DAYS} days before {as_of.isoformat()}."
            )
        rate = float(col.iloc[-1])
        if rate <= 0:
            raise MarkingError(f"Non-positive FX rate for {ccy}: {rate}.")
        out[ccy] = (1.0 / rate if invert else rate, fx_date)
    return out


def mark_positions(
    quantities: dict[str, float],
    marks: dict[str, tuple[float, date]],
    fx: dict[str, tuple[float, date]],
    *,
    reporting_currency: str = "USD",
) -> MarkResult:
    """Combine quantities × marks × FX into a USD-marked book. Fails closed."""
    if reporting_currency != "USD":
        raise ValueError(f"v1 supports USD reporting only; got {reporting_currency!r}.")

    position_values: dict[str, float] = {}
    mark_prices: dict[str, float] = {}
    price_dates: dict[str, str] = {}
    used_fx: dict[str, float] = {"USD": 1.0}
    fx_dates: dict[str, str] = {}

    for ticker, qty in quantities.items():
        if ticker not in marks:
            raise MarkingError(f"Missing mark for {ticker}.")
        raw_close, price_date = marks[ticker]
        unit = currency_for_ticker(ticker)
        major, scale = _MINOR_UNIT.get(unit, (unit, 1.0))
        if major not in fx:
            raise MarkingError(f"Missing FX rate for {major} (ticker {ticker}).")
        usd_per_unit, fx_date = fx[major]
        position_values[ticker] = qty * raw_close * scale * usd_per_unit
        mark_prices[ticker] = raw_close
        price_dates[ticker] = price_date.isoformat()
        used_fx[major] = usd_per_unit
        fx_dates[major] = fx_date.isoformat()

    nav = float(sum(position_values.values()))
    if nav <= 0:
        raise ValueError(f"Portfolio NAV must be positive; got {nav}.")

    weights = {ticker: position_values[ticker] / nav for ticker in quantities}
    return MarkResult(
        nav=nav,
        weights=weights,
        position_values=position_values,
        mark_prices=mark_prices,
        price_date_by_ticker=price_dates,
        fx_rates=used_fx,
        fx_date_by_currency=fx_dates,
        reporting_currency=reporting_currency,
    )


def mark_book(
    quantities: dict[str, float],
    *,
    as_of: date,
    reporting_currency: str = "USD",
    cache: MarketCacheProtocol | None | str = "default",
) -> MarkResult:
    """End-to-end: fetch raw marks + as-of FX, then value the book in USD.

    Raises (fail-closed) on any missing/stale price or FX rate.

    A CASH sleeve is a USD amount, NOT a share count: it is never sent to yfinance,
    marks at 1.0, and values to its own quantity (so `value == quantity`).
    """
    market = [t for t in quantities if t != CASH_TICKER]
    marks = fetch_marks(market, as_of=as_of, cache=cache)
    if CASH_TICKER in quantities:
        marks[CASH_TICKER] = (1.0, as_of)
    majors = {_major_currency(currency_for_ticker(t)) for t in market}
    fx = fetch_fx_to_usd(majors, as_of=as_of, cache=cache)
    return mark_positions(quantities, marks, fx, reporting_currency=reporting_currency)
