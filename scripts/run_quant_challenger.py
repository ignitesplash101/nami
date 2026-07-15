"""Evaluate a paired offline legacy-versus-Quant V2 challenger dataset.

Input is either a JSON list of ChallengerCase objects or ``{"cases": [...]}``.
The command never calls Gemini, FRED, Yahoo, or the French Data Library.

Usage:
  uv run python scripts/run_quant_challenger.py --input cases.json
  uv run python scripts/run_quant_challenger.py --input cases.json --fail-on-gate
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.factors.quant_challenger import ChallengerCase, evaluate_challenger

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "scripts" / "quant_challenger_output.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="paired challenger cases JSON")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--fail-on-gate",
        action="store_true",
        help="exit non-zero unless every promotion gate passes",
    )
    args = parser.parse_args()

    raw = json.loads(args.input.read_text(encoding="utf-8"))
    rows = raw["cases"] if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        raise ValueError("Challenger input must be a JSON list or an object with a cases list")
    report = evaluate_challenger([ChallengerCase.model_validate(row) for row in rows])
    args.output.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8"
    )

    verdict = "PROMOTE" if report.promote else "KEEP LEGACY"
    print(f"{verdict}: {report.n_cases} paired cases")
    for gate in report.gates:
        print(f"{'PASS' if gate.passed else 'FAIL'} {gate.key}: {gate.detail}")
    print(f"wrote {args.output}")
    if args.fail_on_gate and not report.promote:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
