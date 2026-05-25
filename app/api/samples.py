from __future__ import annotations

SAMPLE_SCENARIOS: dict[str, dict[str, str]] = {
    "covid_pandemic": {
        "name": "COVID-like pandemic shock",
        "text": (
            "Sudden global pandemic resurgence; 30-day lockdown across major economies; "
            "risk-off liquidation across all asset classes."
        ),
    },
    "china_tariffs": {
        "name": "China tariff escalation",
        "text": (
            "US announces 60% tariffs on China imports; prolonged trade war; "
            "tech supply-chain disruption; semiconductor names hit hardest."
        ),
    },
    "yen_carry_unwind": {
        "name": "Yen carry trade unwind",
        "text": (
            "BoJ surprise rate hike triggers global yen-funded carry-trade unwind; "
            "sharp JPY appreciation; equities sell off; Japanese exporters down."
        ),
    },
    "banking_stress": {
        "name": "Banking sector stress",
        "text": (
            "Several mid-sized US banks fail in quick succession; deposit flight; "
            "Fed intervenes with emergency liquidity; financials sector under heavy pressure."
        ),
    },
}
