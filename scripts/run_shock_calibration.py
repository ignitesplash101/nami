"""Run the Phase-42 shock-calibration study (paid, capped) and regenerate its artifacts.

Runs the real scenario pipeline in backdated, leave-one-out mode for every event in
data/calibration_prompts.yaml, then scores each run's shocks against realized
outcomes through the same vintage betas (see `app/llm/shock_calibration.py`).

Outputs:
  scripts/shock_calibration_runs.jsonl    — append-only checkpoint, one line per paid run
  scripts/shock_calibration_output.json   — pair scores + summary (fully regenerated)
  docs/shock-calibration.md               — gate verdict and tables (fully regenerated)

Paid calls go straight to Vertex AI, outside the API's daily breaker, so this script
owns its cap (`--budget-usd`, default $10) and resumes from the checkpoint instead
of paying twice. Always start with `--dry-run`.

Usage:
  uv run python scripts/run_shock_calibration.py --dry-run
  uv run python scripts/run_shock_calibration.py --inputs-cache <scratch>/inputs.pkl --reuse-inputs
  uv run python scripts/run_shock_calibration.py --score-only --inputs-cache <scratch>/inputs.pkl --reuse-inputs
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
from dataclasses import asdict
from pathlib import Path

from app.factors.completion_study import gather_inputs
from app.llm.shock_calibration import (
    DEFAULT_BUDGET_USD,
    DEFAULT_PORTFOLIOS,
    EST_COST_PER_RUN_USD,
    execute_runs,
    load_cases,
    plan_runs,
    prewarm_market,
    read_checkpoint,
    render_markdown,
    score_runs,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CHECKPOINT = REPO_ROOT / "scripts" / "shock_calibration_runs.jsonl"
DEFAULT_OUTPUT = REPO_ROOT / "scripts" / "shock_calibration_output.json"
DEFAULT_DOC = REPO_ROOT / "docs" / "shock-calibration.md"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", help="comma-separated event ids (default: every prompt)")
    parser.add_argument("--portfolios", help="comma-separated sample keys (default: all four)")
    parser.add_argument("--budget-usd", type=float, default=DEFAULT_BUDGET_USD)
    parser.add_argument("--max-runs", type=int, help="hard cap on paid runs this invocation")
    parser.add_argument("--jobs", type=int, default=3, help="concurrent pipeline runs")
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--dry-run", action="store_true", help="print the plan; no paid calls")
    parser.add_argument("--score-only", action="store_true", help="score the checkpoint only")
    parser.add_argument("--inputs-cache", type=Path, help="pickle of gathered vintage inputs")
    parser.add_argument("--reuse-inputs", action="store_true", help="load --inputs-cache")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--doc", type=Path, default=DEFAULT_DOC)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # cp1252 consoles

    cases = load_cases()
    if args.events:
        wanted = {e.strip() for e in args.events.split(",")}
        cases = [c for c in cases if c.event_id in wanted]
    keys = (
        [p.strip() for p in args.portfolios.split(",")] if args.portfolios else DEFAULT_PORTFOLIOS
    )
    planned = plan_runs(cases, keys)
    done = {
        (r.event_id, r.portfolio_key, r.sample)
        for r in read_checkpoint(args.checkpoint)
        if r.error is None
    }
    pending = [p for p in planned if p not in done]
    if args.max_runs is not None:
        pending = pending[: max(0, args.max_runs)]
    print(
        f"{len(cases)} events, {len(planned)} planned runs, {len(done)} already done, "
        f"{len(pending)} to run; estimated ≤ ${EST_COST_PER_RUN_USD * len(pending):.2f} "
        f"against a ${args.budget_usd:.2f} cap"
    )
    for case in cases:
        print(f"  {case.event_id}: as-of {case.as_of}")
    if args.dry_run:
        return

    if not args.score_only and pending:
        pending_events = {p[0] for p in pending}
        failures = prewarm_market(
            [c for c in cases if c.event_id in pending_events],
            sorted({p[1] for p in pending}),
        )
        if failures:
            print("market data not ready; refusing to spend:")
            for failure in failures:
                print(f"  {failure}")
            raise SystemExit(2)
        print("market data pre-warmed for every pending run")
        finished = execute_runs(
            cases,
            planned,
            checkpoint=args.checkpoint,
            budget_usd=args.budget_usd,
            max_runs=args.max_runs,
            jobs=args.jobs,
        )
        failed = [r for r in finished if r.error]
        print(
            f"finished {len(finished)} runs ({len(failed)} failed), "
            f"${sum(r.cost_usd for r in finished):.2f} this invocation"
        )

    if args.reuse_inputs:
        if args.inputs_cache is None or not args.inputs_cache.exists():
            raise SystemExit("--reuse-inputs needs an existing --inputs-cache file")
        with args.inputs_cache.open("rb") as handle:
            inputs = pickle.load(handle)  # noqa: S301 — a file written locally by our scripts
    else:
        inputs = gather_inputs(event_ids=[c.event_id for c in cases], portfolio_keys=keys)
        if args.inputs_cache is not None:
            with args.inputs_cache.open("wb") as handle:
                pickle.dump(inputs, handle)

    pairs, summary = score_runs(read_checkpoint(args.checkpoint), inputs)
    payload = {"summary": asdict(summary), "pairs": [asdict(p) for p in pairs]}
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    args.doc.write_text(render_markdown(pairs, summary), encoding="utf-8")
    print(f"wrote {args.output} and {args.doc}")
    verdict = "n/a" if summary.g4_passed is None else ("PASS" if summary.g4_passed else "FAIL")
    print(f"{verdict} G4_magnitudes: {summary.g4_detail}")
    print(f"total spend across all runs: ${summary.spent_usd:.2f}")


if __name__ == "__main__":
    main()
