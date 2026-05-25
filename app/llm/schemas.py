"""Pydantic v2 models for the LLM pipeline: Gemini call inputs/outputs and the cached ScenarioResult."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict


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
    model_config = ConfigDict(extra="forbid")
    total_pnl: float
    by_factor: dict[str, float]
    by_ticker_factor: dict[str, float]
    by_ticker_periphery: dict[str, float]
    by_ticker_total: dict[str, float]


class ScenarioResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_text: str
    market_date: date
    portfolio_key: str
    analogs_selected: list[AnalogSelection]
    factor_shocks: list[FactorShock]
    periphery_shocks: list[PeripheryShock]
    narrative: str
    citations: list[Citation]
    factor_envelope: dict[str, dict[str, float]]
    portfolio_pnl: PortfolioPnL
