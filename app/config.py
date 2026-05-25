from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    google_cloud_project: str
    vertex_ai_location: str
    gcs_bucket: str
    google_application_credentials: str | None = None
    vertex_model_id: str = "gemini-3.5-flash"
    llm_temperature: float = 0.0
    market_data_cache_ttl_hours: int = 24
    llm_cache_ttl_days: int = 7
    beta_lookback_weeks: int = 156
    ridge_alpha: float = 0.1
    log_level: str = "INFO"
    environment: str = "dev"


def load_config() -> Config:
    required = ("GOOGLE_CLOUD_PROJECT", "VERTEX_AI_LOCATION", "GCS_BUCKET")
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Copy .env.example to .env and populate the required values."
        )

    return Config(
        google_cloud_project=os.environ["GOOGLE_CLOUD_PROJECT"],
        vertex_ai_location=os.environ["VERTEX_AI_LOCATION"],
        gcs_bucket=os.environ["GCS_BUCKET"],
        google_application_credentials=os.getenv("GOOGLE_APPLICATION_CREDENTIALS"),
        vertex_model_id=os.getenv("VERTEX_MODEL_ID", "gemini-3.5-flash"),
        llm_temperature=float(os.getenv("LLM_TEMPERATURE", "0")),
        market_data_cache_ttl_hours=int(os.getenv("MARKET_DATA_CACHE_TTL_HOURS", "24")),
        llm_cache_ttl_days=int(os.getenv("LLM_CACHE_TTL_DAYS", "7")),
        beta_lookback_weeks=int(os.getenv("BETA_LOOKBACK_WEEKS", "156")),
        ridge_alpha=float(os.getenv("RIDGE_ALPHA", "0.1")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        environment=os.getenv("ENVIRONMENT", "dev"),
    )
