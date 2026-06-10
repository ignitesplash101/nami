"""Factor universe definitions.

The stable factor keys in ``FACTORS`` are model identifiers and must not be
renamed casually. Display labels are separate metadata so the UI can be readable
while cache keys, stored results, and regression columns remain stable.
"""

from __future__ import annotations

import functools
import hashlib
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class Factor:
    name: str  # stable internal key, no caret (e.g. "VIX")
    ticker: str  # yfinance ticker (e.g. "^VIX")
    group: str  # "market" | "sector" | "style" | "macro"
    short_label: str  # compact display label for charts/tables
    display_name: str  # human-readable factor name for the UI/docs
    description: str  # what this factor is + the unit convention for its returns/shocks
    # (horizon-neutral: shocks are episode total moves, betas use weekly returns)


FACTORS: dict[str, Factor] = {
    # Market
    "SPY": Factor(
        "SPY",
        "SPY",
        "market",
        "US large-cap",
        "US large-cap equities",
        "S&P 500 ETF; decimal price return (-0.05 = -5%).",
    ),
    "ACWI": Factor(
        "ACWI",
        "ACWI",
        "market",
        "Global equities",
        "Global equities",
        "MSCI All Country World ETF; decimal price return.",
    ),
    # Sectors
    "XLK": Factor(
        "XLK",
        "XLK",
        "sector",
        "US technology",
        "US technology",
        "US Technology sector ETF; decimal price return.",
    ),
    "XLF": Factor(
        "XLF",
        "XLF",
        "sector",
        "US financials",
        "US financials",
        "US Financials sector ETF; decimal price return.",
    ),
    "XLE": Factor(
        "XLE",
        "XLE",
        "sector",
        "US energy",
        "US energy",
        "US Energy sector ETF; decimal price return.",
    ),
    "XLV": Factor(
        "XLV",
        "XLV",
        "sector",
        "US health care",
        "US health care",
        "US Health Care sector ETF; decimal price return.",
    ),
    "XLI": Factor(
        "XLI",
        "XLI",
        "sector",
        "US industrials",
        "US industrials",
        "US Industrials sector ETF; decimal price return.",
    ),
    "XLY": Factor(
        "XLY",
        "XLY",
        "sector",
        "US discretionary",
        "US consumer discretionary",
        "US Consumer Discretionary sector ETF; decimal price return.",
    ),
    "XLP": Factor(
        "XLP",
        "XLP",
        "sector",
        "US staples",
        "US consumer staples",
        "US Consumer Staples sector ETF; decimal price return.",
    ),
    "XLU": Factor(
        "XLU",
        "XLU",
        "sector",
        "US utilities",
        "US utilities",
        "US Utilities sector ETF; decimal price return.",
    ),
    "XLB": Factor(
        "XLB",
        "XLB",
        "sector",
        "US materials",
        "US materials",
        "US Materials sector ETF; decimal price return.",
    ),
    "XLRE": Factor(
        "XLRE",
        "XLRE",
        "sector",
        "US real estate",
        "US real estate",
        "US Real Estate sector ETF; decimal price return.",
    ),
    "XLC": Factor(
        "XLC",
        "XLC",
        "sector",
        "US comm services",
        "US communication services",
        "US Communication Services sector ETF; decimal price return.",
    ),
    # Styles
    "MTUM": Factor(
        "MTUM",
        "MTUM",
        "style",
        "Momentum",
        "Momentum stocks",
        "MSCI USA Momentum factor ETF; decimal price return.",
    ),
    "QUAL": Factor(
        "QUAL",
        "QUAL",
        "style",
        "Quality",
        "Quality stocks",
        "MSCI USA Quality factor ETF; decimal price return.",
    ),
    "VLUE": Factor(
        "VLUE",
        "VLUE",
        "style",
        "Value",
        "Value stocks",
        "MSCI USA Value factor ETF; decimal price return.",
    ),
    "SIZE": Factor(
        "SIZE",
        "SIZE",
        "style",
        "Small-cap tilt",
        "Small-cap tilt",
        "MSCI USA Size (small-cap) factor ETF; decimal price return.",
    ),
    "USMV": Factor(
        "USMV",
        "USMV",
        "style",
        "Low volatility",
        "Low-volatility stocks",
        "MSCI USA Minimum Volatility factor ETF; decimal price return.",
    ),
    # Macro
    "TNX": Factor(
        "TNX",
        "^TNX",
        "macro",
        "US 10Y yield",
        "US 10Y yield",
        "CBOE 10-Year Treasury Note Yield Index; decimal change in the yield index level "
        "(e.g., +0.05 moves the 10Y yield from 4.00% to about 4.20%).",
    ),
    "DXY": Factor(
        "DXY",
        "DX-Y.NYB",
        "macro",
        "US dollar",
        "US dollar",
        "ICE US Dollar Index; decimal change in the index level (dollar strength "
        "against a basket of major currencies).",
    ),
    "VIX": Factor(
        "VIX",
        "^VIX",
        "macro",
        "Equity volatility",
        "Equity volatility",
        "CBOE Volatility Index (S&P 500 implied vol); decimal change in the VIX level "
        "(e.g., 15 -> 22.5 == +0.50). Level-dependent: the same decimal move means "
        "different vol points at different starting levels.",
    ),
    "OIL": Factor(
        "OIL",
        "CL=F",
        "macro",
        "Oil price",
        "Oil price",
        "WTI Crude Oil front-month futures; decimal change in the futures price.",
    ),
}


def factor_tickers() -> list[str]:
    """yfinance tickers, in the order they appear in FACTORS."""
    return [f.ticker for f in FACTORS.values()]


def factor_name_by_ticker() -> dict[str, str]:
    """Reverse lookup: yfinance ticker -> stable factor key."""
    return {f.ticker: f.name for f in FACTORS.values()}


def factors_by_group(group: str) -> list[Factor]:
    """All factors in a group ('market' | 'sector' | 'style' | 'macro')."""
    valid = {"market", "sector", "style", "macro"}
    if group not in valid:
        raise ValueError(f"Unknown factor group '{group}'. Valid: {sorted(valid)}")
    return [f for f in FACTORS.values() if f.group == group]


def factor_metadata() -> list[dict[str, str]]:
    """Public display metadata for every factor.

    `key` is the stable ID used in API payloads and stored scenario results.
    `ticker` is the yfinance ticker used for market data and auditability.
    """
    return [
        {
            "key": key,
            "ticker": factor.ticker,
            "group": factor.group,
            "short_label": factor.short_label,
            "display_name": factor.display_name,
            "description": factor.description,
        }
        for key, factor in FACTORS.items()
    ]


@functools.lru_cache(maxsize=1)
def factor_universe_version() -> str:
    """Short hash of the factor universe shape used in scenario cache keys.

    Display label edits intentionally do not change this hash; they do not change
    model inputs, regression columns, or market-data tickers. Description edits do
    not change it either, but they DO change the LLM prompt payloads — a
    description change therefore requires a PROMPT_VERSION bump instead.
    """
    payload = json.dumps(
        [(name, f.ticker, f.group) for name, f in sorted(FACTORS.items())],
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
