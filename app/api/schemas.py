from __future__ import annotations

from datetime import date, datetime
from typing import Literal

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
    # Latest NYSE regular-close date (YYYY-MM-DD). The UI seeds the as-of picker
    # with this so "live" means the latest US close, not the browser's local day.
    latest_market_date: str


class UnlockRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    passcode: str


class ReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ready: bool
    # Coarse per-dependency status: "ok" | "unavailable" (no internal detail leak).
    checks: dict[str, str]


class StatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service: str
    nami_engine_version: str
    prompt_version: str
    model_id: str
    environment: str
    ready: bool
    disclaimer: str
    rate_limits: dict[str, str]
    daily_cost_cap_usd: float
    daily_run_cap: int
    runs_today: int
    # Admin-only; None for visitors so spend is not exposed publicly.
    est_cost_today_usd: float | None = None


class UsageSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    day: str
    runs: int
    calls: int
    tokens_in: int
    tokens_out: int
    spent_usd: float
    reserved_usd: float
    cost_cap_usd: float
    run_cap: int


class AuditEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str
    target_type: str
    target_id: str | None = None
    request_id: str | None = None
    ip_hash: str | None = None
    at: datetime


class PurgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: str


class SamplePortfolioResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    name: str
    description: str
    holdings: dict[str, float]
    benchmark: str | None = None


class TickerMetadataResponse(BaseModel):
    """ticker -> {sector, country} classification tags for exposure breakdowns."""

    model_config = ConfigDict(extra="forbid")
    ticker_meta: dict[str, dict[str, str]]


class FactorMetadataResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    ticker: str
    group: str
    short_label: str
    display_name: str
    description: str


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
    # Backdated scenarios: user-requested as-of date. When None or today,
    # standard live-grounded path. When < today, runs in vintage-controlled
    # backdated mode (events filtered, yfinance end=, analog-only narrative).
    as_of_date: date | None = None
    # Mark-to-market (admin-only). `position_quantities` = share counts → true MTM
    # (marked to the as-of raw close, FX-converted to USD, weights derived).
    # `portfolio_nav` (alone, with weights) = illustrative dollar scaling. Both None
    # → return-space only (today's behavior).
    position_quantities: dict[str, float] | None = None
    portfolio_nav: float | None = None
    reporting_currency: str | None = None
    # Benchmark ticker for relative (active) return. None falls back to the sample
    # portfolio's own benchmark; custom books must pass one to get an active return.
    benchmark: str | None = None


class AnalogEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str
    name: str
    start_date: str
    end_date: str
    tags: list[str]
    description: str


class ScenarioReproducibility(BaseModel):
    """Full audit metadata for a scenario run. Surfaced on every response and
    persisted inline on saved scenarios so a result is reproducible (best-effort)
    without depending on any external version's stability.
    """

    model_config = ConfigDict(extra="forbid")
    model_id: str
    prompt_version: str
    factor_universe_version: str
    events_version: str
    requested_as_of_date: date
    effective_as_of_date: date
    narrative_mode: Literal["grounded", "analog_only"]
    beta_lookback_weeks: int
    ridge_alpha: float
    selected_event_ids: list[str]
    portfolio_holdings: dict[str, float]
    portfolio_key: str
    market_data_source: Literal["yfinance"] = "yfinance"
    nami_engine_version: str
    # Frozen mark-to-market block (None on return-only runs). Snapshotting the
    # NAV, the exact marks, and the FX rates + dates makes a saved MTM scenario
    # re-render identically even after live prices/FX drift.
    portfolio_nav: float | None = None
    reporting_currency: str | None = None
    position_quantities: dict[str, float] | None = None
    position_values: dict[str, float] | None = None
    mark_prices: dict[str, float] | None = None
    price_date_by_ticker: dict[str, str] | None = None
    fx_rates: dict[str, float] | None = None
    fx_date_by_currency: dict[str, str] | None = None


class ScenarioRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result: ScenarioResult
    analog_events: dict[str, AnalogEventResponse] = Field(default_factory=dict)
    # Server-computed cache key for the canonical scenario. The client echoes this
    # back on /api/scenarios/adjust-shocks; the server re-fetches the trusted
    # canonical result from the GCS cache rather than trusting client-supplied data.
    cache_key: str | None = None
    # Full reproducibility metadata (model/prompt/factor/events version + as-of
    # dates + config). Always populated; saved scenarios persist it inline.
    reproducibility: ScenarioReproducibility | None = None


class NarrativeDecompositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result: ScenarioResult


class ScenarioAdjustRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cache_key: str
    overrides: dict[str, float] | None = None  # manual mode: full factor->value map
    adjustment_text: str | None = None  # prompt mode: natural-language edit
    # Resent benchmark for the active-return overlay. Benchmarks are overlay-only
    # (never cached), so a custom book's benchmark can't be recovered from the
    # canonical — the client echoes it back here.
    benchmark: str | None = None


# --- Saved analytics (Firestore-backed) ---


class SaveScenarioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=200)
    tags: list[str] = Field(default_factory=list)
    notes: str = ""
    owner_label: str | None = None
    # The full result + analog events + reproducibility snapshot to persist.
    # All inline — no FK to GCS scenario cache; saved record is self-contained.
    result: ScenarioResult
    analog_events_snapshot: dict[str, AnalogEventResponse]
    reproducibility: ScenarioReproducibility
    portfolio_snapshot_ref: str | None = None


class SavedScenarioRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    tags: list[str] = Field(default_factory=list)
    notes: str = ""
    created_at: datetime
    created_by: str = "admin"
    owner_label: str | None = None
    scenario_text: str
    portfolio_snapshot_ref: str | None = None
    portfolio_holdings: dict[str, float]
    portfolio_key: str
    portfolio_name: str
    analog_events_snapshot: dict[str, AnalogEventResponse]
    result: ScenarioResult
    reproducibility: ScenarioReproducibility


class SavedScenarioListItem(BaseModel):
    """Trimmed-down list-view entry. Excludes the heavy `result` payload to keep
    library listings small; clients fetch the full record by id."""

    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    owner_label: str | None = None
    portfolio_name: str
    portfolio_key: str
    requested_as_of_date: date
    effective_as_of_date: date
    narrative_mode: Literal["grounded", "analog_only"]
    total_pnl: float
    # NAV for MTM runs (None otherwise); the UI shows total dollar P&L as
    # `total_pnl × portfolio_nav` without inflating the list payload.
    portfolio_nav: float | None = None


class SavePortfolioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    owner_label: str | None = None


class SavedPortfolioRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    description: str = ""
    created_at: datetime
    created_by: str = "admin"
    owner_label: str | None = None


class PortfolioSnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    as_of_date: date
    holdings: dict[str, float]
    notes: str = ""
    owner_label: str | None = None


class PortfolioSnapshotRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    portfolio_id: str
    as_of_date: date
    holdings: dict[str, float]
    notes: str = ""
    created_at: datetime
    created_by: str = "admin"
    owner_label: str | None = None
