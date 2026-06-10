"""Currency conversion for weekly RETURN histories (beta-estimation inputs).

`convert_weekly_returns_to_usd` translates local-currency weekly ticker returns
into USD returns by compounding each week with the FX return:

    r_usd = (1 + r_local) * (1 + r_fx) - 1

Used by `run_scenario` / `adjust_scenario_shocks` so non-USD listings (e.g. the
Japan book's `.T` tickers) regress USD returns on the USD-denominated factor
ETFs — betas then absorb FX exposure, and active return vs a USD-quoted
benchmark compares like with like. This is the RETURN-history layer; spot
valuation for mark-to-market lives in `app/data/marking.py`.

GBp (London pence) note: the 1/100 price scale is a constant multiplier, so it
cancels in `pct_change` — pence returns convert with GBPUSD directly, no /100.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from app.data.market import compute_weekly_returns, fetch_weekly_prices
from app.data.market_cache import MarketCacheProtocol
from app.data.marking import (
    MarkingError,
    currency_for_ticker,
    fx_pair_for_currency,
    major_currency,
)


def convert_weekly_returns_to_usd(
    local_returns: pd.DataFrame,
    *,
    end: date | datetime | str | None = None,
    cache: MarketCacheProtocol | None | str = "default",
) -> pd.DataFrame:
    """Convert local-currency weekly returns to USD weekly returns.

    Columns whose quote currency is USD pass through unchanged; when EVERY
    column is USD the input frame is returned as-is with ZERO FX fetches (the
    common case for all-US books). `end` must carry the caller's vintage-correct
    as-of bound (yfinance `end=` is exclusive) so backdated runs stay
    look-ahead-free. Weeks where the FX series has no bar become NaN for that
    column — the beta estimator's per-ticker masks drop them.

    Raises MarkingError (fail-closed) when a needed FX series is entirely
    unavailable: silently regressing local-currency returns would reintroduce
    the currency mismatch this function exists to fix.
    """
    if local_returns.empty:
        return local_returns

    majors_by_ticker = {
        str(t): major_currency(currency_for_ticker(str(t))) for t in local_returns.columns
    }
    needed = sorted({m for m in majors_by_ticker.values() if m != "USD"})
    if not needed:
        return local_returns

    # FX prices start one week before the local window so the first local return
    # row has an FX return bar (compute_weekly_returns drops the first FX row).
    start = local_returns.index.min() - timedelta(days=7)
    fx_returns: dict[str, pd.Series] = {}
    for major in needed:
        symbol, invert = fx_pair_for_currency(major)
        prices = fetch_weekly_prices([symbol], start=start, end=end, cache=cache)
        if symbol not in prices.columns or prices[symbol].dropna().empty:
            affected = sorted(t for t, m in majors_by_ticker.items() if m == major)
            raise MarkingError(
                f"FX series unavailable for {major} ({symbol}); cannot convert "
                f"{affected} weekly returns to USD."
            )
        rate = prices[symbol]
        if invert:
            rate = 1.0 / rate
        fx_returns[major] = compute_weekly_returns(rate.to_frame(name=symbol))[symbol]

    out = local_returns.copy()
    for ticker, major in majors_by_ticker.items():
        if major == "USD":
            continue
        fx_r = fx_returns[major].reindex(out.index)
        out[ticker] = (1.0 + out[ticker]) * (1.0 + fx_r) - 1.0
    return out
