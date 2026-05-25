"""Live-LLM evaluation tests. Stochastic over news/search drift even with temperature=0.

These are NOT deterministic backtests — they hit real Gemini + Google Search. Use semantic
assertions only (tag membership, ordering, presence-of-citation). Run-to-run output WILL
vary as news headlines drift. See `docs/backtest_results.md` for a dated snapshot.

Gated on `RUN_NETWORK_TESTS=1` so the default test suite stays offline + free.
"""

from __future__ import annotations

import os

import pytest

from app.factors.analogs import load_events
from app.llm.scenario import run_scenario

_NETWORK_REASON = "set RUN_NETWORK_TESTS=1 to enable yfinance/Gemini-backed evals"


@pytest.mark.skipif(not os.environ.get("RUN_NETWORK_TESTS"), reason=_NETWORK_REASON)
def test_pandemic_picks_pandemic_tagged_analog():
    """A pandemic-flavored scenario should select at least one pandemic-tagged analog
    and the run should return at least one citation (grounding fired)."""
    result = run_scenario(
        "Sudden global pandemic resurgence; 30-day lockdown across major economies; "
        "risk-off liquidation across all asset classes.",
        portfolio_key="msci_world",
    )
    registry = load_events()
    tags = {tag for a in result.analogs_selected for tag in registry[a.event_id].tags}
    assert "pandemic" in tags, (
        f"Expected a pandemic-tagged analog. Selected: "
        f"{[a.event_id for a in result.analogs_selected]} (tags={tags})"
    )
    assert result.citations, "Grounded scenarios must produce citations"


@pytest.mark.skipif(not os.environ.get("RUN_NETWORK_TESTS"), reason=_NETWORK_REASON)
def test_banking_stress_hits_xlf_harder_than_spy():
    """Banking-stress scenario: when both XLF and SPY are shocked, XLF should be more
    negative (financials lead the selloff)."""
    result = run_scenario(
        "Several mid-sized US banks fail; deposit flight; Fed liquidity backstop announced.",
        portfolio_key="msci_world",
    )
    xlf = next((fs.shock for fs in result.factor_shocks if fs.factor == "XLF"), None)
    spy = next((fs.shock for fs in result.factor_shocks if fs.factor == "SPY"), None)
    if xlf is None or spy is None:
        pytest.skip(f"LLM did not shock both XLF and SPY this run (xlf={xlf}, spy={spy})")
    assert xlf < spy, f"Expected XLF ({xlf}) more negative than SPY ({spy})"


@pytest.mark.skipif(not os.environ.get("RUN_NETWORK_TESTS"), reason=_NETWORK_REASON)
def test_taiwan_scenario_periphery_includes_semis():
    """A Taiwan crisis scenario against the US tech growth portfolio should produce
    periphery shocks on at least one TSMC-exposed semi name."""
    result = run_scenario(
        "China invades Taiwan; semiconductor supply chain disrupted; export controls tighten.",
        portfolio_key="us_tech_growth",
    )
    periphery_tickers = {ps.ticker for ps in result.periphery_shocks}
    expected_set = {"NVDA", "AMD", "AAPL", "AVGO", "AMAT", "QCOM"}
    assert periphery_tickers & expected_set, (
        f"Expected Taiwan periphery on at least one semi. Got: {periphery_tickers}"
    )
