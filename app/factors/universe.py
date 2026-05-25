"""Factor universe — definitions of every factor the regression engine knows about.

Every factor's "return" is `pct_change()` of its weekly closing level (see Factor.description).
For equity ETFs that's the natural percent return. For yield / vol / level indices it's the
percent change of the index level (e.g., VIX 15 -> 22.5 == +0.50; TNX 4.00% -> 4.20% yield is
+0.05 in the yield index, roughly +20 bps in the underlying 10Y rate).
"""

from __future__ import annotations

import functools
import hashlib
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class Factor:
    name: str  # friendly key, no caret (e.g. "VIX")
    ticker: str  # yfinance ticker (e.g. "^VIX")
    group: str  # "market" | "sector" | "style" | "macro"
    description: str  # what this factor is + units of its weekly return


FACTORS: dict[str, Factor] = {
    # ─── Market ────────────────────────────────────────────────
    "SPY": Factor("SPY", "SPY", "market", "S&P 500 ETF; weekly % return."),
    "ACWI": Factor("ACWI", "ACWI", "market", "MSCI All Country World ETF; weekly % return."),
    # ─── Sectors (GICS 11) ────────────────────────────────────
    "XLK": Factor("XLK", "XLK", "sector", "US Technology sector ETF; weekly % return."),
    "XLF": Factor("XLF", "XLF", "sector", "US Financials sector ETF; weekly % return."),
    "XLE": Factor("XLE", "XLE", "sector", "US Energy sector ETF; weekly % return."),
    "XLV": Factor("XLV", "XLV", "sector", "US Health Care sector ETF; weekly % return."),
    "XLI": Factor("XLI", "XLI", "sector", "US Industrials sector ETF; weekly % return."),
    "XLY": Factor("XLY", "XLY", "sector", "US Consumer Discretionary sector ETF; weekly % return."),
    "XLP": Factor("XLP", "XLP", "sector", "US Consumer Staples sector ETF; weekly % return."),
    "XLU": Factor("XLU", "XLU", "sector", "US Utilities sector ETF; weekly % return."),
    "XLB": Factor("XLB", "XLB", "sector", "US Materials sector ETF; weekly % return."),
    "XLRE": Factor("XLRE", "XLRE", "sector", "US Real Estate sector ETF; weekly % return."),
    "XLC": Factor("XLC", "XLC", "sector", "US Communication Services sector ETF; weekly % return."),
    # ─── Style factors (MSCI USA single-factor ETFs) ──────────
    "MTUM": Factor("MTUM", "MTUM", "style", "MSCI USA Momentum factor ETF; weekly % return."),
    "QUAL": Factor("QUAL", "QUAL", "style", "MSCI USA Quality factor ETF; weekly % return."),
    "VLUE": Factor("VLUE", "VLUE", "style", "MSCI USA Value factor ETF; weekly % return."),
    "SIZE": Factor(
        "SIZE", "SIZE", "style", "MSCI USA Size (small-cap) factor ETF; weekly % return."
    ),
    "USMV": Factor(
        "USMV", "USMV", "style", "MSCI USA Minimum Volatility factor ETF; weekly % return."
    ),
    # ─── Macro ────────────────────────────────────────────────
    "TNX": Factor(
        "TNX",
        "^TNX",
        "macro",
        "CBOE 10-Year Treasury Note Yield Index; weekly % change in the yield index level "
        "(e.g., +0.05 ≈ +20bps in 10Y yield from 4.00% to 4.20%).",
    ),
    "DXY": Factor(
        "DXY",
        "DX-Y.NYB",
        "macro",
        "ICE US Dollar Index; weekly % change in dollar strength against a basket of major currencies.",
    ),
    "VIX": Factor(
        "VIX",
        "^VIX",
        "macro",
        "CBOE Volatility Index (S&P 500 implied vol); weekly % change in the VIX level "
        "(e.g., 15 -> 22.5 == +0.50).",
    ),
    "OIL": Factor(
        "OIL",
        "CL=F",
        "macro",
        "WTI Crude Oil front-month futures; weekly % change in the futures price.",
    ),
}


def factor_tickers() -> list[str]:
    """yfinance tickers, in the order they appear in FACTORS."""
    return [f.ticker for f in FACTORS.values()]


def factor_name_by_ticker() -> dict[str, str]:
    """Reverse lookup: yfinance ticker -> friendly name (used to rename DataFrame columns)."""
    return {f.ticker: f.name for f in FACTORS.values()}


def factors_by_group(group: str) -> list[Factor]:
    """All factors in a group ('market' | 'sector' | 'style' | 'macro')."""
    valid = {"market", "sector", "style", "macro"}
    if group not in valid:
        raise ValueError(f"Unknown factor group '{group}'. Valid: {sorted(valid)}")
    return [f for f in FACTORS.values() if f.group == group]


@functools.lru_cache(maxsize=1)
def factor_universe_version() -> str:
    """Short (12-char) hash of the factor universe shape. Used in the scenario cache key
    so any change to FACTORS (added/removed/renamed/retickered) invalidates cached responses.

    Cached for process lifetime — FACTORS is a module-level constant; the hash never
    changes within a process. Saves the JSON+SHA256 round-trip on every scenario.
    """
    payload = json.dumps(
        [(name, f.ticker, f.group) for name, f in sorted(FACTORS.items())],
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
