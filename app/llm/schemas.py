"""Pydantic v2 models for the LLM pipeline: Gemini call inputs/outputs and the cached ScenarioResult."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AnalogSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str
    why_relevant: str


class FactorShock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    factor: str
    shock: float
    reasoning: str


class PeripheryShock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str
    shock: float
    reasoning: str


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str
    title: str | None = None
    snippet: str | None = None
    grounding_metadata: dict[str, Any] | None = None


class AnalogSelectionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selected_events: list[AnalogSelection]
    reasoning: str


class ShockProposalOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    factor_shocks: list[FactorShock]
    periphery_shocks: list[PeripheryShock]
    narrative: str


class PortfolioPnL(BaseModel):
    # NOTE: no `by_factor` alias — readers must pick a specific variant explicitly.
    # Pydantic v2's `computed_field` is included in `model_dump()` but rejected by
    # `model_validate()` under `extra="forbid"`, which would poison the JSON cache
    # round-trip.
    #
    # Conditional Shapley variants (all best-effort; None when factor history is
    # unavailable or shap fails):
    #   - by_factor_conditional_shapley:          full F-dim game, can cross-credit
    #                                              factors the LLM never shocked.
    #   - by_factor_conditional_shapley_explicit: game restricted to LLM-shocked
    #                                              factors; unshocked factors stay 0.
    #                                              Sum ≤ factor-driven P&L (gap is
    #                                              unattributed cross-correlation).
    #   - by_factor_conditional_shapley_grouped:  G-dim game over factor groups
    #                                              (market/sector/style/macro);
    #                                              within-group credit redistributed
    #                                              by naive weight. Sum = factor P&L.
    model_config = ConfigDict(extra="forbid")
    total_pnl: float
    by_factor_naive: dict[str, float]
    by_factor_conditional_shapley: dict[str, float] | None = None
    by_factor_conditional_shapley_explicit: dict[str, float] | None = None
    by_factor_conditional_shapley_grouped: dict[str, float] | None = None
    by_ticker_factor: dict[str, float]
    by_ticker_periphery: dict[str, float]
    by_ticker_total: dict[str, float]


class DecompositionOutput(BaseModel):
    """Gemini's split of a scenario into 2-4 self-contained sub-narratives."""

    model_config = ConfigDict(extra="forbid")
    sub_narratives: list[str]


class NarrativeContribution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    narrative_index: int
    narrative_text: str
    shapley_value: float
    relative_contribution: float


class NarrativeShapleyResult(BaseModel):
    """Result of running 2^N subset evaluations to assign per-sub-narrative Shapley values.

    Experimental counterfactual *pipeline* attribution — each subset reruns analog
    selection + grounded narrative + shock extraction, so the values reflect pipeline
    behavior on the subset, not a causal decomposition of the original scenario.
    """

    model_config = ConfigDict(extra="forbid")
    sub_narratives: list[str]
    contributions: list[NarrativeContribution]
    subset_pnls: dict[str, float]  # bitmask string "0110" -> P&L
    total_pnl: float  # full scenario (all sub-narratives ON)
    n_subsets_evaluated: int  # 2^N


class ScenarioResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_text: str
    market_date: date
    portfolio_key: str
    portfolio_name: str = "(unknown)"
    portfolio_holdings: dict[str, float] = Field(default_factory=dict)
    analogs_selected: list[AnalogSelection]
    factor_shocks: list[FactorShock]
    periphery_shocks: list[PeripheryShock]
    narrative: str
    citations: list[Citation]
    factor_envelope: dict[str, dict[str, float]]
    portfolio_pnl: PortfolioPnL
    narrative_shapley: NarrativeShapleyResult | None = None  # opt-in only
