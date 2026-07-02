"""Historical analog matcher — the empirical grounding layer between the LLM and the factor model.

Loads a curated registry of market-stress events from `data/historical_events.yaml`, fetches the
realized total factor return over each event's exact-day window, and aggregates into an empirical
envelope (mean, p10, p90, count) per factor. Phase 4's LLM uses this envelope as a constraint on
proposed factor shocks.
"""

from __future__ import annotations

import functools
import hashlib
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from app.data.market import fetch_daily_prices
from app.factors.universe import FACTORS, factor_name_by_ticker, factor_tickers

DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "data" / "historical_events.yaml"

VALID_TAGS = frozenset(
    {
        "trade-war",
        "pandemic",
        "inflation",
        "geopolitical",
        "banking",
        "energy",
        "central-bank",
        "currency",
        # Phase-22 registry expansion
        "technology",
        "volatility",
        "credit",
        "disaster",
    }
)

MIN_WINDOW_DAYS = 3


@dataclass(frozen=True)
class HistoricalEvent:
    id: str
    name: str
    start_date: date
    end_date: date
    tags: tuple[str, ...]
    description: str


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                None,
                None,
                f"duplicate key: {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def load_events(path: Path | None = None) -> dict[str, HistoricalEvent]:
    """Parse and validate the historical events registry.

    Cached per-path for the lifetime of the process — events are immutable historical
    records, the YAML changes only on deploy, and the cache key includes file path so
    tests using custom registries don't pollute the production entry.

    Raises:
        FileNotFoundError: if the registry file is missing.
        ValueError: if any event is malformed — invalid tag, inverted dates,
            window shorter than MIN_WINDOW_DAYS, missing required field.
        yaml.constructor.ConstructorError: if duplicate event_ids exist.
    """
    return _load_events_cached(path or DEFAULT_REGISTRY_PATH)


@functools.lru_cache(maxsize=8)
def _load_events_cached(path: Path) -> dict[str, HistoricalEvent]:
    with open(path, encoding="utf-8") as f:
        raw = yaml.load(f, Loader=_UniqueKeyLoader)

    if not isinstance(raw, dict) or "events" not in raw:
        raise ValueError(f"{path}: expected top-level 'events:' mapping")

    events: dict[str, HistoricalEvent] = {}
    for event_id, payload in raw["events"].items():
        events[event_id] = _validate_event(event_id, payload)
    return events


def _validate_event(event_id: str, payload: dict[str, Any]) -> HistoricalEvent:
    required = {"name", "start_date", "end_date", "tags", "description"}
    missing = required - payload.keys()
    if missing:
        raise ValueError(f"event {event_id!r}: missing fields {sorted(missing)}")

    start_date = payload["start_date"]
    end_date = payload["end_date"]
    if not isinstance(start_date, date) or not isinstance(end_date, date):
        raise ValueError(f"event {event_id!r}: start_date and end_date must be ISO YYYY-MM-DD")

    if end_date < start_date + timedelta(days=MIN_WINDOW_DAYS):
        raise ValueError(
            f"event {event_id!r}: window too short — end_date must be at least "
            f"{MIN_WINDOW_DAYS} days after start_date (got {start_date} to {end_date})"
        )

    tags = tuple(payload["tags"])
    unknown_tags = set(tags) - VALID_TAGS
    if unknown_tags:
        raise ValueError(
            f"event {event_id!r}: unknown tags {sorted(unknown_tags)}. Valid: {sorted(VALID_TAGS)}"
        )

    return HistoricalEvent(
        id=event_id,
        name=payload["name"],
        start_date=start_date,
        end_date=end_date,
        tags=tags,
        description=payload["description"],
    )


def event_summaries(path: Path | None = None) -> list[dict[str, Any]]:
    """Compact LLM-facing summaries of the full event registry, ordered by
    start_date ascending. Process-cached. Use `summarize_events(filter_events_as_of(...))`
    when backdating to enforce strict no-look-ahead.
    """
    return _event_summaries_cached(path or DEFAULT_REGISTRY_PATH)


@functools.lru_cache(maxsize=8)
def _event_summaries_cached(path: Path) -> list[dict[str, Any]]:
    return summarize_events(load_events(path))


def summarize_events(events: dict[str, HistoricalEvent]) -> list[dict[str, Any]]:
    """Render an event-registry dict to the JSON shape the analog-selection LLM
    expects. Mirrors `event_summaries()` but takes a pre-filtered registry, so
    callers in backdated mode can pass `filter_events_as_of(load_events(), as_of)`
    and the LLM is shown only eligible analogs.
    """
    sorted_events = sorted(events.values(), key=lambda e: e.start_date)
    return [
        {
            "id": e.id,
            "name": e.name,
            "start_date": e.start_date.isoformat(),
            "end_date": e.end_date.isoformat(),
            "tags": list(e.tags),
            "description": e.description,
        }
        for e in sorted_events
    ]


