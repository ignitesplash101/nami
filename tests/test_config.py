from __future__ import annotations

from app.config import load_config


def test_load_config_uses_gemini_3_7_defaults(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setenv("VERTEX_AI_LOCATION", "global")
    monkeypatch.setenv("GCS_BUCKET", "test-bucket")
    monkeypatch.delenv("VERTEX_MODEL_ID", raising=False)
    monkeypatch.delenv("PRICE_INPUT_PER_MTOK", raising=False)
    monkeypatch.delenv("PRICE_OUTPUT_PER_MTOK", raising=False)

    config = load_config()

    assert config.vertex_model_id == "gemini-3.7-flash"
    assert config.price_input_per_mtok == 1.50
    assert config.price_output_per_mtok == 7.50
