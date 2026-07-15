"""Versioned public-data adapters used by the optional Quant V2 engine.

The adapters keep network I/O at the boundary, validate downloaded structures,
and persist exact-source provenance beside cached parquet frames.  Callers may
inject both the byte fetcher and the cache, which keeps the numerical engine and
its tests independent of external services.
"""

from __future__ import annotations

import contextlib
import csv
import hashlib
import io
import json
import re
import urllib.request
import zipfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import numpy as np
import pandas as pd

from app.data.quant_cache import get_public_data_cache

PUBLIC_DATA_CACHE_TTL_HOURS = 24 * 30
PUBLIC_DATA_CACHE_VERSION = "public-quant-v1"

_SOURCE_DATASET_COLUMN = "__nami_source_dataset"
_SOURCE_URL_COLUMN = "__nami_source_url"
_SOURCE_SHA_COLUMN = "__nami_source_sha256"
_SOURCE_RETRIEVED_COLUMN = "__nami_source_retrieved_at"
_SOURCE_COLUMNS = (
    _SOURCE_DATASET_COLUMN,
    _SOURCE_URL_COLUMN,
    _SOURCE_SHA_COLUMN,
    _SOURCE_RETRIEVED_COLUMN,
)


class FrameCacheProtocol(Protocol):
    def get(self, key: str, ttl_hours: int = ...) -> pd.DataFrame | None: ...

    def put(self, key: str, frame: pd.DataFrame) -> None: ...


@dataclass(frozen=True)
class ResearchDatasetSpec:
    dataset_id: str
    url: str
    columns: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ObservationDatasetSpec:
    dataset_id: str
    url: str
    value_column: str
    output_column: str
    scale: float = 1.0


@dataclass(frozen=True)
class SourceVersion:
    dataset_id: str
    url: str
    sha256: str
    retrieved_at: datetime


@dataclass(frozen=True)
class PublicDataset:
    frame: pd.DataFrame
    source: SourceVersion


@dataclass(frozen=True)
class QuantPublicInputs:
    regional_factors: dict[str, pd.DataFrame]
    us_industries: pd.DataFrame
    state_levels: pd.DataFrame
    sources: dict[str, SourceVersion]


_FIVE_FACTOR_COLUMNS = (
    ("Mkt-RF", "MKT_RF"),
    ("SMB", "SMB"),
    ("HML", "HML"),
    ("RMW", "RMW"),
    ("CMA", "CMA"),
    ("RF", "RF"),
)
# The international/regional daily files label momentum "WML" (winners minus
# losers); normalize that public-data label to the engine's stable MOM key.
_MOMENTUM_COLUMNS = (("WML", "MOM"),)
_INDUSTRY_COLUMNS = tuple(
    (name, name)
    for name in (
        "NoDur",
        "Durbl",
        "Manuf",
        "Enrgy",
        "Chems",
        "BusEq",
        "Telcm",
        "Utils",
        "Shops",
        "Hlth",
        "Money",
        "Other",
    )
)

_RESEARCH_BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp"

REGION_RESEARCH_SPECS: dict[str, tuple[ResearchDatasetSpec, ResearchDatasetSpec]] = {
    "generic": (
        ResearchDatasetSpec(
            "developed_five_daily",
            f"{_RESEARCH_BASE}/Developed_5_Factors_Daily_CSV.zip",
            _FIVE_FACTOR_COLUMNS,
        ),
        ResearchDatasetSpec(
            "developed_momentum_daily",
            f"{_RESEARCH_BASE}/Developed_Mom_Factor_Daily_CSV.zip",
            _MOMENTUM_COLUMNS,
        ),
    ),
    "developed_ex_us": (
        ResearchDatasetSpec(
            "developed_ex_us_five_daily",
            f"{_RESEARCH_BASE}/Developed_ex_US_5_Factors_Daily_CSV.zip",
            _FIVE_FACTOR_COLUMNS,
        ),
        ResearchDatasetSpec(
            "developed_ex_us_momentum_daily",
            f"{_RESEARCH_BASE}/Developed_ex_US_Mom_Factor_Daily_CSV.zip",
            _MOMENTUM_COLUMNS,
        ),
    ),
    "japan": (
        ResearchDatasetSpec(
            "japan_five_daily",
            f"{_RESEARCH_BASE}/Japan_5_Factors_Daily_CSV.zip",
            _FIVE_FACTOR_COLUMNS,
        ),
        ResearchDatasetSpec(
            "japan_momentum_daily",
            f"{_RESEARCH_BASE}/Japan_Mom_Factor_Daily_CSV.zip",
            _MOMENTUM_COLUMNS,
        ),
    ),
    "north_america": (
        ResearchDatasetSpec(
            "north_america_five_daily",
            f"{_RESEARCH_BASE}/North_America_5_Factors_Daily_CSV.zip",
            _FIVE_FACTOR_COLUMNS,
        ),
        ResearchDatasetSpec(
            "north_america_momentum_daily",
            f"{_RESEARCH_BASE}/North_America_Mom_Factor_Daily_CSV.zip",
            _MOMENTUM_COLUMNS,
        ),
    ),
}

