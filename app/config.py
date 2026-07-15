from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal, cast

from dotenv import load_dotenv

load_dotenv()

EngineMode = Literal["legacy", "shadow", "quant_v2"]


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
    narrative_shapley_max_workers: int = 4
    log_level: str = "INFO"
    environment: str = "dev"
    # Operational hardening (all optional with safe defaults — local dev / tests
    # need no new env). Rate-limit strings use slowapi's "<count>/<period>" syntax.
    sentry_dsn: str | None = None
    cors_allow_origins: tuple[str, ...] = ()
    rate_limit_default: str = "120/minute"
    rate_limit_llm: str = "10/minute"
    rate_limit_unlock: str = "5/minute"
    unlock_max_failures: int = 10
    unlock_window_seconds: int = 900
    daily_llm_run_cap: int = 500
    daily_llm_cost_cap_usd: float = 25.0
    # Rough list prices (USD per 1M tokens) for the daily-budget breaker. These are
    # for cost ESTIMATION/budgeting only, not billing — keep them conservative.
    price_input_per_mtok: float = 0.30
    price_output_per_mtok: float = 2.50
    engine_mode: EngineMode = "legacy"


def _split_origins(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(origin.strip() for origin in raw.split(",") if origin.strip())


def _engine_mode(raw: str | None) -> EngineMode:
    value = (raw or "legacy").strip().lower()
    if value not in {"legacy", "shadow", "quant_v2"}:
        raise ValueError("ENGINE_MODE must be one of: legacy, shadow, quant_v2")
    return cast(EngineMode, value)


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
        narrative_shapley_max_workers=int(os.getenv("NARRATIVE_SHAPLEY_MAX_WORKERS", "4")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        environment=os.getenv("ENVIRONMENT", "dev"),
        sentry_dsn=os.getenv("SENTRY_DSN") or None,
        cors_allow_origins=_split_origins(os.getenv("CORS_ALLOW_ORIGINS")),
        rate_limit_default=os.getenv("RATE_LIMIT_DEFAULT", "120/minute"),
        rate_limit_llm=os.getenv("RATE_LIMIT_LLM", "10/minute"),
        rate_limit_unlock=os.getenv("RATE_LIMIT_UNLOCK", "5/minute"),
        unlock_max_failures=int(os.getenv("UNLOCK_MAX_FAILURES", "10")),
        unlock_window_seconds=int(os.getenv("UNLOCK_WINDOW_SECONDS", "900")),
        daily_llm_run_cap=int(os.getenv("DAILY_LLM_RUN_CAP", "500")),
        daily_llm_cost_cap_usd=float(os.getenv("DAILY_LLM_COST_CAP_USD", "25.0")),
        price_input_per_mtok=float(os.getenv("PRICE_INPUT_PER_MTOK", "0.30")),
        price_output_per_mtok=float(os.getenv("PRICE_OUTPUT_PER_MTOK", "2.50")),
        engine_mode=_engine_mode(os.getenv("ENGINE_MODE")),
    )
