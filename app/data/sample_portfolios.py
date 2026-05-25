"""Pre-loaded sample portfolios used by the Portfolio tab."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Portfolio:
    name: str
    description: str
    holdings: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        total = sum(self.holdings.values())
        if not 0.999 <= total <= 1.001:
            raise ValueError(f"Portfolio '{self.name}' weights sum to {total:.4f}, expected 1.0")

    @property
    def tickers(self) -> list[str]:
        return list(self.holdings.keys())


def _equal_weight(tickers: list[str]) -> dict[str, float]:
    return dict.fromkeys(tickers, 1.0 / len(tickers))


_MSCI_WORLD_APPROX = [
    "AAPL",
    "MSFT",
    "NVDA",
    "GOOGL",
    "AMZN",
    "META",
    "TSLA",
    "AVGO",
    "BRK-B",
    "LLY",
    "JPM",
    "V",
    "UNH",
    "XOM",
    "MA",
    "PG",
    "JNJ",
    "HD",
    "COST",
    "ORCL",
    "WMT",
    "ABBV",
    "BAC",
    "NFLX",
    "KO",
    "PEP",
    "CRM",
    "MRK",
    "TMO",
    "ADBE",
    "CSCO",
    "ABT",
    "PFE",
    "MCD",
    "DIS",
    "ACN",
    "WFC",
    "LIN",
    "AMD",
    "INTC",
    "QCOM",
    "TXN",
    "NKE",
    "PM",
    "CMCSA",
    "IBM",
    "GE",
    "T",
    "RTX",
    "HON",
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

_JAPAN_TOPIX_CORE = [
    "7203.T",  # Toyota
    "9984.T",  # SoftBank Group
    "6758.T",  # Sony
    "8306.T",  # Mitsubishi UFJ
    "6861.T",  # Keyence
    "8035.T",  # Tokyo Electron
    "9433.T",  # KDDI
    "9432.T",  # NTT
    "6501.T",  # Hitachi
    "7267.T",  # Honda
    "8316.T",  # Sumitomo Mitsui Financial
    "6098.T",  # Recruit Holdings
    "4063.T",  # Shin-Etsu Chemical
    "6902.T",  # Denso
    "8058.T",  # Mitsubishi Corp
    "8001.T",  # Itochu
]


SAMPLE_PORTFOLIOS: dict[str, Portfolio] = {
    "msci_world": Portfolio(
        name="MSCI World Approximation",
        description="~50 global large caps, equal-weighted (a rough cap-weighted approximation lives in Phase 2).",
        holdings=_equal_weight(_MSCI_WORLD_APPROX),
    ),
    "us_tech_growth": Portfolio(
        name="US Tech Growth",
        description="FAANG+ and semiconductor large caps, equal-weighted.",
        holdings=_equal_weight(_US_TECH_GROWTH),
    ),
    "defensive_mix": Portfolio(
        name="Defensive Mix",
        description="Staples, utilities, and healthcare large caps, equal-weighted.",
        holdings=_equal_weight(_DEFENSIVE_MIX),
    ),
    "japan_equity": Portfolio(
        name="Japan Equity (TOPIX Core 30 subset)",
        description="Large Japanese names, equal-weighted. Tickers use the .T suffix for Tokyo.",
        holdings=_equal_weight(_JAPAN_TOPIX_CORE),
    ),
}


def get_portfolio(key: str) -> Portfolio:
    if key not in SAMPLE_PORTFOLIOS:
        raise KeyError(f"Unknown sample portfolio '{key}'. Available: {list(SAMPLE_PORTFOLIOS)}")
    return SAMPLE_PORTFOLIOS[key]


def list_portfolios() -> list[tuple[str, str]]:
    return [(key, p.name) for key, p in SAMPLE_PORTFOLIOS.items()]
