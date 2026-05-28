"""Snapshot the live-LLM eval scenarios for docs/backtest_results.md.

Runs the same 3 scenarios as tests/test_live_evals.py (current-day market_date,
Google Search grounding active) and dumps the full result payload to JSON so the
maintainer can populate the markdown snapshot table.

Cost: ~$0.003 per scenario × 3 = ~$0.009. Cache hits on identical scenario_text
+ portfolio + NYSE day make repeat runs free.

Usage:
  uv run python scripts/snapshot_live_evals.py
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

from app.llm.scenario import run_scenario


@dataclass
class EvalScenario:
    name: str
    scenario_text: str
    portfolio_key: str


SCENARIOS: list[EvalScenario] = [
    EvalScenario(
        name="pandemic_resurgence",
        scenario_text=(
            "Sudden global pandemic resurgence; 30-day lockdown across major economies; "
            "risk-off liquidation across all asset classes."
        ),
        portfolio_key="msci_world",
    ),
    EvalScenario(
        name="banking_stress",
        scenario_text=(
            "Several mid-sized US banks fail; deposit flight; Fed liquidity " "backstop announced."
        ),
        portfolio_key="msci_world",
    ),
    EvalScenario(
        name="taiwan_semis",
        scenario_text=(
            "China invades Taiwan; semiconductor supply chain disrupted; "
            "export controls tighten."
        ),
        portfolio_key="us_tech_growth",
    ),
]


def run_eval(scenario: EvalScenario) -> dict:
    print(f"\n=== {scenario.name} ===")
    print(f"  portfolio: {scenario.portfolio_key}")
    print(f"  prompt: {scenario.scenario_text[:80]}...")

    t0 = time.perf_counter()
    result = run_scenario(scenario.scenario_text, scenario.portfolio_key)
    wall_clock_s = time.perf_counter() - t0

    factor_shocks_sorted = sorted(result.factor_shocks, key=lambda fs: abs(fs.shock), reverse=True)
    top_factor = factor_shocks_sorted[0] if factor_shocks_sorted else None

    # Naive contrib of the top factor to total P&L (the "contrib" column).
    top_factor_contrib = None
    if top_factor is not None:
        top_factor_contrib = result.portfolio_pnl.by_factor_naive.get(top_factor.factor)

    return {
        "name": scenario.name,
        "scenario_text": scenario.scenario_text,
        "portfolio_key": scenario.portfolio_key,
        "portfolio_name": result.portfolio_name,
        "market_date": result.market_date.isoformat(),
        "narrative_mode": result.narrative_mode,
        "total_pnl": result.portfolio_pnl.total_pnl,
        "top_factor_name": top_factor.factor if top_factor else None,
        "top_factor_shock": top_factor.shock if top_factor else None,
        "top_factor_contrib_naive": top_factor_contrib,
        "analogs_selected_ids": [a.event_id for a in result.analogs_selected],
        "citations_count": len(result.citations),
        "factor_shock_count": len(result.factor_shocks),
        "periphery_shock_count": len(result.periphery_shocks),
        "wall_clock_seconds": round(wall_clock_s, 1),
    }


def main() -> None:
    results = []
    for scenario in SCENARIOS:
        try:
            results.append(run_eval(scenario))
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED: {exc}")
            results.append({"name": scenario.name, "error": str(exc)})

    output_path = "scripts/live_evals_snapshot.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nWrote {len(results)} eval(s) to {output_path}")


if __name__ == "__main__":
    main()
