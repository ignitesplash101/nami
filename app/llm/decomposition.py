"""Decompose a scenario into 2-4 independent sub-narratives via one Gemini call.

Result is cached separately under prefix='decomposition_cache' so the same scenario on
the same day with the same portfolio reuses the split — narrative decomposition is
LLM-driven and not deterministic across runs even at temperature=0.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

from app.data.cache import CacheProtocol
from app.llm.gemini_client import GeminiClient
from app.llm.prompts import PROMPT_VERSION


def decomposition_cache_key(
    *,
    scenario_text: str,
    portfolio_key: str,
    market_date: date,
    model_id: str,
    prompt_version: str,
) -> str:
    payload = json.dumps(
        {
            "scenario_text": scenario_text.strip().lower(),
            "portfolio_key": portfolio_key,
            "market_date": market_date.isoformat(),
            "model_id": model_id,
            "prompt_version": prompt_version,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def decompose_scenario(
    scenario_text: str,
    *,
    client: GeminiClient,
    cache: CacheProtocol,
    market_date: date,
    portfolio_key: str,
    model_id: str,
    ttl_hours: int = 7 * 24,
) -> list[str]:
    """Return 2-4 self-contained sub-narratives. Raises if Gemini returns out-of-range N."""
    key = decomposition_cache_key(
        scenario_text=scenario_text,
        portfolio_key=portfolio_key,
        market_date=market_date,
        model_id=model_id,
        prompt_version=PROMPT_VERSION,
    )

    cached = cache.get_json(key, ttl_hours=ttl_hours)
    if cached is not None and "sub_narratives" in cached:
        sub_narratives = list(cached["sub_narratives"])
    else:
        out = client.decompose(scenario_text)
        sub_narratives = [s.strip() for s in out.sub_narratives if s.strip()]
        cache.put_json(key, {"sub_narratives": sub_narratives})

    n = len(sub_narratives)
    if n < 2 or n > 4:
        raise RuntimeError(
            f"Decomposition returned {n} sub-narratives; must be in [2, 4]. "
            f"Sub-narratives: {sub_narratives!r}"
        )
    return sub_narratives
