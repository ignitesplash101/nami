"""System prompts and prompt-formatting helpers for Gemini calls.

PROMPT_VERSION is part of the scenario cache key. Bump it when prompt semantics
change so cached responses are re-derived against the new pipeline.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pandas as pd

from app.utils.disclaimers import DISCLAIMER_LONG

# Bump on ANY change that affects ScenarioResult's shape OR prompt semantics. Schema
# changes invalidate the cache the same way prompt changes do.
# v2 -> v3: ScenarioResult gained portfolio_name + portfolio_holdings.
# v3 -> v4: PortfolioPnL renamed by_factor -> by_factor_naive, added
#           by_factor_conditional_shapley; ScenarioResult gained narrative_shapley.
# v4 -> v5: PortfolioPnL gained by_factor_conditional_shapley_explicit and
#           by_factor_conditional_shapley_grouped (extra Shapley variants).
# v5 -> v6: Backdated scenarios + analog-only narrative path. Analog filter now
#           uses end_date <= as_of (was implicitly unbounded); ScenarioResult
#           gained narrative_mode + effective/requested as-of dates +
#           selected_event_ids. Cache namespace must be invalidated because
#           the same (scenario_text, portfolio, market_date) key could have
#           produced a different result under v5 if any analog event was
#           still in progress on market_date.
# v7 — Live anchor moved from date.today() to latest NYSE close
#      (app/utils/calendar.py::latest_market_date). A fixed past as-of (e.g. the
#      last close) is now classified LIVE (grounded, Google-Search citations)
#      where v6 classified it backdated/analog-only — same key, different
#      semantics — so v6 entries must be invalidated.
# v8 - Shock extraction is framed explicitly as hypothetical stress construction,
#      factor universe payloads include human-readable labels, and ScenarioResult
#      gained warning-only risk_diagnostics.
# v8 -> v9: Shock-semantics contract. The extraction prompt defines shock units and
#      horizon (cumulative episode total return, not weekly); rule 4 now states the
#      validator's actual blocking behavior (the reasoning-based escape hatch never
#      existed in code); factor descriptions are horizon-neutral; the extraction
#      payload gains per-event factor returns + window lengths; analog selection is
#      enforced to 2-5 unique events post-hoc (422); periphery shocks gain a hard
#      ±0.75 band; ScenarioResult gained regression_quality + analog_event_returns;
#      .T-suffix ticker returns are converted to USD before beta estimation.
#      NOTE: engine-math changes (estimator/alpha/lookback) are keyed separately
#      via `regression_spec` in the cache key — they do NOT require a bump here.
PROMPT_VERSION = "v9"


ANALOG_SELECTION_PROMPT = f"""\
You are a quantitative strategist matching hypothetical market stresses to
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

Write a 3-5 sentence hypothetical stress narrative explaining the scenario mechanism
and modeled market impact. Ground the narrative in recent, real market news relevant
to the user's scenario. Mention concrete dates, reported market moves, policy actions,
earnings/news items, or headlines when they are relevant.

Do not propose numeric factor shocks in this step. Do not recommend trades. Output
plain text only: no JSON, no markdown headers, no bullet list.
"""


DECOMPOSITION_PROMPT = f"""\
You are a quantitative scenario analyst splitting a market scenario into independent
sub-narratives for counterfactual attribution.

{DISCLAIMER_LONG}

TASK
Given a market scenario in natural language, decompose it into 2 to 4 sub-narratives.
Each sub-narrative must be:

1. SELF-CONTAINED — readable on its own without referring to the others.
2. CAUSALLY DISTINCT — does not logically imply or fully overlap with another sub-narrative.
3. MATERIAL - removing it would meaningfully change the modeled portfolio P&L.

Return JSON matching the DecompositionOutput schema with exactly 2-4 strings under
`sub_narratives`. No commentary outside the JSON.

If the scenario describes only a single mechanism, return exactly 2 entries that split
the mechanism into its setup and its consequence. Never return fewer than 2 or more than 4.
"""


SHOCK_EXTRACTION_PROMPT = f"""\
You are a quantitative scenario analyst extracting structured factor and periphery
shocks from an already grounded hypothetical stress narrative. Treat the scenario
as a conditional stress test, not as a forecast of expected returns.

{DISCLAIMER_LONG}

The narrative was generated upstream with Google Search grounding. Your job is purely
to translate that narrative into a coherent numeric stress vector using the empirical
envelope, per-event returns, factor universe, and portfolio holdings provided by the
user message.

