"""Vertex AI Gemini wrapper for the scenario LLM calls.

Call 1 (`select_analogs`): structured output, no grounding; picks event_ids from the registry.
Call 2a (`_grounded_narrative`): free-form text, Google Search grounding, no schema.
Call 2b (`_extract_structured_shocks`): structured output, no grounding tools.

The split avoids the Gemini failure mode where `response_schema` is honored but the
Google Search tool is not invoked, producing valid JSON with no grounding metadata.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from app.config import Config
from app.data.sample_portfolios import Portfolio
from app.factors.analogs import HistoricalEvent
from app.llm.grounding import extract_citations
from app.llm.prompts import (
    ANALOG_GROUNDED_NARRATIVE_PROMPT,
    ANALOG_SELECTION_PROMPT,
    DECOMPOSITION_PROMPT,
    GROUNDED_NARRATIVE_PROMPT,
    SHOCK_EDIT_PROMPT,
    SHOCK_EXTRACTION_PROMPT,
    format_analog_grounded_narrative_user_message,
    format_analog_selection_user_message,
    format_decomposition_user_message,
    format_grounded_narrative_user_message,
    format_shock_edit_user_message,
    format_shock_extraction_user_message,
)
from app.llm.schemas import (
    AnalogSelectionOutput,
    Citation,
    DecompositionOutput,
    ShockEditPatch,
    ShockProposalOutput,
)
from app.llm.validation import validate_shock_proposal


class GeminiClient:
    def __init__(self, config: Config) -> None:
        from google import genai
        from google.genai import types as _types

        self._types = _types
        self._client = genai.Client(
            vertexai=True,
            project=config.google_cloud_project,
            location=config.vertex_ai_location,
            http_options=_types.HttpOptions(api_version="v1"),
        )
        self._model = config.vertex_model_id
        self._temperature = config.llm_temperature

    def _generate_content(self, *, contents: object, config: object) -> object:
        """Single chokepoint for every paid Gemini call.

        All 6 `generate_content` call sites route through here so a metered subclass
        (see `app/observability/metering.py`) can reserve budget, count tokens, and
        reconcile actual usage in ONE place — catching internal fan-out (retries,
        decomposition subset reruns) that an outer method wrapper would miss.
        """
        return self._client.models.generate_content(
            model=self._model, contents=contents, config=config
        )

    def decompose(self, scenario_text: str) -> DecompositionOutput:
        """Split a scenario into 2-4 self-contained sub-narratives. No grounding.

        Used by `compute_narrative_shapley` to enumerate 2^N subset evaluations for
        per-sub-narrative Shapley attribution.
        """
        user_msg = format_decomposition_user_message(scenario_text)
        response = self._generate_content(
            contents=user_msg,
            config=self._types.GenerateContentConfig(
                system_instruction=DECOMPOSITION_PROMPT,
                temperature=self._temperature,
                response_mime_type="application/json",
                response_schema=DecompositionOutput,
            ),
        )
        return DecompositionOutput.model_validate_json(response.text)

    def select_analogs(
        self, scenario_text: str, event_summaries: list[dict]
    ) -> AnalogSelectionOutput:
        user_msg = format_analog_selection_user_message(scenario_text, event_summaries)
        response = self._generate_content(
            contents=user_msg,
            config=self._types.GenerateContentConfig(
                system_instruction=ANALOG_SELECTION_PROMPT,
                temperature=self._temperature,
                response_mime_type="application/json",
                response_schema=AnalogSelectionOutput,
            ),
        )
        return AnalogSelectionOutput.model_validate_json(response.text)

    def propose_shocks_with_retry(
        self,
        *,
        scenario_text: str,
        portfolio: Portfolio,
        factor_universe_descriptions: list[dict],
        envelope: pd.DataFrame,
        events_registry: dict[str, HistoricalEvent],
        max_retries: int = 1,
        analog_grounded: bool = False,
        as_of_date: date | None = None,
        selected_analog_events: list[dict] | None = None,
        per_event_returns: list[dict] | None = None,
    ) -> tuple[ShockProposalOutput, list[Citation]]:
        del events_registry  # currently unused; reserved for future cross-checks

        if analog_grounded:
            # Backdated path: no Google Search, narrative grounded in analog
            # events only. as_of_date + selected_analog_events are required.
            if as_of_date is None or selected_analog_events is None:
                raise ValueError(
                    "analog_grounded=True requires as_of_date and selected_analog_events"
                )
            narrative, citations = self._analog_grounded_narrative(
                scenario_text=scenario_text,
                as_of_date=as_of_date,
                selected_analog_events=selected_analog_events,
                envelope=envelope,
                factor_universe_descriptions=factor_universe_descriptions,
                portfolio=portfolio,
            )
        else:
            narrative, citations = self._grounded_narrative(
                scenario_text=scenario_text,
                envelope=envelope,
                factor_universe_descriptions=factor_universe_descriptions,
                portfolio=portfolio,
            )
            if not citations:
                raise RuntimeError(
                    "Grounded narrative call returned no citations. Gemini did not invoke "
                    "Google Search, so current-market stress context cannot be returned."
                )

        prior_errors: list[str] = []
        for attempt in range(max_retries + 1):
            shock_output = self._extract_structured_shocks(
                narrative=narrative,
                envelope=envelope,
                factor_universe_descriptions=factor_universe_descriptions,
                portfolio=portfolio,
                prior_errors=prior_errors if attempt > 0 else None,
                per_event_returns=per_event_returns,
            )
            shock_output = shock_output.model_copy(update={"narrative": narrative})

            errors = validate_shock_proposal(shock_output, envelope=envelope, portfolio=portfolio)
            if not errors:
                return shock_output, citations

            prior_errors = errors

        raise RuntimeError(
            f"Shock proposal failed validation after {max_retries + 1} attempts: {prior_errors}"
        )

    def _analog_grounded_narrative(
        self,
        *,
        scenario_text: str,
        as_of_date: date,
        selected_analog_events: list[dict],
        envelope: pd.DataFrame,
        factor_universe_descriptions: list[dict],
        portfolio: Portfolio,
    ) -> tuple[str, list[Citation]]:
        """Backdated narrative path: NO Google Search. Narrative is grounded
        in the selected analog events and the envelope only. Returns empty
        citations list — `analogs_selected` on the result is the audit trail.
        """
        user_msg = format_analog_grounded_narrative_user_message(
            scenario_text=scenario_text,
            as_of_date=as_of_date,
            selected_analog_events=selected_analog_events,
            envelope=envelope,
            factor_universe_descriptions=factor_universe_descriptions,
            portfolio_holdings=portfolio.holdings,
        )
        response = self._generate_content(
            contents=user_msg,
            config=self._types.GenerateContentConfig(
                system_instruction=ANALOG_GROUNDED_NARRATIVE_PROMPT,
                temperature=self._temperature,
                # NO tools= — Google Search must not be invoked for backdated runs.
            ),
        )
        return response.text or "", []

    def _grounded_narrative(
        self,
        *,
        scenario_text: str,
        envelope: pd.DataFrame,
        factor_universe_descriptions: list[dict],
        portfolio: Portfolio,
    ) -> tuple[str, list[Citation]]:
        """Call 2a: current-market narrative with Google Search grounding, no schema."""
        user_msg = format_grounded_narrative_user_message(
            scenario_text=scenario_text,
            envelope=envelope,
            factor_universe_descriptions=factor_universe_descriptions,
            portfolio_holdings=portfolio.holdings,
        )
        response = self._generate_content(
            contents=user_msg,
            config=self._types.GenerateContentConfig(
                system_instruction=GROUNDED_NARRATIVE_PROMPT,
                temperature=self._temperature,
                tools=[self._types.Tool(google_search=self._types.GoogleSearch())],
            ),
        )
        return response.text or "", extract_citations(response)

    def propose_shock_edit(
        self,
        *,
        prior_factor_shocks: list[dict],
        adjustment_text: str,
        envelope: pd.DataFrame,
        factor_universe_descriptions: list[dict],
    ) -> ShockEditPatch:
        """Patch-only adjustment call: returns a ShockEditPatch, no Google Search.

        Caller is responsible for re-validating the patch against the canonical
        scenario's envelope and factor-name set (see `validate_factor_overrides`).
        """
        user_msg = format_shock_edit_user_message(
            prior_factor_shocks=prior_factor_shocks,
            adjustment_text=adjustment_text,
            envelope=envelope,
            factor_universe_descriptions=factor_universe_descriptions,
        )
        response = self._generate_content(
            contents=user_msg,
            config=self._types.GenerateContentConfig(
                system_instruction=SHOCK_EDIT_PROMPT,
                temperature=self._temperature,
                response_mime_type="application/json",
                response_schema=ShockEditPatch,
            ),
        )
        return ShockEditPatch.model_validate_json(response.text)

    def _extract_structured_shocks(
        self,
        *,
        narrative: str,
        envelope: pd.DataFrame,
        factor_universe_descriptions: list[dict],
        portfolio: Portfolio,
        prior_errors: list[str] | None = None,
        per_event_returns: list[dict] | None = None,
    ) -> ShockProposalOutput:
        """Call 2b: schema-bound shock extraction from the grounded narrative, no tools."""
        user_msg = format_shock_extraction_user_message(
            narrative=narrative,
            envelope=envelope,
            factor_universe_descriptions=factor_universe_descriptions,
            portfolio_holdings=portfolio.holdings,
            prior_errors=prior_errors,
            per_event_returns=per_event_returns,
        )
        response = self._generate_content(
            contents=user_msg,
            config=self._types.GenerateContentConfig(
                system_instruction=SHOCK_EXTRACTION_PROMPT,
                temperature=self._temperature,
                response_mime_type="application/json",
                response_schema=ShockProposalOutput,
            ),
        )
        return ShockProposalOutput.model_validate_json(response.text)
