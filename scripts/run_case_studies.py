"""Reproduce the 3 backdated retrospective case studies in docs/backdated-case-studies.md.

For each case (pre-COVID, pre-2022-tightening, pre-SVB):
  1. Run a backdated scenario via the existing pipeline (Gemini + analog matcher).
  2. Compute the actual realized P&L over the analog window using yfinance on the same
     portfolio holdings, so the doc reports predicted-vs-actual side by side.

Output: writes scripts/case_studies_output.json, which the maintainer pastes into
docs/backdated-case-studies.md. Re-run any time to refresh; cache hits make it cheap.

Usage:
  uv run python scripts/run_case_studies.py [--case covid|tightening|svb|all]
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import date

from app.data.market import fetch_daily_prices
from app.data.sample_portfolios import get_portfolio
from app.factors.analogs import filter_events_as_of, load_events
from app.llm.scenario import run_scenario


@dataclass
class Case:
    key: str
    title: str
    as_of: date
    realized_end: date
    portfolio_key: str
    prompt: str
    leakage_notes: str


CASES: list[Case] = [
    Case(
        key="covid",
        title="2020 demand-shock crash",
        as_of=date(2020, 2, 26),
        realized_end=date(2020, 3, 23),
        portfolio_key="msci_world",
        prompt=(
            "A major exogenous shock to global travel and supply chains forces a "
            "synchronous recession scare; equity markets repricing happens over "
            "weeks not months, with cyclicals and travel-exposed names leading "
            "the drawdown."
        ),
        leakage_notes=(
            "Post-2020 readers cannot un-know COVID, and Gemini knows COVID "
            "happened. The prompt avoids 'pandemic' and 'virus' but the "
            "mechanism is still recognizable. The selected analogs and the "
            "structural shock magnitudes are the cleaner signal; the narrative "
            "should be treated as illustrative."
        ),
    ),
    Case(
        key="tightening",
        title="2022 hawkish-pivot regime",
        as_of=date(2021, 12, 31),
        realized_end=date(2022, 6, 30),
        portfolio_key="us_tech_growth",
        prompt=(
            "Persistent above-target core inflation forces developed-market "
            "central banks into a sustained tightening cycle over the next 12 "
            "months; duration-sensitive growth equities derate sharply, "
            "defensives and value relatively spared."
        ),
        leakage_notes=(
            "Less acute leakage than the 2020 case — 'above-target inflation' "
            "was already a 2021 narrative — but the trajectory framing "
            "('sustained tightening cycle') pre-loads what the LLM should pick "
            "as analogs. The Taper Tantrum 2013 + early-2018-volatility analogs "
            "are the realistic pre-2022 reference set."
        ),
    ),
    Case(
        key="svb",
        title="2023 regional-banking stress",
        as_of=date(2023, 3, 8),
        realized_end=date(2023, 5, 8),
        portfolio_key="defensive_mix",
        prompt=(
            "Sudden loss of depositor confidence in select mid-size lenders "
            "triggers deposit withdrawals and forced asset sales; large "
            "diversified banks relatively spared, regional bank index leads "
            "losses."
        ),
        leakage_notes=(
            "Most leaky of the three — the prompt reads as the SVB postmortem "
            "written before the fact. The defensive_mix portfolio has minimal "
            "bank exposure, so this case is closer to 'does the engine "
            "correctly identify that defensives ride out a banking stress' "
            "than to 'does it predict the banking stress'."
        ),
    ),
]


def realized_portfolio_pnl(
    portfolio_key: str, start: date, end: date
) -> tuple[float, dict[str, float]]:
    """Compute (weighted return, per-ticker return) over [start, end] inclusive
    using yfinance daily prices. Add +1d to `end` because yfinance is exclusive."""
    from datetime import timedelta

    portfolio = get_portfolio(portfolio_key)
    prices = fetch_daily_prices(
        portfolio.tickers, start=start, end=end + timedelta(days=1), cache=None
    )
    if prices.empty:
        raise RuntimeError(f"No prices fetched for {portfolio_key} [{start}, {end}]")

    first_row = prices.iloc[0]
    last_row = prices.iloc[-1]
    per_ticker_return: dict[str, float] = {}
    weighted = 0.0
    for ticker, weight in portfolio.holdings.items():
        if ticker not in prices.columns:
            continue
        p0 = float(first_row[ticker])
        p1 = float(last_row[ticker])
        if p0 == 0 or p0 != p0:  # NaN check
            continue
        ret = (p1 / p0) - 1.0
        per_ticker_return[ticker] = ret
        weighted += weight * ret
    return weighted, per_ticker_return


def run_case(case: Case) -> dict:
    print(f"\n=== {case.key}: {case.title} ===")
    print(f"  as-of: {case.as_of.isoformat()}  portfolio: {case.portfolio_key}")
    print(f"  prompt: {case.prompt[:80]}...")

    # Pre-compute eligible analog set so we can report it independently of LLM choice.
    events_registry = load_events()
    eligible = filter_events_as_of(events_registry, case.as_of)

    # Run the full backdated pipeline.
    result = run_scenario(case.prompt, case.portfolio_key, market_date=case.as_of)

    # Predicted top factor by absolute shock magnitude.
    factor_shocks_sorted = sorted(result.factor_shocks, key=lambda fs: abs(fs.shock), reverse=True)
    top_factor = factor_shocks_sorted[0] if factor_shocks_sorted else None

    # Compute realized P&L over the same window with the same portfolio.
    realized_pnl, per_ticker = realized_portfolio_pnl(
        case.portfolio_key, case.as_of, case.realized_end
    )

    return {
        "case_key": case.key,
        "title": case.title,
        "as_of_requested": case.as_of.isoformat(),
        "as_of_effective": result.market_date.isoformat(),
        "realized_window_end": case.realized_end.isoformat(),
        "portfolio_key": case.portfolio_key,
        "portfolio_name": result.portfolio_name,
        "prompt": case.prompt,
        "leakage_notes": case.leakage_notes,
        "narrative_mode": result.narrative_mode,
        "eligible_analog_count": len(eligible),
        "eligible_analog_ids": sorted(eligible.keys()),
        "selected_analog_ids": [a.event_id for a in result.analogs_selected],
        "selected_analog_justifications": [
            {"event_id": a.event_id, "why_relevant": a.why_relevant}
            for a in result.analogs_selected
        ],
        "narrative": result.narrative,
        "predicted_total_pnl_naive": result.portfolio_pnl.total_pnl,
        "predicted_by_factor_naive": dict(result.portfolio_pnl.by_factor_naive),
        "predicted_by_factor_conditional_shapley_explicit": (
            dict(result.portfolio_pnl.by_factor_conditional_shapley_explicit)
            if result.portfolio_pnl.by_factor_conditional_shapley_explicit
            else None
        ),
        "predicted_top_factor": (
            {
                "factor": top_factor.factor,
                "shock": top_factor.shock,
                "reasoning": top_factor.reasoning,
            }
            if top_factor
            else None
        ),
        "predicted_periphery_shocks": [
            {"ticker": ps.ticker, "shock": ps.shock, "reasoning": ps.reasoning}
            for ps in result.periphery_shocks
        ],
        "realized_total_pnl": realized_pnl,
        "realized_top_ticker_winner": (
            max(per_ticker.items(), key=lambda x: x[1]) if per_ticker else None
        ),
        "realized_top_ticker_loser": (
            min(per_ticker.items(), key=lambda x: x[1]) if per_ticker else None
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", default="all", choices=["covid", "tightening", "svb", "all"])
    parser.add_argument(
        "--output", default="scripts/case_studies_output.json", help="JSON output path"
    )
    args = parser.parse_args()

    cases_to_run = CASES if args.case == "all" else [c for c in CASES if c.key == args.case]

    results = []
    for case in cases_to_run:
        try:
            results.append(run_case(case))
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED: {exc}")
            results.append({"case_key": case.key, "error": str(exc), **asdict(case)})

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\nWrote {len(results)} case(s) to {args.output}")


if __name__ == "__main__":
    main()
