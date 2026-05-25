"""Cache-key derivation for `app.llm.scenario.run_scenario`.

The key hashes EVERY input that could change the response semantically: scenario text,
portfolio identity AND weights, the market date, the LLM model id, the prompt version,
the factor universe version, and the events registry version. Bumping any of these
invalidates cache cleanly — same tickers with different weights, or a prompt rewrite,
or a model swap, all produce distinct cache entries.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date


def scenario_cache_key(
    *,
    scenario_text: str,
    portfolio_key: str,
    portfolio_holdings: dict[str, float],
    market_date: date,
    model_id: str,
    prompt_version: str,
    factor_universe_version: str,
    events_version: str,
) -> str:
    """SHA256 hex digest of normalized inputs."""
    payload = json.dumps(
        {
            "scenario_text": scenario_text.strip().lower(),
            "portfolio_key": portfolio_key,
            "portfolio_holdings": sorted((t, round(w, 6)) for t, w in portfolio_holdings.items()),
            "market_date": market_date.isoformat(),
            "model_id": model_id,
            "prompt_version": prompt_version,
            "factor_universe_version": factor_universe_version,
            "events_version": events_version,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