US_INDUSTRY_SPEC = ResearchDatasetSpec(
    "us_12_industries_daily",
    f"{_RESEARCH_BASE}/12_Industry_Portfolios_Daily_CSV.zip",
    _INDUSTRY_COLUMNS,
)

OBSERVATION_SPECS: dict[str, ObservationDatasetSpec] = {
    "vix": ObservationDatasetSpec(
        "vix_close",
        "https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS",
        "VIXCLS",
        "VIX",
    ),
    "yield_10y": ObservationDatasetSpec(
        "us_10y_yield",
        "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10",
        "DGS10",
        "US_10Y_YIELD",
        scale=0.01,
    ),
    "dollar": ObservationDatasetSpec(
        "broad_dollar",
        "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTWEXBGS",
        "DTWEXBGS",
        "BROAD_DOLLAR",
    ),
    "oil": ObservationDatasetSpec(
        "wti_spot",
        "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILWTICO",
        "DCOILWTICO",
        "WTI",
    ),
}


def source_sha256(raw: bytes) -> str:
    """Return the full SHA-256 of the exact downloaded response bytes."""
    return hashlib.sha256(raw).hexdigest()


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _single_csv_member(raw: bytes) -> bytes:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if len(members) != 1:
                raise ValueError("research archive must contain exactly one CSV member")
            return archive.read(members[0])
    except zipfile.BadZipFile as exc:
        raise ValueError("research response is not a valid ZIP archive") from exc


def _research_table(csv_bytes: bytes, required: tuple[str, ...]) -> pd.DataFrame:
    lines = _decode(csv_bytes).splitlines()
    header_index: int | None = None
    for index, line in enumerate(lines):
        fields = [item.strip() for item in next(csv.reader([line]))]
        if required and set(required).issubset(fields):
            header_index = index
            break
    if header_index is None:
        raise ValueError(f"research CSV missing required columns: {sorted(required)}")

    # Some archives contain a second table with the same daily dates (for
    # example value-weighted followed by equal-weighted industry portfolios).
    # The first header is the requested canonical table; stop at the first
    # non-daily row after its contiguous date block.
    data_lines: list[str] = []
    for line in lines[header_index + 1 :]:
        fields = next(csv.reader([line]))
        first = fields[0].strip() if fields else ""
        if first.isdigit() and len(first) == 8:
            data_lines.append(line)
        elif not first and data_lines:
            break
        elif first and len(fields) >= len(required) + 1:
            raise ValueError(f"research CSV contains malformed daily date {first!r}")
        elif data_lines:
            break
    table = pd.read_csv(io.StringIO("\n".join([lines[header_index], *data_lines])), dtype=str)
    table.columns = [str(column).strip() for column in table.columns]
    first_column = str(table.columns[0])
    missing = set(required) - set(table.columns)
    if missing:
        raise ValueError(f"research CSV missing required columns: {sorted(missing)}")

    dates = table[first_column].astype(str).str.strip()
    daily = table.loc[dates.str.fullmatch(r"\d{8}", na=False), [first_column, *required]].copy()
    if daily.empty:
        raise ValueError("research CSV contains no daily observations")
    daily[first_column] = pd.to_datetime(
        daily[first_column].astype(str).str.strip(), format="%Y%m%d", errors="raise"
    )
    daily = daily.set_index(first_column)
    daily.index.name = "date"
    if daily.index.has_duplicates:
        raise ValueError("research CSV contains duplicate daily dates")
    return daily.sort_index()


def _strict_numeric(
    values: pd.Series,
    *,
    missing_tokens: frozenset[str],
    label: str,
) -> pd.Series:
    tokens = values.astype(str).str.strip()
    candidate = tokens.mask(tokens.isin(missing_tokens))
    try:
        numeric = pd.to_numeric(candidate, errors="raise")
    except (TypeError, ValueError) as exc:
        bad = sorted(set(tokens[~tokens.isin(missing_tokens)]))
        raise ValueError(f"{label} contains invalid numeric value(s): {bad[:3]}") from exc
    finite = numeric.dropna()
    if not np.isfinite(finite.to_numpy(dtype=float)).all():
        raise ValueError(f"{label} contains non-finite values")
    if finite.empty:
        raise ValueError(f"{label} has no usable observations")
    return numeric.astype(float)


