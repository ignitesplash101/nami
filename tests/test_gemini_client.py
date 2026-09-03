from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pandas as pd
from google.genai import types

from app.data.sample_portfolios import get_portfolio
from app.llm.gemini_client import GeminiClient
from app.llm.schemas import (
    AnalogSelectionOutput,
    DecompositionOutput,
    ShockEditPatch,
    ShockProposalOutput,
)


def test_all_request_configs_omit_deprecated_sampling_parameters(monkeypatch) -> None:
    client = GeminiClient.__new__(GeminiClient)
    client._types = types
    client._structured_thinking = None
    client._selection_thinking = None
    captured_configs: list[types.GenerateContentConfig] = []

    def _capture_request(*, contents: object, config: object) -> object:
        del contents
        assert isinstance(config, types.GenerateContentConfig)
        captured_configs.append(config)
        response_schema = config.response_schema
        if response_schema is DecompositionOutput:
            text = '{"sub_narratives":["rate shock","credit stress"]}'
        elif response_schema is AnalogSelectionOutput:
            text = '{"selected_events":[],"reasoning":"test"}'
        elif response_schema is ShockEditPatch:
            text = '{"scope":"rerun_required","edits":[],' '"rejection_reason":"test"}'
        elif response_schema is ShockProposalOutput:
            text = '{"factor_shocks":[],"periphery_shocks":[],"narrative":"test"}'
        else:
            text = "test narrative"
        return SimpleNamespace(text=text, candidates=[])

    monkeypatch.setattr(client, "_generate_content", _capture_request)

    portfolio = get_portfolio("us_tech_growth")
    envelope = pd.DataFrame(
        {"mean": [-0.1], "p10": [-0.2], "p90": [0.0], "count": [3]},
        index=["SPY"],
    )

    client.decompose("Rates rise while credit spreads widen")
    client.select_analogs("Rates rise", [])
    client._analog_grounded_narrative(
        scenario_text="Rates rise",
        as_of_date=date(2026, 1, 2),
        selected_analog_events=[],
        envelope=envelope,
        factor_universe_descriptions=[],
        portfolio=portfolio,
    )
    client._grounded_narrative(
        scenario_text="Rates rise",
        envelope=envelope,
        factor_universe_descriptions=[],
        portfolio=portfolio,
    )
    client.propose_shock_edit(
        prior_factor_shocks=[],
        adjustment_text="Reduce the rate shock",
        envelope=envelope,
        factor_universe_descriptions=[],
    )
    client._extract_structured_shocks(
        narrative="test narrative",
        envelope=envelope,
        factor_universe_descriptions=[],
        portfolio=portfolio,
    )

    assert len(captured_configs) == 6
    deprecated = {"temperature", "top_p", "top_k"}
    for config in captured_configs:
        assert deprecated.isdisjoint(config.model_dump(exclude_none=True))
