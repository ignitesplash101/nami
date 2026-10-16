"""Run the LLM-free completion study and regenerate its artifacts.

For every (historical event × sample book) pair, reduce the event to a few
anchored factor moves and compare how much of the book's realized return each
completion variant recovers (see `app/factors/completion_study.py`).

Outputs (both fully regenerated, never hand-edited):
  scripts/completion_study_output.json   — pairs + summary + provenance
  docs/completion-study.md               — gates, tables, and the honesty header

The network stage (prices) and the pure evaluation are separate: pass
`--inputs-cache <path>` to pickle the gathered inputs, then `--reuse-inputs` to
re-run the evaluation without touching the market-data provider (back-to-back
full fetches rate-limit it — see docs/agents/engine.md).

Usage:
  uv run python scripts/run_completion_study.py
  uv run python scripts/run_completion_study.py --inputs-cache <scratch>/inputs.pkl
  uv run python scripts/run_completion_study.py --inputs-cache <scratch>/inputs.pkl --reuse-inputs
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
from dataclasses import asdict
from pathlib import Path

from app.factors.completion_study import (
    DEFAULT_BOOTSTRAP,
    DEFAULT_SEED,
    evaluate,
    gather_inputs,
    render_markdown,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "scripts" / "completion_study_output.json"
DEFAULT_DOC = REPO_ROOT / "docs" / "completion-study.md"
REPLAY_ARTIFACT = REPO_ROOT / "scripts" / "engine_replay_output.json"


def _replay_reference() -> dict[tuple[str, str], float]:
    if not REPLAY_ARTIFACT.exists():
        return {}
    payload = json.loads(REPLAY_ARTIFACT.read_text(encoding="utf-8"))
    return {
        (row["event_id"], row["portfolio_key"]): float(row["modeled_pnl"])
        for row in payload.get("pairs", [])
        if row.get("modeled_pnl") is not None
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", help="comma-separated event ids (default: all)")
    parser.add_argument("--portfolios", help="comma-separated sample keys (default: all)")
    parser.add_argument("--jobs", type=int, default=4, help="parallel fetch workers")
    parser.add_argument("--bootstrap", type=int, default=DEFAULT_BOOTSTRAP)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--inputs-cache", type=Path, help="pickle path for gathered inputs")
    parser.add_argument(
        "--reuse-inputs", action="store_true", help="load --inputs-cache instead of fetching"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--doc", type=Path, default=DEFAULT_DOC)
    parser.add_argument(
        "--json-only", action="store_true", help="write the JSON artifact but not the doc"
    )
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # cp1252 consoles

    if args.reuse_inputs:
        if args.inputs_cache is None or not args.inputs_cache.exists():
            raise SystemExit("--reuse-inputs needs an existing --inputs-cache file")
        with args.inputs_cache.open("rb") as handle:
            inputs = pickle.load(handle)  # noqa: S301 — a file this script wrote locally
    else:
        event_ids = [e.strip() for e in args.events.split(",")] if args.events else None
        keys = [p.strip() for p in args.portfolios.split(",")] if args.portfolios else None
        inputs = gather_inputs(event_ids=event_ids, portfolio_keys=keys, max_workers=args.jobs)
        if args.inputs_cache is not None:
            args.inputs_cache.parent.mkdir(parents=True, exist_ok=True)
            with args.inputs_cache.open("wb") as handle:
                pickle.dump(inputs, handle)
            print(f"cached inputs at {args.inputs_cache}")

    pairs, summary = evaluate(
        inputs,
        bootstrap=args.bootstrap,
        seed=args.seed,
        replay_reference=_replay_reference(),
    )
    payload = {"summary": asdict(summary), "pairs": [asdict(p) for p in pairs]}
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}")
    if not args.json_only:
        args.doc.write_text(render_markdown(pairs, summary), encoding="utf-8")
        print(f"wrote {args.doc}")
    print(f"{summary.n_computed}/{summary.n_pairs} pairs computed, {summary.n_common} gated")
    for gate in summary.gates:
        print(f"{'PASS' if gate.passed else 'FAIL'} {gate.key}: {gate.detail}")


if __name__ == "__main__":
    main()
