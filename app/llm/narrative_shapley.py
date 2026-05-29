"""Fixed-context shock attribution: per-sub-narrative Shapley values.

Decomposes a scenario into N sub-narratives (2 ≤ N ≤ 4) and computes the exact Shapley
value of each under the payoff v(S) := total_pnl(run_scenario(" ".join(S))). Each subset
run is **fixed-context**: it reuses the SOURCE scenario's analog set (`pinned_event_ids`)
and the analog-only narrative path (no Google re-grounding), so the only thing varying
across subsets is the shock proposal for that fragment text. This makes v(S) deterministic
(modulo temperature) and reproducible — versus re-selecting analogs + re-grounding per
subset, which was noisy and news-dependent.

This is decomposition SENSITIVITY, not a causal decomposition: it measures the marginal
shock each theme adds WITHIN the original analog context. Frame it as illustrative in UI
and docs.

Lives OUTSIDE `run_scenario` (which it calls). Putting it inside would invite recursion
and control-flow confusion.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from math import factorial

from app.config import Config
from app.data.cache import CacheProtocol
from app.data.sample_portfolios import Portfolio
from app.llm.decomposition import decompose_scenario
from app.llm.gemini_client import GeminiClient
from app.llm.scenario import run_scenario
from app.llm.schemas import (
    NarrativeContribution,
    NarrativeShapleyResult,
    ScenarioResult,
)


def compute_narrative_shapley(
    original_result: ScenarioResult,
    *,
    config: Config,
    gemini: GeminiClient,
    cache: CacheProtocol,
    decomposition_cache: CacheProtocol,
    market_date: date,
    progress: Callable[[int, int], None] | None = None,
    sub_narratives_override: list[str] | None = None,
) -> ScenarioResult:
    """Run 2^N subset scenarios, compute exact narrative Shapley, return a new
    ScenarioResult with `narrative_shapley` attached via `model_copy(update=...)`.

    Empty-subset payoff v(∅) := 0 — no narrative → no pipeline → no P&L move.

    `sub_narratives_override` is for tests; in production it stays None and the
    decomposer is called.
    """
    if sub_narratives_override is not None:
        sub_narratives = list(sub_narratives_override)
    else:
        sub_narratives = decompose_scenario(
            original_result.scenario_text,
            client=gemini,
            cache=decomposition_cache,
            market_date=market_date,
            portfolio_key=original_result.portfolio_key,
            model_id=config.vertex_model_id,
        )
    N = len(sub_narratives)
    if N < 2 or N > 4:
        raise RuntimeError(
            f"Narrative Shapley requires 2-4 sub-narratives; got {N}: {sub_narratives!r}"
        )

    portfolio = Portfolio(
        name=original_result.portfolio_name,
        description="reconstructed for narrative decomposition",
        holdings=original_result.portfolio_holdings,
    )

    subset_pnls: dict[int, float] = {0: 0.0}
    total_subsets = 2**N
    non_empty_count = total_subsets - 1

    max_workers = max(1, min(config.narrative_shapley_max_workers, non_empty_count))

    # Fixed-context attribution: pin the SOURCE scenario's analog set across every
    # subset and skip per-subset Google re-grounding, so the only thing that varies
    # is the shock proposal for that sub-narrative text. This makes the payoff
    # v(S) deterministic (vs. re-selecting analogs + re-grounding per subset). Falls
    # back to per-subset selection if the source carried no event ids (old cache).
    pinned_ids = original_result.selected_event_ids or None

    def _run_one(mask: int) -> float:
        included = [sub_narratives[i] for i in range(N) if mask & (1 << i)]
        subset_text = " ".join(included)
        sub_result = run_scenario(
            subset_text,
            portfolio,
            config=config,
            gemini=gemini,
            cache=cache,
            market_date=market_date,
            pinned_event_ids=pinned_ids,
        )
        return float(sub_result.portfolio_pnl.total_pnl)

    # Submit all subsets to the pool, then drain via `as_completed` so the progress
    # callback fires from the main thread (Streamlit's `st.progress` is not safe to
    # call from worker threads; the FastAPI SSE/WebSocket replacement has the same
    # requirement). `subset_pnls` is keyed by mask, not by completion order, so the
    # downstream Shapley math is deterministic regardless of how the pool drained.
    progress_lock = threading.Lock()
    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_mask = {pool.submit(_run_one, mask): mask for mask in range(1, total_subsets)}
        for future in as_completed(future_to_mask):
            mask = future_to_mask[future]
            subset_pnls[mask] = future.result()
            with progress_lock:
                done += 1
                if progress is not None:
                    progress(done, non_empty_count)

    contributions: list[NarrativeContribution] = []
    full_pnl = subset_pnls[total_subsets - 1]
    for i in range(N):
        phi = 0.0
        for s_mask in range(total_subsets):
            if s_mask & (1 << i):
                continue
            s = bin(s_mask).count("1")
            w = factorial(s) * factorial(N - s - 1) / factorial(N)
            phi += w * (subset_pnls[s_mask | (1 << i)] - subset_pnls[s_mask])
        relative = (phi / abs(full_pnl)) if full_pnl else 0.0
        contributions.append(
            NarrativeContribution(
                narrative_index=i,
                narrative_text=sub_narratives[i],
                shapley_value=float(phi),
                relative_contribution=float(relative),
            )
        )

    nsr = NarrativeShapleyResult(
        sub_narratives=sub_narratives,
        contributions=contributions,
        subset_pnls={f"{mask:0{N}b}": p for mask, p in subset_pnls.items()},
        total_pnl=float(full_pnl),
        n_subsets_evaluated=total_subsets,
    )
    return original_result.model_copy(update={"narrative_shapley": nsr})
