from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.llm.schemas import ScenarioResult


class Permissions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    custom_portfolio: bool
    free_text_scenario: bool
    narrative_decomposition: bool


class AccessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    access_mode: str
    admin_available: bool
    permissions: Permissions


class UnlockRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    passcode: str


class SamplePortfolioResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    name: str
    description: str
    holdings: dict[str, float]


class SampleScenarioResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    name: str
    text: str


class PortfolioValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    holdings: dict[str, float]


class PortfolioValidationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    errors: list[str]
    normalized_holdings: dict[str, float]
    total_weight: float


class ScenarioRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sample_scenario_key: str | None = None
    scenario_text: str | None = None
    portfolio_key: str | None = None
    portfolio_name: str | None = None
    portfolio_holdings: dict[str, float] | None = None


class AnalogEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str
    name: str
    start_date: str
    end_date: str
    tags: list[str]
    description: str


class ScenarioRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result: ScenarioResult
    analog_events: dict[str, AnalogEventResponse] = Field(default_factory=dict)


class NarrativeDecompositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result: ScenarioResult
