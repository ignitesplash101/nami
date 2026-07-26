"""Snapshot the live-LLM eval scenarios for docs/backtest_results.md.

Runs the same 3 scenarios as tests/test_live_evals.py (current-day market_date,
Google Search grounding active) and dumps the full result payload to JSON so the
maintainer can populate the markdown snapshot table.

Cost: ~$0.08 per scenario × 3 = ~$0.25 (gemini-3.6-flash list prices incl. thinking
tokens, 2026-07-22). Cache hits on identical scenario_text + portfolio + NYSE day make
repeat runs free.

Usage:
  uv run python scripts/snapshot_live_evals.py
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

from app.api.main import NAMI_ENGINE_VERSION
from app.config import load_config
from app.factors.analogs import events_version
from app.factors.universe import factor_universe_version
from app.llm.prompts import PROMPT_VERSION
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


def _source_domain(citation) -> str:  # noqa: ANN001 — Citation, avoided for import cycle
    """The PUBLISHER, which is not in the URL.

    Vertex grounding returns every `uri` as a `vertexaisearch.cloud.google.com`
    redirect, so hashing the URL's netloc reports the redirector for 100% of
    citations and tells you nothing. The SDK puts the real domain in `web.title`
    (e.g. "wikipedia.org"), which is what the v11 source hierarchy is about.
    """
    title = (citation.title or "").strip().removeprefix("www.")
    if title:
        return title
    return urlparse(citation.url or "").netloc.removeprefix("www.")


def _provenance() -> dict:
    """Stamp the engine identity onto the snapshot.

    Without this the table is undateable against the code: a reader cannot tell
    which model or prompt produced it, and a stale snapshot reads as current.
    """
    config = load_config()
    return {
        "generated_at": datetime.now(UTC).date().isoformat(),
        "model_id": config.vertex_model_id,
        "vertex_ai_location": config.vertex_ai_location,
        "prompt_version": PROMPT_VERSION,
        "factor_universe_version": factor_universe_version(),
        "events_version": events_version(),
        "nami_engine_version": NAMI_ENGINE_VERSION,
        "llm_temperature": config.llm_temperature,
        "structured_thinking_level": config.structured_thinking_level,
    }


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
        # Domains, not just a count: PROMPT_VERSION v11 added a source-quality
        # hierarchy (official > research > major news > fallback), and WHICH domains
        # come back is the only evidence that it does anything.
        "citation_domains": sorted({_source_domain(c) for c in result.citations}),
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

    provenance = _provenance()
    output_path = "scripts/live_evals_snapshot.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({"provenance": provenance, "evals": results}, f, indent=2, default=str)
    print(f"\nWrote {len(results)} eval(s) to {output_path}")
    print(f"provenance: {json.dumps(provenance)}")


if __name__ == "__main__":
    main()
