"""Offline refresher for the sample-portfolio weight snapshot.

Run this by hand to regenerate ``app/data/sample_portfolio_weights.json`` — the
frozen, dated cap-weight snapshot the app ships. The runtime NEVER scrapes; it
only reads the committed JSON, which keeps the ``scenario_cache_key`` /
backdating reproducibility contract intact (drifting weights would silently
change P&L).

    uv run python scripts/refresh_sample_weights.py

Sourcing
--------
Weights are **cap-weighted** per portfolio: ``weight_i = marketCap_i / Σ marketCap``.
Market cap, sector, and country all come from one yfinance ``.info`` call per
ticker. Cap-weighting is the "rough cap-weighted approximation" the codebase
always anticipated for the sample books — a large step up from equal-weight.

Issuer holdings CSVs (iShares URTH/IVV/EWJ, Invesco QQQ/SPLV) carry the exact
published index weights and are the *preferred* source, but their download
endpoints serve an HTML SPA shell to non-browser clients, so they are not
fetchable from a headless script in this environment. The ``sources`` field in
the emitted JSON records which source actually produced each book's weights, so
a future run from an environment that can reach the issuer CSVs can upgrade the
snapshot transparently.

Currency safety
---------------
Cap ratios are only meaningful within a single quote currency. Each portfolio is
asserted single-currency before weighting:
  * the US + ex-US-ADR ``msci_world`` book is entirely USD-quoted (ADRs report in
    USD), and
  * ``japan_equity`` is entirely JPY-quoted.
A mixed-currency book raises rather than silently summing across currencies.

Every ticker MUST resolve to a finite, positive market cap or the run raises —
honoring the repo invariant "data layers silently drop tickers; validate set
membership and raise loudly".
"""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

import yfinance as yf

# Curated compositions. msci_world is rebuilt as a developed-world large-cap
# proxy using US-listed lines (US names + ex-US developed ADRs) so the label
# matches the holdings and cap-weighting stays in one currency (USD).
_MSCI_WORLD = [
    # US mega/large caps
    "AAPL",
    "MSFT",
    "NVDA",
    "GOOGL",
    "AMZN",
    "META",
    "AVGO",
    "TSLA",
    "BRK-B",
    "LLY",
    "JPM",
    "V",
    "UNH",
    "XOM",
    "MA",
    "JNJ",
    "PG",
    "HD",
    "COST",
    "ORCL",
    "WMT",
    "ABBV",
    "BAC",
    "NFLX",
    "KO",
    "CRM",
    "MRK",
    "TMO",
    "ADBE",
    "CSCO",
    "ACN",
    "MCD",
    "WFC",
    "ABT",
    "AMD",
    "PEP",
    # ex-US developed-market ADRs (all USD-quoted)
    "ASML",
    "SAP",
    "NVO",
    "NVS",
    "TM",
    "SONY",
    "AZN",
    "SHEL",
    "UL",
    "TTE",
    "HSBC",
    "RY",
    "MUFG",
    "BHP",
]

_US_TECH_GROWTH = [
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "META",
    "NVDA",
    "TSLA",
    "NFLX",
    "AVGO",
    "AMD",
    "CRM",
    "ORCL",
    "ADBE",
    "INTC",
    "QCOM",
    "CSCO",
    "TXN",
    "AMAT",
]

_DEFENSIVE_MIX = [
    "PG",
    "KO",
    "PEP",
    "WMT",
    "COST",
    "MDLZ",
    "CL",
    "NEE",
    "DUK",
    "SO",
    "AEP",
    "JNJ",
    "UNH",
    "LLY",
    "PFE",
    "ABT",
    "MRK",
]

_JAPAN_EQUITY = [
    "7203.T",
    "9984.T",
    "6758.T",
    "8306.T",
    "6861.T",
    "8035.T",
    "9433.T",
    "9432.T",
    "6501.T",
    "7267.T",
    "8316.T",
    "6098.T",
    "4063.T",
    "6902.T",
    "8058.T",
    "8001.T",
]

PORTFOLIOS: dict[str, list[str]] = {
    "msci_world": _MSCI_WORLD,
    "us_tech_growth": _US_TECH_GROWTH,
    "defensive_mix": _DEFENSIVE_MIX,
    "japan_equity": _JAPAN_EQUITY,
}

_OUTPUT_PATH = (
    Path(__file__).resolve().parents[1] / "app" / "data" / "sample_portfolio_weights.json"
)
_MAX_RETRIES = 3


def _fetch_info(ticker: str) -> dict[str, object]:
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            info = yf.Ticker(ticker).info
            cap = info.get("marketCap")
            if cap is None or not isinstance(cap, (int, float)) or cap <= 0:
                raise ValueError(f"{ticker}: missing/non-positive marketCap ({cap!r})")
            return {
                "market_cap": float(cap),
                "currency": str(info.get("currency") or "").upper(),
                "sector": str(info.get("sector") or "Unknown"),
                "country": str(info.get("country") or "Unknown"),
            }
        except Exception as exc:  # noqa: BLE001 — retry then raise loudly
            last_exc = exc
            time.sleep(1.0 + attempt)
    raise RuntimeError(
        f"Failed to fetch market cap for {ticker!r} after {_MAX_RETRIES} tries"
    ) from last_exc


def build_snapshot() -> dict[str, object]:
    weights: dict[str, dict[str, float]] = {}
    ticker_meta: dict[str, dict[str, str]] = {}

    for key, tickers in PORTFOLIOS.items():
        print(f"[{key}] fetching {len(tickers)} tickers ...")
        infos: dict[str, dict[str, object]] = {}
        for ticker in tickers:
            infos[ticker] = _fetch_info(ticker)
            time.sleep(0.3)

        currencies = {str(i["currency"]) for i in infos.values()}
        if len(currencies) != 1:
            raise RuntimeError(
                f"Portfolio {key!r} mixes quote currencies {sorted(currencies)}; "
                "cap-weighting across currencies is invalid."
            )

        total_cap = sum(float(i["market_cap"]) for i in infos.values())
        raw = {t: float(infos[t]["market_cap"]) / total_cap for t in tickers}
        norm = sum(raw.values())
        weights[key] = {t: w / norm for t, w in raw.items()}

        for ticker, info in infos.items():
            ticker_meta[ticker] = {
                "sector": str(info["sector"]),
                "country": str(info["country"]),
            }

    return {
        "as_of": date.today().isoformat(),
        "method": "cap_weighted",
        "sources": dict.fromkeys(PORTFOLIOS, "yfinance_marketcap"),
        "weights": weights,
        "ticker_meta": ticker_meta,
    }


def main() -> None:
    snapshot = build_snapshot()
    _OUTPUT_PATH.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\nWrote {_OUTPUT_PATH} (as_of={snapshot['as_of']})")
    for key, w in snapshot["weights"].items():
        top = sorted(w.items(), key=lambda kv: kv[1], reverse=True)[:3]
        top_str = ", ".join(f"{t} {wt:.1%}" for t, wt in top)
        print(f"  {key:16} {len(w):>3} names · top: {top_str}")


if __name__ == "__main__":
    main()
