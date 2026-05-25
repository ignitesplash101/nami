"""System prompts and prompt-formatting helpers for Gemini calls.

PROMPT_VERSION is part of the scenario cache key. Bump it when prompt semantics
change so cached responses are re-derived against the new pipeline.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from app.utils.disclaimers import DISCLAIMER_LONG

PROMPT_VERSION = "v2"


ANALOG_SELECTION_PROMPT = f"""\
You are a quantitative strategist matching forward-looking market scenarios to
historical analogs.

{DISCLAIMER_LONG}

TASK
You will receive a user-provided market scenario in natural language, plus a JSON list
of historical market-stress events (each with id, name, date range, tags, description).

Pick 2 to 5 events whose underlying mechanism most closely resembles the proposed
scenario. Match on how factors and markets typically respond, not on headline alone.

For each selected event, give a 1-2 sentence justification grounded in the event's
description.

Return JSON matching the AnalogSelectionOutput schema. No extra fields, no commentary
outside the JSON.

REMINDER: this engine is illustrative and educational, not investment advice.
"""


GROUNDED_NARRATIVE_PROMPT = f"""\
You are a quantitative scenario analyst writing the current-market evidence layer for
an equity portfolio scenario engine.

{DISCLAIMER_LONG}

You MUST use the Google Search tool before writing. The response is rejected when it
does not return grounding metadata.

Write a 3-5 sentence forward-looking narrative explaining the scenario mechanism and
likely market impact. Ground the narrative in recent, real market news relevant to the
user's scenario. Mention concrete dates, reported market moves, policy actions,
earnings/news items, or headlines when they are relevant.

Do not propose numeric factor shocks in this step. Do not recommend trades. Output
plain text only: no JSON, no markdown headers, no bullet list.
"""


SHOCK_EXTRACTION_PROMPT = f"""\
You are a quantitative scenario analyst extracting structured factor and periphery
shocks from an already grounded market narrative.

{DISCLAIMER_LONG}

The narrative was generated upstream with Google Search grounding. Your job is purely
to translate that narrative into numeric shocks using the empirical envelope, factor
universe, and portfolio holdings provided by the user message.

RULES
1. Output JSON matching the ShockProposalOutput schema. No extra fields.
2. Copy the grounded narrative into the `narrative` field exactly as provided.
3. Do not introduce new current-market claims beyond the narrative.
4. Factor shocks should stay inside [p10, p90] for each factor unless the reasoning
   explicitly explains why the scenario is outside the analog envelope.
5. Down-weight factors with count < 3.
6. Periphery shocks may only reference tickers in the provided portfolio holdings.
7. Outputs are illustrative and probabilistic, not investment advice.
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


def format_grounded_narrative_user_message(
    *,
    scenario_text: str,
    envelope: pd.DataFrame,
    factor_universe_descriptions: list[dict[str, Any]],
    portfolio_holdings: dict[str, float],
) -> str:
    return "\n".join(
        [
            "SCENARIO",
            scenario_text.strip(),
            "",
            "EMPIRICAL ENVELOPE",
            json.dumps(_envelope_records(envelope), indent=2),
            "",
            "FACTOR UNIVERSE",
            json.dumps(factor_universe_descriptions, indent=2),
            "",
            "PORTFOLIO HOLDINGS (ticker -> weight)",
            json.dumps(_rounded_holdings(portfolio_holdings), indent=2),
            "",
            "INSTRUCTION",
            "Use Google Search to ground a concise narrative in recent market news.",
        ]
    )


def format_shock_extraction_user_message(
    *,
    narrative: str,
    envelope: pd.DataFrame,
    factor_universe_descriptions: list[dict[str, Any]],
    portfolio_holdings: dict[str, float],
    prior_errors: list[str] | None = None,
) -> str:
    sections = [
        "GROUNDED NARRATIVE",
        narrative.strip(),
        "",
        "EMPIRICAL ENVELOPE (per factor, across selected analogs)",
        json.dumps(_envelope_records(envelope), indent=2),
        "",
        "FACTOR UNIVERSE",
        json.dumps(factor_universe_descriptions, indent=2),
        "",
        "PORTFOLIO HOLDINGS (ticker -> weight)",
        json.dumps(_rounded_holdings(portfolio_holdings), indent=2),
    ]
    if prior_errors:
        sections.extend(
            [
                "",
                "YOUR PREVIOUS PROPOSAL HAD THESE ISSUES - fix them:",
                *(f"- {e}" for e in prior_errors),
            ]
        )
    return "\n".join(sections)


def _envelope_records(envelope: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {
            "factor": name,
            "mean": float(row["mean"]) if pd.notna(row["mean"]) else None,
            "p10": float(row["p10"]) if pd.notna(row["p10"]) else None,
            "p90": float(row["p90"]) if pd.notna(row["p90"]) else None,
            "count": int(row["count"]),
        }
        for name, row in envelope.iterrows()
    ]


def _rounded_holdings(portfolio_holdings: dict[str, float]) -> dict[str, float]:
    return {t: round(w, 6) for t, w in sorted(portfolio_holdings.items())}
