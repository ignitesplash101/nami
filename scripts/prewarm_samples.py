"""Warm the scenario cache for every visitor-reachable sample combination.

WHY: `scenario_cache_key` includes the effective NYSE date, which rolls at 16:00
ET. Every sample scenario x sample portfolio therefore goes cold every trading
day, and whoever opens the app first each morning waits ~53s for a full Gemini
chain. Running this just after the close means every visitor gets the ~0.4s
cached path instead.

COST: one cache-miss run per combination (~$0.08 at 2026-07 list prices), so the
current 4x4 matrix is ~$1.30 per trading day. That is genuinely ADDITIONAL spend,
not reallocated — visitors may also submit free scenario text, so the sample
matrix is not a cost ceiling. Trim `--limit` (or the sample sets) if it matters.
Well inside the 500/day run cap and the $25/day cost breaker either way.

Deliberately stdlib-only and endpoint-driven: it does exactly what a visitor does
against the already-public endpoint, so it needs no repo install, no GCP
credentials, and no new authenticated surface on the service.

On a US market holiday the effective date does not advance, so this hits the
existing entries and costs nothing — no holiday calendar needed.

Usage:
  python scripts/prewarm_samples.py --base-url https://<service-host>
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

# A cache miss is a full Gemini chain; the server's own request timeout is 900s.
REQUEST_TIMEOUT_SECONDS = 300

# Marks every request this job makes so the admin metrics dashboard can exclude
# it. Without it the ~16 weekday warms are indistinguishable from real visitors
# and would dominate the traffic and feature-usage numbers. Reporting label only.
SYNTHETIC_HEADER = "X-Nami-Synthetic"


def _get(url: str) -> object:
    request = urllib.request.Request(url, headers={SYNTHETIC_HEADER: "1"})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 — https literal
        return json.loads(response.read())


def _post(url: str, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", SYNTHETIC_HEADER: "1"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:  # noqa: S310
        return response.status, json.loads(response.read())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="service origin, no trailing slash")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="warm at most N combinations (0 = all). Use to cap spend.",
    )
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    # Enumerate from the live API rather than hard-coding, so adding a sample
    # scenario can never silently leave a cold combination behind.
    scenarios = _get(f"{base}/api/scenarios/samples")
    portfolios = _get(f"{base}/api/portfolios/samples")
    combos = [
        (s["key"], p["key"])
        for s in scenarios  # type: ignore[union-attr]
        for p in portfolios  # type: ignore[union-attr]
    ]
    if args.limit:
        combos = combos[: args.limit]

    print(f"warming {len(combos)} combination(s) against {base}", flush=True)
    failures: list[str] = []
    for index, (scenario_key, portfolio_key) in enumerate(combos, start=1):
        label = f"{scenario_key} x {portfolio_key}"
        started = time.perf_counter()
        try:
            # Sequential on purpose: ~1 request/minute stays far inside the
            # 10/minute per-IP limit and never contends with real traffic.
            status, body = _post(
                f"{base}/api/scenarios/run",
                {"sample_scenario_key": scenario_key, "portfolio_key": portfolio_key},
            )
            elapsed = time.perf_counter() - started
            pnl = body.get("result", {}).get("portfolio_pnl", {}).get("total_pnl")
            # A fast response means it was already warm; a slow one means this run
            # is what warmed it. Both are successes worth distinguishing in the log.
            state = "already warm" if elapsed < 5 else "warmed"
            print(
                f"[{index}/{len(combos)}] {label}: {status} {state} "
                f"in {elapsed:.1f}s (total_pnl={pnl})",
                flush=True,
            )
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:200]
            print(f"[{index}/{len(combos)}] {label}: HTTP {exc.code} {detail}", flush=True)
            failures.append(f"{label} (HTTP {exc.code})")
        except Exception as exc:  # noqa: BLE001 — report and keep warming the rest
            print(f"[{index}/{len(combos)}] {label}: {type(exc).__name__} {exc}", flush=True)
            failures.append(f"{label} ({type(exc).__name__})")

    if failures:
        # Fail loudly: a silently-broken warm is indistinguishable from having no
        # warm at all, which is exactly the state this exists to fix.
        print(f"\nFAILED {len(failures)}/{len(combos)}: {', '.join(failures)}", flush=True)
        return 1
    print(f"\nAll {len(combos)} combination(s) warm.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