def parse_research_archive(raw: bytes, spec: ResearchDatasetSpec) -> pd.DataFrame:
    """Parse one official research ZIP and convert percentage returns to decimals."""
    source_columns = tuple(source for source, _output in spec.columns)
    table = _research_table(_single_csv_member(raw), source_columns)
    output = pd.DataFrame(index=table.index)
    for source, destination in spec.columns:
        values = _strict_numeric(
            table[source],
            missing_tokens=frozenset({"-99.99", "-999", "-999.0"}),
            label=f"research column {source!r}",
        )
        output[destination] = values / 100.0
    return output


def parse_observation_csv(raw: bytes, spec: ObservationDatasetSpec) -> pd.DataFrame:
    """Parse a two-column public observation CSV with explicit unit scaling."""
    table = pd.read_csv(io.BytesIO(raw), dtype=str)
    date_column = "observation_date" if "observation_date" in table.columns else "DATE"
    required = {date_column, spec.value_column}
    missing = required - set(table.columns)
    if missing:
        raise ValueError(f"observation CSV missing required columns: {sorted(missing)}")

    dates = pd.to_datetime(table[date_column], errors="raise")
    values = (
        _strict_numeric(
            table[spec.value_column],
            missing_tokens=frozenset({".", "-99.99", "-999", "-999.0"}),
            label=f"observation column {spec.value_column!r}",
        )
        * spec.scale
    )
    output = pd.DataFrame({spec.output_column: values.to_numpy()}, index=dates)
    output.index.name = "date"
    if output.index.has_duplicates:
        raise ValueError("observation CSV contains duplicate dates")
    return output.sort_index()


def merge_region_factors(five_factor: pd.DataFrame, momentum: pd.DataFrame) -> pd.DataFrame:
    """Inner-join a region's five-factor, momentum, and risk-free histories."""
    required_five = {"MKT_RF", "SMB", "HML", "RMW", "CMA", "RF"}
    if not required_five.issubset(five_factor.columns):
        raise ValueError("five-factor frame is missing required columns")
    if "MOM" not in momentum.columns:
        raise ValueError("momentum frame is missing MOM")
    joined = five_factor[list(required_five)].join(momentum[["MOM"]], how="inner")
    if joined.empty:
        raise ValueError("regional five-factor and momentum histories have no overlapping dates")
    return joined[["MKT_RF", "SMB", "HML", "RMW", "CMA", "MOM", "RF"]].sort_index()


def _default_fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "nami-research-data/1"})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return response.read()


def _cache_key(spec: ResearchDatasetSpec | ObservationDatasetSpec) -> str:
    payload = json.dumps(
        {"version": PUBLIC_DATA_CACHE_VERSION, **spec.__dict__},
        sort_keys=True,
        default=list,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_frame(dataset: PublicDataset) -> pd.DataFrame:
    frame = dataset.frame.copy()
    frame[_SOURCE_DATASET_COLUMN] = dataset.source.dataset_id
    frame[_SOURCE_URL_COLUMN] = dataset.source.url
    frame[_SOURCE_SHA_COLUMN] = dataset.source.sha256
    frame[_SOURCE_RETRIEVED_COLUMN] = dataset.source.retrieved_at.isoformat()
    return frame


def _dataset_from_cache(frame: pd.DataFrame, spec_id: str, url: str) -> PublicDataset:
    if not set(_SOURCE_COLUMNS).issubset(frame.columns) or frame.empty:
        raise ValueError("cached public dataset is missing provenance metadata")
    metadata = frame.loc[frame.index[0], list(_SOURCE_COLUMNS)]
    if metadata[_SOURCE_DATASET_COLUMN] != spec_id or metadata[_SOURCE_URL_COLUMN] != url:
        raise ValueError("cached public dataset provenance does not match its specification")
    if any(frame[column].nunique(dropna=False) != 1 for column in _SOURCE_COLUMNS):
        raise ValueError("cached public dataset has inconsistent provenance metadata")
    sha256 = str(metadata[_SOURCE_SHA_COLUMN])
    if re.fullmatch(r"[0-9a-f]{64}", sha256) is None:
        raise ValueError("cached public dataset has invalid SHA-256 provenance")
    try:
        retrieved_at = datetime.fromisoformat(str(metadata[_SOURCE_RETRIEVED_COLUMN]))
    except ValueError as exc:
        raise ValueError("cached public dataset has invalid retrieval timestamp") from exc
    if retrieved_at.tzinfo is None:
        raise ValueError("cached public dataset retrieval timestamp must be timezone-aware")
    retrieved_at = retrieved_at.astimezone(UTC)

    data = frame.drop(columns=list(_SOURCE_COLUMNS))
    if not isinstance(data.index, pd.DatetimeIndex):
        raise ValueError("cached public dataset index must be datetime")
    if data.index.has_duplicates or not data.index.is_monotonic_increasing:
        raise ValueError("cached public dataset index must be unique and sorted")
    if data.columns.has_duplicates or data.empty:
        raise ValueError("cached public dataset data columns are malformed")
    for column in data.columns:
        try:
            numeric = pd.to_numeric(data[column], errors="raise")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"cached public dataset column {column!r} is not numeric") from exc
        finite = numeric.dropna().to_numpy(dtype=float)
        if len(finite) == 0 or not np.isfinite(finite).all():
            raise ValueError(f"cached public dataset column {column!r} is unusable")

    source = SourceVersion(spec_id, url, sha256, retrieved_at)
    return PublicDataset(data, source)


