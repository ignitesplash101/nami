from __future__ import annotations

import pytest

from app.config import load_config


def _set_required_env(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setenv("VERTEX_AI_LOCATION", "global")
    monkeypatch.setenv("GCS_BUCKET", "test-bucket")


def test_load_config_uses_gemini_3_8_defaults(monkeypatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.delenv("VERTEX_MODEL_ID", raising=False)
    monkeypatch.delenv("PRICE_INPUT_PER_MTOK", raising=False)
    monkeypatch.delenv("PRICE_OUTPUT_PER_MTOK", raising=False)

    config = load_config()

    assert config.vertex_model_id == "gemini-3.8-flash"
    assert config.price_input_per_mtok == 1.50
    assert config.price_output_per_mtok == 7.50


@pytest.mark.parametrize("env_name", ["STRUCTURED_THINKING_LEVEL", "SELECTION_THINKING_LEVEL"])
def test_load_config_rejects_minimal_thinking_for_gemini_3_8(monkeypatch, env_name: str) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.delenv("VERTEX_MODEL_ID", raising=False)
    monkeypatch.setenv(env_name, "MINIMAL")

    with pytest.raises(ValueError, match=rf"{env_name}.*LOW.*MEDIUM.*HIGH"):
        load_config()
