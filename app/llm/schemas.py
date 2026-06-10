"""Pydantic v2 models for the LLM pipeline: Gemini call inputs/outputs and the cached ScenarioResult."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

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
    #                                              Sum = factor-driven P&L under
    #                                              the demeaned-background contract.
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

    Fixed-context shock attribution — each subset PINS the source scenario's analog
    set and uses the analog-only narrative path (no Google re-grounding), so only the
    shock proposal varies per fragment. Deterministic and illustrative, not a causal
    decomposition of the original scenario.
    """

    model_config = ConfigDict(extra="forbid")
    sub_narratives: list[str]
    contributions: list[NarrativeContribution]
    subset_pnls: dict[str, float]  # bitmask string "0110" -> P&L
    total_pnl: float  # full scenario (all sub-narratives ON)
    n_subsets_evaluated: int  # 2^N


class FactorEdit(BaseModel):
    """One factor magnitude/removal edit in a ShockEditPatch.

    `new_shock == 0.0` is the explicit removal sentinel and is always accepted
    regardless of envelope bounds; any other value MUST be in [p10, p90] for
    that factor in the canonical result's envelope. Adding factors not in the
    canonical result requires a full rerun.
    """

    model_config = ConfigDict(extra="forbid")
    factor: str
    new_shock: float
    reasoning: str


class ShockEditPatch(BaseModel):
    """LLM output for a prompt-driven shock adjustment.

    `scope` is the LLM's classification of the user's intent:
      - "local":            magnitude/removal edits to existing shocks only.
                            `edits` populated; `rejection_reason` is None.
      - "rerun_required":   user asked for a semantic change (new mechanism,
                            region, asset class, factual basis, or introduces
                            factors not already shocked). `edits` is empty
                            and `rejection_reason` explains why a full rerun
                            is required (surfaced to the user as a CTA).
    """

    model_config = ConfigDict(extra="forbid")
    scope: Literal["local", "rerun_required"]
    edits: list[FactorEdit] = Field(default_factory=list)
    rejection_reason: str | None = None


class ShockAdjustment(BaseModel):
    """One entry in the per-result adjustment history (derived results only).

    Adjusted results are NOT cached; only canonical (initial) results round-trip
    the scenario cache. Canonical results always carry `adjustment_history=[]`.
    """

    model_config = ConfigDict(extra="forbid")
    kind: Literal["manual", "prompt"]
    prompt_text: str | None = None
    timestamp: datetime
    changed_factors: dict[str, list[float]]  # factor -> [before, after]


class RiskDiagnostic(BaseModel):
    """Warning-only methodology diagnostics for scenario review.

    These records explain why a shock vector or diagnostic attribution view may
    need human review. They never rewrite shocks and are safe to omit on older
    cached/saved results.
    """

    model_config = ConfigDict(extra="forbid")
    kind: Literal[
        "correlation_conflict",
        "envelope_direction_conflict",
        "conditional_cross_credit",
        "low_regression_r2",
        "position_loss_exceeds_100pct",
        "periphery_magnitude",
        "periphery_dominance",
    ]
    severity: Literal["info", "warning"] = "warning"
    message: str
    factors: list[str] = Field(default_factory=list)
    evidence: dict[str, float | int | str] = Field(default_factory=dict)


class TickerRegressionQuality(BaseModel):
    """Per-ticker beta-regression fit quality (mirrors regression.TickerRegressionStats).

    `r2` is in-sample on the centered standardized-ridge fit, in [0, 1].
    `idio_vol_weekly` is the ddof=1 weekly residual vol, NOT annualized.
    """

    model_config = ConfigDict(extra="forbid")
    r2: float
    n_obs: int
    idio_vol_weekly: float


class RegressionQuality(BaseModel):
    """Fit-quality block for the beta regression behind a scenario result.

    Deterministic from the same vintage-controlled data as the betas (same cache
    key), so unlike NAV/benchmark overlays it IS cached with the canonical result.
    `by_ticker` deliberately has no entry for the CASH sentinel — no regression
    runs for it.
    """

    model_config = ConfigDict(extra="forbid")
    estimator: str
    lookback_weeks: int
    alpha: float
    min_obs: int
    by_ticker: dict[str, TickerRegressionQuality]


class AnalogEventReturns(BaseModel):
    """Total factor returns over one selected analog's exact-day window.

    Mirrors the per-event payload shown to the shock-extraction call so the UI
    can show which analog drives each envelope band edge. `factor_returns` values
    are decimal total returns over the event window (None where the factor's ETF
    did not exist in the window); `window_calendar_days` is end − start.
    """

    model_config = ConfigDict(extra="forbid")
    event_id: str
    window_calendar_days: int
    factor_returns: dict[str, float | None]


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
    adjustment_history: list[ShockAdjustment] = Field(default_factory=list)
    risk_diagnostics: list[RiskDiagnostic] = Field(default_factory=list)
    # Beta-regression fit quality (Phase 18). Cached with the canonical result
    # (deterministic from the keyed vintage); None on pre-Phase-18 payloads.
    regression_quality: RegressionQuality | None = None
    # Per-analog factor returns + window lengths backing the envelope (Phase 18).
    # Same payload the shock-extraction call sees; None on older payloads.
    analog_event_returns: list[AnalogEventReturns] | None = None
    # Backdating metadata (added Phase 11). All default-defaulted so cached v5
    # entries deserialize cleanly under v6 lazy re-derivation.
    # `market_date` is the *effective* as-of date (last NYSE trading day on or
    # before the user request); `requested_as_of_date` is the raw user request
    # for display/audit clarity.
    requested_as_of_date: date | None = None
    # narrative_mode: "grounded" when Google Search ran (current-date); "analog_only"
    # when backdated and the LLM was constrained to analog-event grounding only.
    narrative_mode: Literal["grounded", "analog_only"] = "grounded"
    # event_ids selected for the analog envelope. Already on `analogs_selected`
    # but duplicated here for reproducibility-block convenience.
    selected_event_ids: list[str] = Field(default_factory=list)
    # Mark-to-market metadata. None on return-only runs; populated when the run
    # supplied share quantities (true MTM, USD-marked) or a NAV scalar. Dollars
    # are DERIVED client-side as `return_field × portfolio_nav` (the engine is
    # linear in weights), so no dollar P&L is stored. All optional with defaults
    # so pre-MTM cached payloads deserialize unchanged. NOTE: these are attached
    # AFTER cache retrieval — they are never persisted in the GCS scenario cache.
    portfolio_nav: float | None = None
    reporting_currency: str | None = None
    position_quantities: dict[str, float] | None = None
    position_values: dict[str, float] | None = None  # USD market value per ticker
    mark_prices: dict[str, float] | None = None  # raw close in native quote unit
    price_date_by_ticker: dict[str, str] | None = None
    fx_rates: dict[str, float] | None = None  # major currency -> USD per unit
    fx_date_by_currency: dict[str, str] | None = None
    # Benchmark / active-return overlay (added with the holdings-quality work).
    # Computed by running the benchmark ticker as a one-holding portfolio through
    # the SAME factor shocks. Like the MTM block, these are attached AFTER cache
    # retrieval and NEVER persisted — defaults keep older cached payloads valid.
    # `active_return = portfolio_pnl.total_pnl − benchmark_pnl.total_pnl`.
    benchmark_ticker: str | None = None
    benchmark_pnl: PortfolioPnL | None = None
    active_return: float | None = None