def filter_events_as_of(
    events: dict[str, HistoricalEvent], as_of: date
) -> dict[str, HistoricalEvent]:
    """Strict end-date filter: an event is eligible only if it FULLY completed
    on or before `as_of`. Events still in progress at `as_of` are excluded —
    their windowed-return fetch would otherwise leak post-as-of returns via the
    event's end_date. v1 does not support truncated in-progress events.

    Critical for quant-grade backdating: filtering by `start_date` instead would
    let analogs whose return windows extend past `as_of` into the envelope
    computation.
    """
    return {eid: e for eid, e in events.items() if e.end_date <= as_of}


def fetch_event_returns(event: HistoricalEvent) -> pd.Series:
    """Total factor return over the exact-day event window.

    Returns a Series indexed by FRIENDLY factor name. Factors whose ETFs didn't exist
    in the window appear as NaN (reindexed against the full FACTORS keys after fetch).
    """
    yf_end = event.end_date + timedelta(days=1)
    prices = fetch_daily_prices(
        factor_tickers(),
        start=event.start_date,
        end=yf_end,
    )

    if prices.empty:
        return pd.Series({name: float("nan") for name in FACTORS}, name=event.id)

    total_return = prices.iloc[-1] / prices.iloc[0] - 1.0
    renamed = total_return.rename(index=factor_name_by_ticker())
    full = renamed.reindex(list(FACTORS.keys()))
    full.name = event.id
    return full


def fetch_event_returns_matrix(
    event_ids: list[str],
    registry: dict[str, HistoricalEvent] | None = None,
) -> pd.DataFrame:
    """Events × factors matrix of total returns over each event's exact-day window.

    Index = event_id (input order preserved), columns = friendly factor names.
    NaN where a factor's ETF did not exist in the window. Parallel fetch (≤8
    workers), order-preserving via `executor.map`.

    Raises:
        ValueError: empty or duplicate `event_ids`.
        KeyError: unknown event ids.
    """
    if not event_ids:
        raise ValueError("event_ids must be non-empty")

    seen: set[str] = set()
    duplicates: list[str] = []
    for eid in event_ids:
        if eid in seen:
            duplicates.append(eid)
        seen.add(eid)
    if duplicates:
        raise ValueError(f"duplicate event_ids: {sorted(set(duplicates))}")

    registry = registry if registry is not None else load_events()
    unknown = [eid for eid in event_ids if eid not in registry]
    if unknown:
        raise KeyError(f"unknown event_ids: {unknown}")

    events_to_fetch = [registry[eid] for eid in event_ids]
    if len(events_to_fetch) > 1:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=min(len(events_to_fetch), 8)) as pool:
            rows = list(pool.map(fetch_event_returns, events_to_fetch))
    else:
        rows = [fetch_event_returns(events_to_fetch[0])]
    return pd.DataFrame(rows)


def compute_envelope_from_matrix(returns_matrix: pd.DataFrame) -> pd.DataFrame:
    """Aggregate an events × factors return matrix into the per-factor envelope.

    Returns a DataFrame indexed by friendly factor name with columns:
        mean, p10, p90, count

    Percentiles use pandas' default linear interpolation, NaN-skipping.
    """
    return pd.DataFrame(
        {
            "mean": returns_matrix.mean(axis=0, skipna=True),
            "p10": returns_matrix.quantile(0.10, axis=0),
            "p90": returns_matrix.quantile(0.90, axis=0),
            "count": returns_matrix.count(axis=0),
        }
    )


def compute_envelope(
    event_ids: list[str],
    registry: dict[str, HistoricalEvent] | None = None,
) -> pd.DataFrame:
    """Per-factor empirical distribution across the selected events.

    Returns a DataFrame indexed by friendly factor name with columns:
        mean, p10, p90, count

    `count` < len(event_ids) when some factors are missing for some events (e.g.,
    XLC pre-2018). Downstream (Phase 4 LLM prompt) should down-weight low-count factors.
    Callers that also need the per-event rows (e.g. the shock-extraction payload)
    should call `fetch_event_returns_matrix` + `compute_envelope_from_matrix`
    directly to avoid a duplicate fetch.
    """
    return compute_envelope_from_matrix(fetch_event_returns_matrix(event_ids, registry))


def events_version(path: Path | None = None) -> str:
    """Short (12-char) hash of the events registry file contents. Used in the scenario
    cache key so any edit to the YAML invalidates cached responses. Process-cached."""
    return _events_version_cached(path or DEFAULT_REGISTRY_PATH)


@functools.lru_cache(maxsize=8)
def _events_version_cached(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]
