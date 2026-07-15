"""Public contracts for selecting and preserving the optional Quant V2 engine."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api.schemas import ScenarioRunRequest
from app.config import load_config
from app.data.market_cache import MARKET_CACHE_VERSION
from app.llm.gemini_client import GeminiClient
from app.llm.prompts import ANALOG_SELECTION_PROMPT, PROMPT_VERSION
from app.llm.scenario import QUANT_ENGINE_SPEC, adjust_scenario_shocks
from app.llm.schemas import (
    AnalogSelectionOutput,
    PortfolioPnL,
    QuantAnalogSelectionOutput,
    ScenarioResult,
)
from app.utils.hashing import scenario_cache_key
from tests.conftest import InMemoryCache


def _cache_kwargs() -> dict[str, object]:
    return {
        "scenario_text": "global recession",
        "portfolio_key": "test",
        "portfolio_holdings": {"A": 1.0},
        "market_date": date(2026, 1, 2),
        "model_id": "model",
        "prompt_version": "v12",
        "factor_universe_version": "factors",
        "events_version": "events",
        "regression_spec": "legacy-regression",
    }


def _minimal_result_payload() -> dict[str, object]:
    return {
        "scenario_text": "stress",
        "market_date": "2026-01-02",
        "portfolio_key": "test",
        "portfolio_name": "Test",
        "portfolio_holdings": {"A": 1.0},
        "analogs_selected": [],
        "factor_shocks": [],
        "periphery_shocks": [],
        "narrative": "Narrative.",
        "citations": [],
        "factor_envelope": {},
        "portfolio_pnl": PortfolioPnL(
            total_pnl=0.0,
            by_factor_naive={},
            by_ticker_factor={"A": 0.0},
            by_ticker_periphery={"A": 0.0},
            by_ticker_total={"A": 0.0},
        ).model_dump(),
    }


def test_engine_mode_defaults_legacy_and_rejects_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "project")
    monkeypatch.setenv("VERTEX_AI_LOCATION", "global")
    monkeypatch.setenv("GCS_BUCKET", "bucket")
    monkeypatch.delenv("ENGINE_MODE", raising=False)
    assert load_config().engine_mode == "legacy"

    monkeypatch.setenv("ENGINE_MODE", "invented")
    with pytest.raises(ValueError, match="ENGINE_MODE"):
        load_config()


def test_run_request_has_simple_quant_defaults_and_strict_choices() -> None:
    request = ScenarioRunRequest(scenario_text="A sufficiently detailed scenario")
    assert request.horizon == 21
    assert request.severity == 1.0

    with pytest.raises(ValidationError):
        ScenarioRunRequest(scenario_text="A sufficiently detailed scenario", horizon=20)
    with pytest.raises(ValidationError):
        ScenarioRunRequest(scenario_text="A sufficiently detailed scenario", severity=1.25)


def test_analog_output_is_legacy_compatible_but_supports_all_state_directions() -> None:
    legacy = AnalogSelectionOutput(selected_events=[], reasoning="legacy")
    assert legacy.state_directions == []

    output = AnalogSelectionOutput.model_validate(
        {
            "selected_events": [],
            "reasoning": "quant",
            "state_directions": [
                {"state": state, "direction": "up", "reasoning": "scenario mechanism"}
                for state in ("volatility", "rates", "dollar", "oil", "credit")
            ],
        }
    )
    assert {item.state for item in output.state_directions} == {
        "volatility",
        "rates",
        "dollar",
        "oil",
        "credit",
    }


def test_quant_selector_requires_directions_and_repairs_one_omission(monkeypatch) -> None:
    assert "state_directions" in QuantAnalogSelectionOutput.model_json_schema()["required"]
    selected = [
        {"event_id": "lehman-gfc-2008", "why_relevant": "credit seizure"},
        {"event_id": "covid-crash-2020", "why_relevant": "sudden stop"},
    ]
    responses = iter(
        [
            {"selected_events": selected, "reasoning": "omitted directions"},
            {
                "selected_events": selected,
                "reasoning": "complete",
                "state_directions": [
                    {"state": state, "direction": "neutral", "reasoning": "unconstrained"}
                    for state in ("volatility", "rates", "dollar", "oil", "credit")
                ],
            },
        ]
    )
    calls: list[dict[str, object]] = []
    client = GeminiClient.__new__(GeminiClient)
    client._temperature = 0.0
    client._types = SimpleNamespace(GenerateContentConfig=lambda **kwargs: kwargs)

    def _generate_content(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(text=json.dumps(next(responses)))

    monkeypatch.setattr(client, "_generate_content", _generate_content)
    output = client.select_quant_analogs(
        "A synchronized shutdown",
        [{"event_id": "lehman-gfc-2008"}, {"event_id": "covid-crash-2020"}],
    )

    assert len(calls) == 2
    assert {item.state for item in output.state_directions} == {
        "volatility",
        "rates",
        "dollar",
        "oil",
        "credit",
    }
    assert calls[0]["config"]["response_schema"] is QuantAnalogSelectionOutput


def test_old_scenario_payload_defaults_to_legacy_methodology() -> None:
    result = ScenarioResult.model_validate(_minimal_result_payload())
    assert result.engine_mode == "legacy"
    assert result.methodology == "llm_shock_envelope"
    assert result.historical_model_range is None
    assert result.quant_support is None
    assert result.quant_exposures == {}
    assert result.quant_source_versions == {}


def test_quant_cache_key_covers_engine_horizon_severity_and_spec() -> None:
    base = _cache_kwargs()
    legacy = scenario_cache_key(**base)
    quant = scenario_cache_key(
        **base,
        engine_mode="quant_v2",
        horizon=21,
        severity=1.0,
        engine_spec="quant-spec-a",
    )
    assert quant != legacy
    assert quant != scenario_cache_key(
        **base,
        engine_mode="quant_v2",
        horizon=63,
        severity=1.0,
        engine_spec="quant-spec-a",
    )
    assert quant != scenario_cache_key(
        **base,
        engine_mode="quant_v2",
        horizon=21,
        severity=1.5,
        engine_spec="quant-spec-a",
    )
    assert quant != scenario_cache_key(
        **base,
        engine_mode="quant_v2",
        horizon=21,
        severity=1.0,
        engine_spec="quant-spec-b",
    )


def test_quant_engine_spec_keys_market_cache_semantics() -> None:
    marker = f"market={MARKET_CACHE_VERSION}"
    assert marker in QUANT_ENGINE_SPEC
    changed_spec = QUANT_ENGINE_SPEC.replace(marker, "market=market-cache-future")

    base = _cache_kwargs()
    assert scenario_cache_key(
        **base,
        engine_mode="quant_v2",
        horizon=21,
        severity=1.0,
        engine_spec=QUANT_ENGINE_SPEC,
    ) != scenario_cache_key(
        **base,
        engine_mode="quant_v2",
        horizon=21,
        severity=1.0,
        engine_spec=changed_spec,
    )


def test_prompt_v12_requires_semantic_state_directions_without_numeric_shocks() -> None:
    assert PROMPT_VERSION == "v12"
    assert "volatility" in ANALOG_SELECTION_PROMPT
    assert "credit" in ANALOG_SELECTION_PROMPT
    assert "Do not propose numeric" in ANALOG_SELECTION_PROMPT


def test_quant_result_rejects_factor_adjustment_before_gemini(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "project")
    monkeypatch.setenv("VERTEX_AI_LOCATION", "global")
    monkeypatch.setenv("GCS_BUCKET", "bucket")
    cache = InMemoryCache()
    payload = _minimal_result_payload()
    payload["engine_mode"] = "quant_v2"
    cache.put_json("quant", payload)

    with pytest.raises(RuntimeError, match="joint historical vector"):
        adjust_scenario_shocks(
            "quant",
            overrides={},
            config=load_config(),
            gemini=object(),
            cache=cache,
        )


def test_production_deploy_stays_explicitly_on_legacy_until_promotion() -> None:
    root = Path(__file__).resolve().parent.parent
    assert "ENGINE_MODE=legacy" in (root / "cloudbuild.yaml").read_text(encoding="utf-8")
    assert "# ENGINE_MODE=legacy" in (root / ".env.example").read_text(encoding="utf-8")
