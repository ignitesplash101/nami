"""Admin usage metrics: aggregate the access log the app already writes.

Design note (the whole reason this module looks the way it does): nami stores
NOTHING new to produce these numbers. Every request already emits one structured
`nami.access` line carrying `path`, `method`, `status`, `latency_ms`, `ip_hash`
and — since the metrics work — `access_mode`, `scenario_key`, `portfolio_key`,
`cache_hit` and `synthetic`. This module reads those lines back out of Cloud
Logging and aggregates them in memory. There is no new collection, no new
identifier, and no write on the public request path.

`ip_hash` is used ONLY as a cardinality input and is never returned to a client.
Its salt is a static, non-secret module constant over a 32-bit IPv4 space, so the
hash is pseudonymous, not anonymous — aggregate and discard.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

# Cloud Logging is paged; this bounds a single dashboard query. When it bites, the
# response says so rather than silently reporting a partial window as if complete.
MAX_LOG_ENTRIES = 20_000

# `/api/scenarios/run-stream` logs at first byte, not at completion, so its latency
# is time-to-first-byte (milliseconds) rather than the ~50s run. Including it would
# report a fast lie, so latency stats exclude it — disclosed in the payload.
LATENCY_EXCLUDED_PATHS = frozenset({"/api/scenarios/run-stream", "/api/scenarios/decompose-stream"})

RUN_PATHS = frozenset({"/api/scenarios/run", "/api/scenarios/run-stream"})


@dataclass
class LogEntry:
    """One access-log line, already parsed out of the Cloud Logging payload."""

    day: str
    path: str
    status: int
    latency_ms: float
    ip_hash: str
    access_mode: str | None = None
    scenario_key: str | None = None
    portfolio_key: str | None = None
    cache_hit: bool | None = None
    synthetic: bool = False


@dataclass
class MetricsWindow:
    """Aggregated view over a window of access-log lines. JSON-safe throughout."""

    days: int
    entries_scanned: int
    truncated: bool
    synthetic_excluded: int
    daily: list[dict] = field(default_factory=list)
    top_paths: list[dict] = field(default_factory=list)
    scenario_runs: list[dict] = field(default_factory=list)
    portfolio_runs: list[dict] = field(default_factory=list)
    status_counts: dict[str, int] = field(default_factory=dict)
    top_errors: list[dict] = field(default_factory=list)
    totals: dict = field(default_factory=dict)


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 1)
    # Nearest-rank; deliberately simple and dependency-free at this sample size.
    index = min(len(ordered) - 1, max(0, round(pct / 100 * len(ordered)) - 1))
    return round(ordered[index], 1)


def aggregate(entries: list[LogEntry], *, days: int, include_synthetic: bool) -> MetricsWindow:
    """Roll access-log lines into the dashboard payload.

    `include_synthetic` controls whether the scheduled pre-warm's own traffic is
    counted. It is excluded by default because ~16 machine-driven runs every
    weekday would otherwise dominate every number — but the count of what was
    dropped is reported, so the exclusion is visible rather than silent.
    """
    scanned = len(entries)
    synthetic_total = sum(1 for e in entries if e.synthetic)
    if not include_synthetic:
        entries = [e for e in entries if not e.synthetic]

    per_day: dict[str, dict] = defaultdict(
        lambda: {"requests": 0, "visitors": set(), "runs": 0, "errors": 0}
    )
    paths: Counter[str] = Counter()
    scenarios: Counter[str] = Counter()
    portfolios: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    errors: Counter[tuple[str, int]] = Counter()
    latencies: list[float] = []
    visitors_all: set[str] = set()
    mode_counts: Counter[str] = Counter()
    cache_hits = 0
    cache_total = 0

    for entry in entries:
        bucket = per_day[entry.day]
        bucket["requests"] += 1
        bucket["visitors"].add(entry.ip_hash)
        visitors_all.add(entry.ip_hash)
        paths[entry.path] += 1
        statuses[str(entry.status)] += 1
        if entry.status >= 400:
            bucket["errors"] += 1
            errors[(entry.path, entry.status)] += 1
        if entry.path not in LATENCY_EXCLUDED_PATHS:
            latencies.append(entry.latency_ms)
        if entry.path in RUN_PATHS:
            bucket["runs"] += 1
            if entry.scenario_key:
                scenarios[entry.scenario_key] += 1
            if entry.portfolio_key:
                portfolios[entry.portfolio_key] += 1
            if entry.access_mode:
                mode_counts[entry.access_mode] += 1
            if entry.cache_hit is not None:
                cache_total += 1
                cache_hits += int(entry.cache_hit)

    daily = [
        {
            "day": day,
            "requests": data["requests"],
            "unique_visitors": len(data["visitors"]),
            "runs": data["runs"],
            "errors": data["errors"],
        }
        for day, data in sorted(per_day.items())
    ]

    return MetricsWindow(
        days=days,
        entries_scanned=scanned,
        truncated=scanned >= MAX_LOG_ENTRIES,
        synthetic_excluded=0 if include_synthetic else synthetic_total,
        daily=daily,
        top_paths=[{"path": p, "requests": n} for p, n in paths.most_common(12)],
        scenario_runs=[{"key": k, "runs": n} for k, n in scenarios.most_common()],
        portfolio_runs=[{"key": k, "runs": n} for k, n in portfolios.most_common()],
        status_counts=dict(sorted(statuses.items())),
        top_errors=[
            {"path": path, "status": status, "count": n}
            for (path, status), n in errors.most_common(10)
        ],
        totals={
            "requests": sum(d["requests"] for d in daily),
            # Distinct across the WHOLE window, so it is deliberately NOT the sum of
            # the per-day figures — one visitor returning on three days counts once.
            "unique_visitors": len(visitors_all),
            "runs": sum(d["runs"] for d in daily),
            "errors": sum(d["errors"] for d in daily),
            "visitor_runs": mode_counts.get("visitor", 0),
            "admin_runs": mode_counts.get("admin", 0),
            "cache_hits": cache_hits,
            "cache_observed": cache_total,
            "cache_hit_rate": round(cache_hits / cache_total, 4) if cache_total else None,
            "latency_p50_ms": _percentile(latencies, 50),
            "latency_p95_ms": _percentile(latencies, 95),
            "latency_excluded_paths": sorted(LATENCY_EXCLUDED_PATHS),
        },
    )


def parse_entry(payload: dict, timestamp: datetime | None) -> LogEntry | None:
    """Build a `LogEntry` from one Cloud Logging jsonPayload, or None if unusable.

    Tolerant by design: a line missing the newer tag fields (anything logged before
    this feature shipped) still counts toward traffic, it just carries no
    scenario/mode dimension.
    """
    path = payload.get("path")
    if not path or payload.get("message") != "request":
        return None
    when = timestamp or datetime.now(UTC)
    try:
        status = int(payload.get("status", 0))
    except (TypeError, ValueError):
        status = 0
    try:
        latency = float(payload.get("latency_ms", 0.0))
    except (TypeError, ValueError):
        latency = 0.0
    return LogEntry(
        day=when.astimezone(UTC).date().isoformat(),
        path=str(path),
        status=status,
        latency_ms=latency,
        ip_hash=str(payload.get("ip_hash") or "unknown"),
        access_mode=payload.get("access_mode"),
        scenario_key=payload.get("scenario_key"),
        portfolio_key=payload.get("portfolio_key"),
        cache_hit=payload.get("cache_hit"),
        synthetic=bool(payload.get("synthetic")),
    )


def fetch_access_entries(
    project_id: str, days: int, *, limit: int = MAX_LOG_ENTRIES
) -> list[LogEntry]:
    """Read this service's access lines back out of Cloud Logging.

    Local import so the logging client is never paid for at cold start — the same
    posture `shap` gets in `app/factors/attribution.py`. Requires
    `roles/logging.viewer` on the runtime service account; without it the caller
    sees the API's PermissionDenied and surfaces a coded error rather than a 500.

    Newest-first with a hard `limit`, so a busy window degrades to "the most recent
    N requests" — which `aggregate` then reports as truncated rather than passing
    off as complete.
    """
    from google.cloud import logging as cloud_logging

    client = cloud_logging.Client(project=project_id)
    entries: list[LogEntry] = []
    for record in client.list_entries(
        filter_=log_filter(days),
        order_by=cloud_logging.DESCENDING,
        page_size=1000,
    ):
        payload = record.payload
        if not isinstance(payload, dict):
            continue
        parsed = parse_entry(payload, record.timestamp)
        if parsed is not None:
            entries.append(parsed)
        if len(entries) >= limit:
            break
    return entries


def log_filter(days: int, *, now: datetime | None = None) -> str:
    """Cloud Logging filter selecting this service's access lines in the window.

    `timestamp` must be an RFC3339 literal — the API has no relative-time syntax
    (that is a `gcloud --freshness` convenience, not a filter feature).
    """
    start = (now or datetime.now(UTC)) - timedelta(days=days)
    return (
        'resource.type="cloud_run_revision" '
        'AND jsonPayload.logger="nami.access" '
        f'AND timestamp>="{start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}"'
    )
