"""Run the LLM-free engine-replay validation harness and regenerate its artifacts.

Replays every (historical event × sample book) pair — vintage betas as of the
event start, the event's realized factor returns as the shock vector — and
compares modeled factor-driven P&L against the book's realized buy-and-hold USD
return. See `app/factors/engine_replay.py` for the methodology and caveats.

Outputs (both fully regenerated, never hand-edited):
  scripts/engine_replay_output.json     — machine-readable pairs + summary + provenance
  docs/engine-replay-validation.md      — human-readable table with the honesty header

Re-run and commit whenever the regression estimator/params, the factor universe,
data/historical_events.yaml, or sample_portfolio_weights.json change — the
embedded provenance strings make staleness visible in review.

Usage:
  uv run python scripts/run_engine_replay.py
  uv run python scripts/run_engine_replay.py --events covid-crash-2020,q4-trade-war-2018
  uv run python scripts/run_engine_replay.py --portfolios defensive_mix --jobs 1 --json-only
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from app.factors.engine_replay import render_markdown, run_engine_replay

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "scripts" / "engine_replay_output.json"
DEFAULT_DOC = REPO_ROOT / "docs" / "engine-replay-validation.md"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", help="comma-separated event ids (default: all)")
    parser.add_argument("--portfolios", help="comma-separated sample keys (default: all)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--doc", type=Path, default=DEFAULT_DOC)
    parser.add_argument("--jobs", type=int, default=4, help="parallel fetch workers")
    parser.add_argument(
        "--json-only", action="store_true", help="write the JSON artifact but not the doc"
    )
    args = parser.parse_args()

    event_ids = [e.strip() for e in args.events.split(",")] if args.events else None
    portfolio_keys = [p.strip() for p in args.portfolios.split(",")] if args.portfolios else None

    pairs, summary = run_engine_replay(
        event_ids=event_ids,
        portfolio_keys=portfolio_keys,
        max_workers=args.jobs,
    )

    payload = {"summary": asdict(summary), "pairs": [asdict(p) for p in pairs]}
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}")

    if not args.json_only:
        args.doc.write_text(render_markdown(pairs, summary), encoding="utf-8")
        print(f"wrote {args.doc}")

    computed = summary.n_computed
    print(
        f"pairs: {summary.n_pairs} ({computed} computed, {summary.n_skipped} skipped) | "
        f"MAE: {summary.mae:.4f} | bias: {summary.bias:+.4f} | "
        f"sign hit-rate: {summary.sign_hit_rate:.0%} | "
        f"pearson r: {summary.pearson_r if summary.pearson_r is not None else 'n/a'}"
        if computed
        else "no pairs computed — see skipped reasons in the JSON"
    )


if __name__ == "__main__":
    main()
