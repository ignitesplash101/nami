"""Pre-loaded sample portfolios used by the Portfolio tab.

Holdings weights are NOT hard-coded here: they are loaded from the frozen, dated
cap-weight snapshot ``sample_portfolio_weights.json`` (regenerated offline by
``scripts/refresh_sample_weights.py``). Keeping weights in a committed artifact —
rather than scraping at runtime — preserves the ``scenario_cache_key`` /
backdating reproducibility contract. A missing or incomplete snapshot is a hard
error (raised at import) so a partial/stale artifact can never ship silently.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

_WEIGHTS_PATH = Path(__file__).resolve().parent / "sample_portfolio_weights.json"

# Sentinel ticker for a non-market cash sleeve: zero beta, zero return, no
# periphery shock, classified as the "Cash" sector. Excluded from yfinance.
CASH_TICKER = "CASH"


@dataclass(frozen=True)
class Portfolio:
    name: str
    description: str
    holdings: dict[str, float] = field(default_factory=dict)
    benchmark: str | None = None

    def __post_init__(self) -> None:
        total = sum(self.holdings.values())
        if not 0.999 <= total <= 1.001:
            raise ValueError(f"Portfolio '{self.name}' weights sum to {total:.4f}, expected 1.0")

    @property
    def tickers(self) -> list[str]:
        return list(self.holdings.keys())


# name, description (sans as-of suffix), benchmark ticker
_SAMPLE_META: dict[str, tuple[str, str, str]] = {
    "msci_world": (
        "MSCI World (developed-world large-cap proxy)",
        "Developed-market large caps (US + ex-US ADRs), cap-weighted",
        "URTH",
    ),
    "us_tech_growth": (
        "US Tech Growth",
        "FAANG+ and semiconductor large caps, cap-weighted",
        "QQQ",
    ),
    "defensive_mix": (
        "Defensive Mix",
        "Staples, utilities, and healthcare large caps, cap-weighted",
        "SPLV",
    ),
    "japan_equity": (
        "Japan Equity (large caps)",
        "Large Japanese names, cap-weighted. Tickers use the .T suffix for Tokyo",
        "EWJ",
    ),
}


@lru_cache(maxsize=1)
def _load_snapshot() -> dict[str, object]:
    if not _WEIGHTS_PATH.exists():
        raise RuntimeError(
            f"Sample-portfolio weight snapshot missing at {_WEIGHTS_PATH}. "
            "Run `uv run python scripts/refresh_sample_weights.py` to generate it."
        )
    snapshot = json.loads(_WEIGHTS_PATH.read_text(encoding="utf-8"))
    weights = snapshot.get("weights", {})
    missing = [key for key in _SAMPLE_META if not weights.get(key)]
    if missing:
        raise RuntimeError(
            f"Sample-portfolio snapshot is incomplete — no weights for {missing}. "
            "Regenerate with scripts/refresh_sample_weights.py."
        )
    return snapshot


def sample_as_of() -> str:
    """The as-of date stamped on the committed weight snapshot."""
    return str(_load_snapshot().get("as_of", "unknown"))


def ticker_metadata() -> dict[str, dict[str, str]]:
    """ticker -> {sector, country} from the snapshot (CASH classified as Cash)."""
    meta = dict(_load_snapshot().get("ticker_meta", {}))  # type: ignore[arg-type]
    meta[CASH_TICKER] = {"sector": "Cash", "country": "Cash"}
    return meta


@lru_cache(maxsize=1)
def _build_portfolios() -> dict[str, Portfolio]:
    snapshot = _load_snapshot()
    weights: dict[str, dict[str, float]] = snapshot["weights"]  # type: ignore[assignment]
    as_of = sample_as_of()
    portfolios: dict[str, Portfolio] = {}
    for key, (name, description, benchmark) in _SAMPLE_META.items():
        holdings = {t: float(w) for t, w in weights[key].items()}
        total = sum(holdings.values())
        holdings = {t: w / total for t, w in holdings.items()}  # defensive re-normalize
        portfolios[key] = Portfolio(
            name=name,
            description=f"{description} (as of {as_of}).",
            holdings=holdings,
            benchmark=benchmark,
        )
    return portfolios


def get_portfolio(key: str) -> Portfolio:
    portfolios = _build_portfolios()
    if key not in portfolios:
        raise KeyError(f"Unknown sample portfolio '{key}'. Available: {list(portfolios)}")
    return portfolios[key]


def list_portfolios() -> list[tuple[str, str]]:
    return [(key, p.name) for key, p in _build_portfolios().items()]


def sample_benchmark(key: str) -> str | None:
    """Benchmark ticker for a sample portfolio key, or None if unknown."""
    meta = _SAMPLE_META.get(key)
    return meta[2] if meta else None


# Eager module-level mapping (forces the snapshot to load at import — a missing
# or incomplete artifact fails fast rather than at first request).
SAMPLE_PORTFOLIOS: dict[str, Portfolio] = _build_portfolios()
