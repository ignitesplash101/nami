"""Prompt-contract pins: the shock-semantics sentences the pipeline relies on.

Mirrors tests/test_validation.py's style of pinning behavioral contracts — if
someone rewords the units/horizon contract or resurrects the reasoning-based
envelope escape hatch, these fail long before a live eval would catch it.
"""

from __future__ import annotations

import json

import pandas as pd

from app.factors.universe import factor_metadata
from app.llm.prompts import (
    ANALOG_GROUNDED_NARRATIVE_PROMPT,
    GROUNDED_NARRATIVE_PROMPT,
    PROMPT_VERSION,
    SHOCK_EDIT_PROMPT,
    SHOCK_EXTRACTION_PROMPT,
    format_shock_extraction_user_message,
)


def _flat(text: str) -> str:
    """Collapse all whitespace so contract pins are insensitive to line wrapping."""
    return " ".join(text.split())


def test_shock_extraction_prompt_defines_units_and_horizon():
    flat = _flat(SHOCK_EXTRACTION_PROMPT)
    assert "CUMULATIVE TOTAL move" in flat
    assert "NOT a weekly or daily return" in flat


def test_shock_extraction_prompt_has_no_reasoning_escape_hatch():
    # Rule 4 must state the validator's actual blocking behavior; the old
    # "unless the reasoning explicitly explains why" promise never existed in
    # code (the validator deliberately never reads `reasoning`).
    flat = _flat(SHOCK_EXTRACTION_PROMPT)
    assert "cannot authorize an out-of-band shock" in flat
    assert "unless the reasoning" not in flat


def test_edit_and_analog_prompts_carry_units_contract():
    assert "cumulative total moves over the stress episode" in _flat(SHOCK_EDIT_PROMPT)
    assert "TOTAL returns over each analog's full event window" in _flat(
        ANALOG_GROUNDED_NARRATIVE_PROMPT
    )


def test_grounded_narrative_prioritizes_high_quality_sources():
    flat = _flat(GROUNDED_NARRATIVE_PROMPT).lower()
    assert PROMPT_VERSION == "v11"
    assert "government" in flat
    assert "central-bank" in flat
    assert "regulator" in flat
    assert "exchange" in flat
    assert "peer-reviewed" in flat
    assert "working papers" in flat
    assert "institutional research" in flat
    assert "major financial" in flat
    assert "broker marketing" in flat
    assert "crypto sites" in flat
    assert "seo" in flat
    assert "wikipedia" in flat
    assert "last-resort evidence" in flat
    assert "search again" in flat
    assert "not a domain allowlist" in flat


def test_factor_descriptions_are_horizon_neutral():
    # The same descriptions feed the LLM payload that is bounded by event-window
    # envelopes — "weekly % return" wording would reintroduce the mixed-horizon
    # contradiction the v9 contract removed.
    payload = json.dumps(factor_metadata())
    assert "weekly % return" not in payload


def _envelope() -> pd.DataFrame:
    return pd.DataFrame(
        {"mean": [-0.1], "p10": [-0.2], "p90": [-0.05], "count": [3]},
        index=["SPY"],
    )


def test_extraction_message_includes_per_event_section_when_supplied():
    records = [
        {
            "event_id": "covid-crash-2020",
            "window_calendar_days": 33,
            "factor_returns": {"SPY": -0.3402, "XLC": None},
        }
    ]
    msg = format_shock_extraction_user_message(
        narrative="n",
        envelope=_envelope(),
        factor_universe_descriptions=[],
        portfolio_holdings={"AAPL": 1.0},
        per_event_returns=records,
    )
    assert "PER-EVENT FACTOR RETURNS" in msg
    assert "covid-crash-2020" in msg
    assert '"window_calendar_days": 33' in msg

    without = format_shock_extraction_user_message(
        narrative="n",
        envelope=_envelope(),
        factor_universe_descriptions=[],
        portfolio_holdings={"AAPL": 1.0},
    )
    assert "PER-EVENT FACTOR RETURNS" not in without