def _slice_end(dataset: PublicDataset, end: object | None) -> PublicDataset:
    if end is None:
        return dataset
    cutoff = pd.Timestamp(end).tz_localize(None)
    return PublicDataset(dataset.frame.loc[dataset.frame.index <= cutoff].copy(), dataset.source)


class PublicDataClient:
    """Fetch and 30-day-cache validated public datasets with exact provenance."""

    def __init__(
        self,
        *,
        fetch_bytes: Callable[[str], bytes] = _default_fetch,
        cache: FrameCacheProtocol | None | str = "default",
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._fetch_bytes = fetch_bytes
        self._clock = clock
        if cache == "default":
            resolved: FrameCacheProtocol | None = None
            with contextlib.suppress(Exception):
                resolved = get_public_data_cache()
            self._cache = resolved
        else:
            self._cache = cache

    def research(self, spec: ResearchDatasetSpec, *, end: object | None = None) -> PublicDataset:
        return _slice_end(self._load(spec, parse_research_archive), end)

    def observation(
        self, spec: ObservationDatasetSpec, *, end: object | None = None
    ) -> PublicDataset:
        return _slice_end(self._load(spec, parse_observation_csv), end)

    def _load(
        self,
        spec: ResearchDatasetSpec | ObservationDatasetSpec,
        parser: Callable[[bytes, object], pd.DataFrame],
    ) -> PublicDataset:
        key = _cache_key(spec)
        if self._cache is not None:
            cached: pd.DataFrame | None = None
            with contextlib.suppress(Exception):
                cached = self._cache.get(key, ttl_hours=PUBLIC_DATA_CACHE_TTL_HOURS)
            if cached is not None:
                with contextlib.suppress(ValueError):
                    return _dataset_from_cache(cached, spec.dataset_id, spec.url)

        raw = self._fetch_bytes(spec.url)
        frame = parser(raw, spec)
        retrieved_at = self._clock()
        if retrieved_at.tzinfo is None:
            raise ValueError("public-data clock must return a timezone-aware datetime")
        dataset = PublicDataset(
            frame=frame,
            source=SourceVersion(
                spec.dataset_id,
                spec.url,
                source_sha256(raw),
                retrieved_at.astimezone(UTC),
            ),
        )
        if self._cache is not None:
            with contextlib.suppress(Exception):
                self._cache.put(key, _cache_frame(dataset))
        return dataset


def load_quant_public_inputs(
    *,
    client: PublicDataClient | None = None,
    end: object | None = None,
) -> QuantPublicInputs:
    """Load every Quant V2 public dataset concurrently and retain exact provenance."""
    resolved = client or PublicDataClient()

    def load_region(
        region: str,
        specs: tuple[ResearchDatasetSpec, ResearchDatasetSpec],
    ) -> tuple[str, pd.DataFrame, tuple[SourceVersion, SourceVersion]]:
        five = resolved.research(specs[0], end=end)
        momentum = resolved.research(specs[1], end=end)
        return (
            region,
            merge_region_factors(five.frame, momentum.frame),
            (five.source, momentum.source),
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        region_futures = [
            pool.submit(load_region, region, specs)
            for region, specs in REGION_RESEARCH_SPECS.items()
        ]
        industry_future = pool.submit(resolved.research, US_INDUSTRY_SPEC, end=end)
        observation_futures = {
            name: pool.submit(resolved.observation, spec, end=end)
            for name, spec in OBSERVATION_SPECS.items()
        }

        regional_factors: dict[str, pd.DataFrame] = {}
        sources: dict[str, SourceVersion] = {}
        for future in region_futures:
            region, frame, region_sources = future.result()
            regional_factors[region] = frame
            sources.update({source.dataset_id: source for source in region_sources})
        industry = industry_future.result()
        sources[industry.source.dataset_id] = industry.source
        observations = [future.result() for future in observation_futures.values()]
        for observation in observations:
            sources[observation.source.dataset_id] = observation.source

    state_levels = pd.concat(
        [observation.frame for observation in observations],
        axis=1,
        join="outer",
    ).sort_index()
    return QuantPublicInputs(
        regional_factors=regional_factors,
        us_industries=industry.frame,
        state_levels=state_levels,
        sources=sources,
    )