SHOCK UNITS AND HORIZON
- A factor shock is the CUMULATIVE TOTAL move of that factor over the entire
  hypothetical stress episode, expressed as a decimal (-0.12 means -12% in total).
  It is NOT a weekly or daily return.
- The episode horizon is implied by the selected analog events: every envelope
  statistic and every per-event figure in the user message is the factor's total
  move from the first to the last day of that analog's window (windows range from
  about a week to several months). Propose magnitudes consistent with an episode
  of similar duration to the analogs shown.
- Macro factors (VIX, TNX, DXY, OIL) are decimal changes in the LEVEL of the index
  over the episode (e.g. VIX 15 -> 22.5 is +0.50). The same decimal move implies
  different absolute levels depending on the starting level.
- A periphery shock is the additional idiosyncratic total return for one held
  ticker over the same episode, on top of its factor-driven move.

RULES
1. Output JSON matching the ShockProposalOutput schema. No extra fields.
2. Copy the grounded narrative into the `narrative` field exactly as provided.
3. Do not introduce new current-market claims beyond the narrative.
4. For any factor whose envelope row has count >= 3, the shock MUST lie inside
   [p10, p90]. This is mechanically enforced: an out-of-band shock is rejected and
   re-asked once, then the run fails. If the narrative implies a move beyond the
   band, set the shock at the nearer band edge and say so in the reasoning. The
   reasoning text is for human review only - it cannot authorize an out-of-band
   shock.
5. Down-weight factors with count < 3 (their band is not enforced, but the
   per-event returns show how thin the evidence is).
6. Periphery shocks may only reference tickers in the provided portfolio holdings,
   must be within [-0.75, +0.75] (mechanically enforced), and should stay modest
   relative to the factor-driven move.
7. When overlapping factors materially diverge (for example US large-cap equities
   (SPY), Global equities (ACWI), US technology (XLK), Momentum stocks (MTUM), and
   Quality stocks (QUAL)), the reasoning must explain the rotation rather than
   leaving it implicit.
8. Outputs are hypothetical stress estimates, not forecasts, investment advice, or
   regulatory stress tests.
"""


ANALOG_GROUNDED_NARRATIVE_PROMPT = f"""\
You are a quantitative scenario analyst writing the narrative for an equity
portfolio scenario engine **in backdated mode**.

{DISCLAIMER_LONG}

CRITICAL BACKDATING CONSTRAINTS

You will receive an explicit AS-OF DATE. You MUST NOT reference any events,
market data, news, or developments that occurred AFTER that date. The only
sources of grounding for this narrative are:

1. The analog events listed in the user message (their dates, magnitudes,
   tagged mechanisms).
2. The empirical envelope statistics (mean, p10, p90, count) computed across
   those analog events.
3. The portfolio holdings.

DO NOT invoke Google Search. DO NOT cite recent news. DO NOT mention any
event whose start date is after the as-of date.

OUTPUT

Write a concise 3-5 sentence narrative that:
- Names which analog event(s) the scenario most closely echoes and why.
- States the mechanism (e.g. "rates spike via Fed credibility shock",
  "risk-off on credit contagion") consistent with those analogs.
- Quotes a few rough magnitudes from the envelope to give the reader a sense
  of scale (e.g. "in 2018-2019, SPY moved -X% across this style of event").
  The envelope statistics are TOTAL returns over each analog's full event
  window, not weekly returns; quote them as episode moves.

Plain text only — no JSON, no headers, no bullets. No URLs or citations
beyond the analog event names themselves.
"""


SHOCK_EDIT_PROMPT = f"""\
You are revising an existing market scenario's factor shocks. The user has already
seen the initial proposal and is now asking for a targeted edit.

{DISCLAIMER_LONG}

YOU MUST FIRST CLASSIFY THE SCOPE OF THE EDIT

Return a ShockEditPatch JSON object. Set `scope` to one of:

  - "local": the user is changing the MAGNITUDE of an existing factor shock, or
    REMOVING one via 0.0. Examples: "make VIX larger", "halve the credit shock",
    "remove the rates component", "push USD to the high end of the band".
    Populate `edits` with one FactorEdit per factor the user wants to change.
    Leave `rejection_reason` as null.

  - "rerun_required": the user is asking for a SEMANTIC change that invalidates
    the original analog/narrative selection. Examples include:
      * a new mechanism not in the original narrative ("add a credit contagion",
        "also model an oil supply shock")
      * a new region or asset class focus ("shift toward emerging markets",
        "focus on Japan instead of US")
      * a changed factual basis ("assume the Fed cuts 50bps instead of 25",
        "assume the war ended yesterday")
      * introducing a factor that was NOT in the prior shock list
    In this case: set `edits=[]` and populate `rejection_reason` with ONE sentence
    that the UI will show the user along with a button to rerun the full scenario.

