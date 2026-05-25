"""Vertex AI Gemini wrapper for the two scenario calls.

Call 1 (`select_analogs`): structured output, no grounding — picks event_ids from the registry.
Call 2 (`propose_shocks_with_retry`): structured output + Google Search grounding —
proposes factor + periphery shocks within the empirical envelope, with a validation
repair loop (one retry max) on semantic violations. Raises if grounding metadata is
empty on the final attempt — we don't return forward-looking claims without citations.
"""

from __future__ import annotations

import pandas as pd

from app.config import Config
from app.data.sample_portfolios import Portfolio
from app.factors.analogs import HistoricalEvent
from app.llm.grounding import extract_citations, has_grounding
from app.llm.prompts import (
    ANALOG_SELECTION_PROMPT,
    SHOCK_PROPOSAL_PROMPT,
    format_analog_selection_user_message,
    format_shock_proposal_user_message,
)
from app.llm.schemas import (
    AnalogSelectionOutput,
    Citation,
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

    def select_analogs(
        self, scenario_text: str, event_summaries: list[dict]
    ) -> AnalogSelectionOutput:
        user_msg = format_analog_selection_user_message(scenario_text, event_summaries)
        response = self._client.models.generate_content(
            model=self._model,
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
    ) -> tuple[ShockProposalOutput, list[Citation]]:
        del events_registry  # currently unused; reserved for future cross-checks
        prior_errors: list[str] = []
        last_output: ShockProposalOutput | None = None
        last_citations: list[Citation] = []

        for attempt in range(max_retries + 1):
            user_msg = format_shock_proposal_user_message(
                scenario_text=scenario_text,
                envelope=envelope,
                factor_universe_descriptions=factor_universe_descriptions,
                portfolio_holdings=portfolio.holdings,
                prior_errors=prior_errors if attempt > 0 else None,
            )
            response = self._client.models.generate_content(
                model=self._model,
                contents=user_msg,
                config=self._types.GenerateContentConfig(
                    system_instruction=SHOCK_PROPOSAL_PROMPT,
                    temperature=self._temperature,
                    response_mime_type="application/json",
                    response_schema=ShockProposalOutput,
                    tools=[self._types.Tool(google_search=self._types.GoogleSearch())],
                ),
            )
            last_output = ShockProposalOutput.model_validate_json(response.text)
            last_citations = extract_citations(response)

            errors = validate_shock_proposal(last_output, envelope=envelope, portfolio=portfolio)
            if not errors:
                if not has_grounding(response):
                    raise RuntimeError(
                        "Gemini response did not return grounding metadata. "
                        "Forward-looking claims must be cited; cannot proceed."
                    )
                return last_output, last_citations

            prior_errors = errors

        raise RuntimeError(
            f"Shock proposal failed validation after {max_retries + 1} attempts: " f"{prior_errors}"
        )
