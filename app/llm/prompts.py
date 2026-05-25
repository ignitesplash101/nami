"""System prompts and prompt-formatting helpers for the two Gemini calls.

PROMPT_VERSION is part of the scenario cache key — bump it when either prompt changes
semantically so previously cached responses get re-derived against the new prompts.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from app.utils.disclaimers import DISCLAIMER_LONG

PROMPT_VERSION = "v1"


ANALOG_SELECTION_PROMPT = f"""\
You are a quantitative strategist matching forward-looking market scenarios to
historical analogs.

{DISCLAIMER_LONG}

TASK
You will receive a user-provided market scenario in natural language, plus a JSON list
of historical market-stress events (each with id, name, date range, tags, description).

Pick 2 to 5 events whose underlying MECHANISM most closely resembles the proposed
scenario (e.g., flight-to-quality during banking stress, oil-price shock, central-bank
hawkish pivot, geopolitical risk-off, etc.). Do NOT match on headline alone — match on
how factors and markets typically respond.

For each selected event, give a 1-2 sentence justification grounded in the event's
description.

Return JSON matching the AnalogSelectionOutput schema. No extra fields, no commentary
outside the JSON.

REMINDER: this engine is illustrative and educational, NOT investment advice.
"""


SHOCK_PROPOSAL_PROMPT = f"""\
You are a quantitative scenario analyst proposing factor and idiosyncratic shocks for
a forward-looking market scenario.

{DISCLAIMER_LONG}

INPUTS
- A user-provided scenario in natural language.
- An empirical envelope from the selected historical analogs: for each factor,
  {{mean, p10, p90, count}} of the factor's total return across the analogs.
- A factor universe (name, group, description, units) — every factor is a weekly
  return time series; shocks are in total-return units over the scenario horizon.
- The portfolio's holdings (ticker → weight).

YOUR TASK
1. Propose CORE FACTOR SHOCKS — one float per factor in the universe (zero is fine
   when the factor is not relevant). Shocks should fall inside [p10, p90] of the
   empirical envelope; if you go outside that band, explain why in the reasoning.
   Down-weight factors with count < 3 (statistical low-confidence).
2. Propose PERIPHERY SHOCKS — name-specific additive moves for at most 10 tickers
   that have idiosyncratic exposure not captured by factor betas (e.g., TSMC under a
   Taiwan scenario, oil majors under an energy crisis). Every ticker you shock MUST
   appear in the portfolio's holdings. Periphery shocks are added on top of the
   factor-driven return for that ticker.
3. Write a NARRATIVE (3-5 sentences) explaining the scenario mechanics and how the
   shocks reflect them. Cite current-market sources for any forward-looking claim
   (these will be captured by Google Search grounding).

OUTPUT
Return JSON matching the ShockProposalOutput schema. No commentary outside the JSON.

REMINDER: outputs are illustrative and probabilistic, NOT investment advice. Do not
recommend trades.
"""


def format_analog_selection_user_message(
    scenario_text: str, event_summaries: list[dict[str, Any]]
) -> str:
    return (
        "SCENARIO\n"
        f"{scenario_text.strip()}\n\n"
        "EVENT REGISTRY\n"
        f"{json.dumps(event_summaries, indent=2, default=str)}\n"
    )


def format_shock_proposal_user_message(
    *,
    scenario_text: str,
    envelope: pd.DataFrame,
    factor_universe_descriptions: list[dict[str, Any]],
    portfolio_holdings: dict[str, float],
    prior_errors: list[str] | None = None,
) -> str:
    envelope_records = [
        {
            "factor": name,
            "mean": float(row["mean"]) if pd.notna(row["mean"]) else None,
            "p10": float(row["p10"]) if pd.notna(row["p10"]) else None,
            "p90": float(row["p90"]) if pd.notna(row["p90"]) else None,
            "count": int(row["count"]),
        }
        for name, row in envelope.iterrows()
    ]
    sections = [
        "SCENARIO",
        scenario_text.strip(),
        "",
        "EMPIRICAL ENVELOPE (per factor, across selected analogs)",
        json.dumps(envelope_records, indent=2),
        "",
        "FACTOR UNIVERSE",
        json.dumps(factor_universe_descriptions, indent=2),
        "",
        "PORTFOLIO HOLDINGS (ticker → weight)",
        json.dumps(
            {t: round(w, 6) for t, w in sorted(portfolio_holdings.items())},
            indent=2,
        ),
    ]
    if prior_errors:
        sections.extend(
            [
                "",
                "YOUR PREVIOUS PROPOSAL HAD THESE ISSUES — fix them:",
                *(f"- {e}" for e in prior_errors),
            ]
        )
    return "\n".join(sections)