RULES FOR `edits`
1. You may only edit factors that appear in the prior shock list. Adding a new
   factor is `rerun_required`.
2. Each edit's `new_shock` MUST be inside the envelope `[p10, p90]` for that
   factor, OR exactly 0.0 (which means "remove this factor from the scenario").
   Shocks are cumulative total moves over the stress episode (decimals),
   matching the envelope's units — not weekly returns.
3. Each edit's `reasoning` is ONE concise sentence explaining the magnitude.
4. Do NOT propose changes to factors the user did not ask about. Edits are
   surgical, not a re-derivation.
5. Outputs are illustrative and probabilistic, not investment advice.
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


def format_decomposition_user_message(scenario_text: str) -> str:
    return (
        "SCENARIO TO DECOMPOSE\n"
        f"{scenario_text.strip()}\n\n"
        "Return 2 to 4 self-contained, causally-distinct sub-narratives."
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
    per_event_returns: list[dict[str, Any]] | None = None,
) -> str:
    sections = [
        "GROUNDED NARRATIVE",
        narrative.strip(),
        "",
        "EMPIRICAL ENVELOPE (total event-window returns per factor, across selected analogs)",
        json.dumps(_envelope_records(envelope), indent=2),
    ]
    if per_event_returns:
        sections.extend(
            [
                "",
                "PER-EVENT FACTOR RETURNS (total return over each analog's full window)",
                json.dumps(per_event_returns, indent=2),
            ]
        )
    sections.extend(
        [
            "",
            "FACTOR UNIVERSE",
            json.dumps(factor_universe_descriptions, indent=2),
            "",
            "PORTFOLIO HOLDINGS (ticker -> weight)",
            json.dumps(_rounded_holdings(portfolio_holdings), indent=2),
        ]
    )
    if prior_errors:
        sections.extend(
            [
                "",
                "YOUR PREVIOUS PROPOSAL HAD THESE ISSUES - fix them:",
                *(f"- {e}" for e in prior_errors),
            ]
        )
    return "\n".join(sections)


def format_analog_grounded_narrative_user_message(
    *,
    scenario_text: str,
    as_of_date: date,
    selected_analog_events: list[dict[str, Any]],
    envelope: pd.DataFrame,
    factor_universe_descriptions: list[dict[str, Any]],
    portfolio_holdings: dict[str, float],
) -> str:
    return "\n".join(
        [
            f"AS-OF DATE (strict no-look-ahead): {as_of_date.isoformat()}",
            "",
            "SCENARIO",
            scenario_text.strip(),
            "",
            "SELECTED HISTORICAL ANALOG EVENTS (your ONLY grounding source)",
            json.dumps(selected_analog_events, indent=2),
            "",
            "EMPIRICAL ENVELOPE (per factor, across the selected analogs)",
            json.dumps(_envelope_records(envelope), indent=2),
            "",
            "FACTOR UNIVERSE",
            json.dumps(factor_universe_descriptions, indent=2),
            "",
            "PORTFOLIO HOLDINGS (ticker -> weight)",
            json.dumps(_rounded_holdings(portfolio_holdings), indent=2),
            "",
            "INSTRUCTION",
            "Write a 3-5 sentence narrative grounded ONLY in the analog events above.",
            "Do not invoke Google Search. Do not reference anything after the as-of date.",
        ]
    )


def format_shock_edit_user_message(
    *,
    prior_factor_shocks: list[dict[str, Any]],
    adjustment_text: str,
    envelope: pd.DataFrame,
    factor_universe_descriptions: list[dict[str, Any]],
) -> str:
    return "\n".join(
        [
            "PRIOR FACTOR SHOCKS (the scenario currently in effect)",
            json.dumps(prior_factor_shocks, indent=2),
            "",
            "EMPIRICAL ENVELOPE (per factor, across the original analogs)",
            json.dumps(_envelope_records(envelope), indent=2),
            "",
            "FACTOR UNIVERSE",
            json.dumps(factor_universe_descriptions, indent=2),
            "",
            "USER ADJUSTMENT REQUEST",
            adjustment_text.strip(),
            "",
            "INSTRUCTION",
            "Classify the scope. If local, return surgical edits. If rerun_required, "
            "return a one-sentence rejection_reason and empty edits.",
        ]
    )


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
