"""Public research-data parsing, provenance, caching, and backdating contracts."""

from __future__ import annotations

import hashlib
import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def _archive(csv_bytes: bytes, *, member: str = "dataset.csv") -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        bundle.writestr(member, csv_bytes)
    return output.getvalue()


class _FrameCache:
    def __init__(self) -> None:
        self.store: dict[str, pd.DataFrame] = {}
        self.get_calls: list[tuple[str, int]] = []
        self.put_calls: list[str] = []

    def get(self, key: str, ttl_hours: int = 24) -> pd.DataFrame | None:
        self.get_calls.append((key, ttl_hours))
        value = self.store.get(key)
        return None if value is None else value.copy()

    def put(self, key: str, frame: pd.DataFrame) -> None:
        self.put_calls.append(key)
        self.store[key] = frame.copy()


class _ParquetFrameCache:
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    def get(self, key: str, ttl_hours: int = 24) -> pd.DataFrame | None:
        del ttl_hours
        raw = self.store.get(key)
        return None if raw is None else pd.read_parquet(io.BytesIO(raw))

    def put(self, key: str, frame: pd.DataFrame) -> None:
        output = io.BytesIO()
        frame.to_parquet(output, index=True)
        self.store[key] = output.getvalue()


class _BrokenCache:
    def get(self, key: str, ttl_hours: int = 24) -> pd.DataFrame | None:
        del key, ttl_hours
        raise RuntimeError("cache read unavailable")

    def put(self, key: str, frame: pd.DataFrame) -> None:
        del key, frame
        raise RuntimeError("cache write unavailable")


def _five_factor_spec():
    from app.data.quant_sources import ResearchDatasetSpec

    return ResearchDatasetSpec(
        dataset_id="north_america_five_daily",
        url="https://example.test/north-america.zip",
        columns=(
            ("Mkt-RF", "MKT_RF"),
            ("SMB", "SMB"),
            ("HML", "HML"),
            ("RMW", "RMW"),
            ("CMA", "CMA"),
            ("RF", "RF"),
        ),
    )


def test_research_archive_converts_percentages_and_missing_sentinels() -> None:
    from app.data.quant_sources import parse_research_archive

    raw_csv = (FIXTURES / "research_factors_daily.csv").read_bytes()
    result = parse_research_archive(_archive(raw_csv), _five_factor_spec())

    assert list(result.columns) == ["MKT_RF", "SMB", "HML", "RMW", "CMA", "RF"]
    assert result.index.equals(pd.DatetimeIndex(["2024-01-02", "2024-01-03"], name="date"))
    assert result.loc["2024-01-02", "MKT_RF"] == pytest.approx(0.01)
    assert result.loc["2024-01-02", "RF"] == pytest.approx(0.0005)
    assert pd.isna(result.loc["2024-01-02", "CMA"])
    assert pd.isna(result.loc["2024-01-03", "HML"])


def test_research_archive_rejects_structural_drift() -> None:
    from app.data.quant_sources import parse_research_archive

    bad_csv = b",Mkt-RF,SMB\n20240102,1.0,2.0\n"
    with pytest.raises(ValueError, match="missing required columns"):
        parse_research_archive(_archive(bad_csv), _five_factor_spec())

    multiple = io.BytesIO()
    with zipfile.ZipFile(multiple, "w") as bundle:
        bundle.writestr("one.csv", bad_csv)
        bundle.writestr("two.csv", bad_csv)
    with pytest.raises(ValueError, match="exactly one CSV"):
        parse_research_archive(multiple.getvalue(), _five_factor_spec())


def test_research_archive_uses_first_contiguous_daily_table() -> None:
    from app.data.quant_sources import ResearchDatasetSpec, parse_research_archive

    spec = ResearchDatasetSpec(
        dataset_id="industry_daily",
        url="https://example.test/industry.zip",
        columns=(("BusEq", "BusEq"),),
    )
    raw_csv = b"\n".join(
        (
            b"Average Value Weighted Returns -- Daily",
            b",BusEq",
            b"20240102    ,1.00",
            b"",
            b"Average Equal Weighted Returns -- Daily",
            b",BusEq",
            b"20240102    ,9.00",
        )
    )

    result = parse_research_archive(_archive(raw_csv), spec)

    assert result.index.is_unique
    assert result.loc["2024-01-02", "BusEq"] == pytest.approx(0.01)


@pytest.mark.parametrize(
    "bad_value",
    ["not-a-number", "inf", "-inf"],
)
def test_research_archive_rejects_unknown_or_non_finite_values(bad_value: str) -> None:
    from app.data.quant_sources import parse_research_archive

    raw_csv = b",Mkt-RF,SMB,HML,RMW,CMA,RF\n" + f"20240102,{bad_value},0,0,0,0,0\n".encode()
    with pytest.raises(ValueError, match="invalid numeric|non-finite"):
        parse_research_archive(_archive(raw_csv), _five_factor_spec())


def test_research_archive_rejects_malformed_date_inside_selected_table() -> None:
    from app.data.quant_sources import parse_research_archive

    raw_csv = b"""\
,Mkt-RF,SMB,HML,RMW,CMA,RF
20240102,1,0,0,0,0,0
2024010X,2,0,0,0,0,0
"""
    with pytest.raises(ValueError, match="malformed daily date"):
        parse_research_archive(_archive(raw_csv), _five_factor_spec())


def test_official_series_parser_scales_percent_units_and_maps_missing() -> None:
    from app.data.quant_sources import ObservationDatasetSpec, parse_observation_csv

    spec = ObservationDatasetSpec(
        dataset_id="ten_year_yield",
        url="https://example.test/series.csv",
        value_column="DGS10",
        output_column="US_10Y_YIELD",
        scale=0.01,
    )
    result = parse_observation_csv((FIXTURES / "official_series.csv").read_bytes(), spec)

    assert result.loc["2024-01-02", "US_10Y_YIELD"] == pytest.approx(0.0425)
    assert pd.isna(result.loc["2024-01-03", "US_10Y_YIELD"])
    assert pd.isna(result.loc["2024-01-04", "US_10Y_YIELD"])


@pytest.mark.parametrize("bad_value", ["oops", "inf", "-inf"])
def test_official_series_parser_rejects_unknown_or_non_finite_values(
    bad_value: str,
) -> None:
    from app.data.quant_sources import ObservationDatasetSpec, parse_observation_csv

    spec = ObservationDatasetSpec(
        dataset_id="ten_year_yield",
        url="https://example.test/series.csv",
        value_column="DGS10",
        output_column="US_10Y_YIELD",
    )
    raw = f"observation_date,DGS10\n2024-01-02,{bad_value}\n".encode()
    with pytest.raises(ValueError, match="invalid numeric|non-finite"):
        parse_observation_csv(raw, spec)


def test_public_parsers_reject_malformed_dates() -> None:
    from app.data.quant_sources import (
        ObservationDatasetSpec,
        parse_observation_csv,
        parse_research_archive,
    )

    malformed_research = b",Mkt-RF,SMB,HML,RMW,CMA,RF\n20240230,1,2,3,4,5,6\n"
    with pytest.raises(ValueError):
        parse_research_archive(_archive(malformed_research), _five_factor_spec())

    observation_spec = ObservationDatasetSpec(
        dataset_id="ten_year_yield",
        url="https://example.test/series.csv",
        value_column="DGS10",
        output_column="US_10Y_YIELD",
        scale=0.01,
    )
    with pytest.raises(ValueError):
        parse_observation_csv(b"observation_date,DGS10\nnot-a-date,4.25\n", observation_spec)


def test_source_version_hashes_exact_downloaded_bytes() -> None:
    from app.data.quant_sources import source_sha256

    first = b"date,value\n2024-01-02,1\n"
    second = first + b"\n"
    assert source_sha256(first) == hashlib.sha256(first).hexdigest()
    assert source_sha256(first) != source_sha256(second)


def test_quant_public_bundle_merges_all_regions_states_and_provenance() -> None:
    from app.data.quant_sources import (
        OBSERVATION_SPECS,
        REGION_RESEARCH_SPECS,
        US_INDUSTRY_SPEC,
        PublicDataset,
        SourceVersion,
        load_quant_public_inputs,
    )

    index = pd.date_range("2024-01-02", periods=3, freq="B")
    retrieved = datetime(2024, 2, 1, tzinfo=UTC)

    class _Client:
        def research(self, spec, *, end=None):
            assert end == index[-1]
            frame = pd.DataFrame(
                {destination: [0.001, 0.002, 0.003] for _source, destination in spec.columns},
                index=index,
            )
            return PublicDataset(
                frame,
                SourceVersion(spec.dataset_id, spec.url, "a" * 64, retrieved),
            )

        def observation(self, spec, *, end=None):
            assert end == index[-1]
            return PublicDataset(
                pd.DataFrame({spec.output_column: [1.0, 2.0, 3.0]}, index=index),
                SourceVersion(spec.dataset_id, spec.url, "b" * 64, retrieved),
            )

    bundle = load_quant_public_inputs(client=_Client(), end=index[-1])

    assert set(bundle.regional_factors) == set(REGION_RESEARCH_SPECS)
    assert all("MOM" in frame and "RF" in frame for frame in bundle.regional_factors.values())
    assert list(bundle.us_industries.columns) == [
        output for _source, output in US_INDUSTRY_SPEC.columns
    ]
    assert set(bundle.state_levels.columns) == {
        spec.output_column for spec in OBSERVATION_SPECS.values()
    }
    assert len(bundle.sources) == 2 * len(REGION_RESEARCH_SPECS) + len(OBSERVATION_SPECS) + 1


def test_client_reuses_30_day_parquet_cache_with_source_metadata() -> None:
    from app.data.quant_sources import PUBLIC_DATA_CACHE_TTL_HOURS, PublicDataClient

    raw = _archive((FIXTURES / "research_factors_daily.csv").read_bytes())
    fetch_calls: list[str] = []

    def fetch(url: str) -> bytes:
        fetch_calls.append(url)
        return raw

    cache = _FrameCache()
    retrieved_at = datetime(2024, 2, 1, 12, tzinfo=UTC)
    client = PublicDataClient(fetch_bytes=fetch, cache=cache, clock=lambda: retrieved_at)
    first = client.research(_five_factor_spec())
    second = PublicDataClient(
        fetch_bytes=lambda _url: (_ for _ in ()).throw(AssertionError("unexpected fetch")),
        cache=cache,
    ).research(_five_factor_spec())

    assert fetch_calls == [_five_factor_spec().url]
    assert cache.get_calls[-1][1] == PUBLIC_DATA_CACHE_TTL_HOURS == 24 * 30
    assert len(cache.put_calls) == 1
    assert second.source == first.source
    pd.testing.assert_frame_equal(second.frame, first.frame)
    assert first.source.sha256 == hashlib.sha256(raw).hexdigest()
    assert first.source.retrieved_at == retrieved_at
    assert first.source.retrieved_at.tzinfo is UTC


def test_source_metadata_survives_a_real_parquet_round_trip() -> None:
    from app.data.quant_sources import PublicDataClient

    raw = _archive((FIXTURES / "research_factors_daily.csv").read_bytes())
    cache = _ParquetFrameCache()
    first = PublicDataClient(fetch_bytes=lambda _url: raw, cache=cache).research(
        _five_factor_spec()
    )
    second = PublicDataClient(
        fetch_bytes=lambda _url: (_ for _ in ()).throw(AssertionError("unexpected fetch")),
        cache=cache,
    ).research(_five_factor_spec())

    assert second.source == first.source
    pd.testing.assert_frame_equal(second.frame, first.frame, check_index_type=False)


def test_malformed_cached_provenance_is_refetched_and_replaced() -> None:
    from app.data.quant_sources import PublicDataClient

    raw = _archive((FIXTURES / "research_factors_daily.csv").read_bytes())
    cache = _FrameCache()
    PublicDataClient(fetch_bytes=lambda _url: raw, cache=cache).research(_five_factor_spec())
    cached = next(iter(cache.store.values()))
    cached["__nami_source_sha256"] = "not-a-sha"
    fetches: list[str] = []

    result = PublicDataClient(
        fetch_bytes=lambda url: fetches.append(url) or raw,
        cache=cache,
    ).research(_five_factor_spec())

    assert fetches == [_five_factor_spec().url]
    assert result.source.sha256 == hashlib.sha256(raw).hexdigest()
    assert cache.put_calls == [next(iter(cache.store)), next(iter(cache.store))]


def test_cache_transport_failures_do_not_hide_valid_network_data() -> None:
    from app.data.quant_sources import PublicDataClient

    raw = _archive((FIXTURES / "research_factors_daily.csv").read_bytes())
    result = PublicDataClient(fetch_bytes=lambda _url: raw, cache=_BrokenCache()).research(
        _five_factor_spec()
    )

    assert not result.frame.empty


def test_cache_entry_without_valid_provenance_is_rejected_and_refetched() -> None:
    from app.data.quant_sources import PublicDataClient

    raw = _archive((FIXTURES / "research_factors_daily.csv").read_bytes())
    cache = _FrameCache()
    first = PublicDataClient(fetch_bytes=lambda _url: raw, cache=cache).research(
        _five_factor_spec()
    )
    key = next(iter(cache.store))
    cache.store[key] = first.frame.copy()
    refetch_calls: list[str] = []

    def refetch(url: str) -> bytes:
        refetch_calls.append(url)
        return raw

    recovered = PublicDataClient(fetch_bytes=refetch, cache=cache).research(_five_factor_spec())

    assert refetch_calls == [_five_factor_spec().url]
    assert recovered.source.dataset_id == _five_factor_spec().dataset_id
    assert recovered.source.sha256 == hashlib.sha256(raw).hexdigest()


def test_default_client_resolves_the_production_cache_lazily(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.data.quant_sources as quant_sources

    raw = _archive((FIXTURES / "research_factors_daily.csv").read_bytes())
    cache = _FrameCache()
    factory_calls = 0

    def cache_factory() -> _FrameCache:
        nonlocal factory_calls
        factory_calls += 1
        return cache

    monkeypatch.setattr(quant_sources, "get_public_data_cache", cache_factory)
    client = quant_sources.PublicDataClient(fetch_bytes=lambda _url: raw)

    assert factory_calls == 1
    client.research(_five_factor_spec())
    assert len(cache.put_calls) == 1


def test_backdated_read_never_exposes_later_rows_from_a_warm_cache() -> None:
    from app.data.quant_sources import PublicDataClient

    raw = _archive((FIXTURES / "research_factors_daily.csv").read_bytes())
    cache = _FrameCache()
    live = PublicDataClient(fetch_bytes=lambda _url: raw, cache=cache)
    assert live.research(_five_factor_spec()).frame.index.max() == pd.Timestamp("2024-01-03")

    backdated = PublicDataClient(
        fetch_bytes=lambda _url: (_ for _ in ()).throw(AssertionError("unexpected fetch")),
        cache=cache,
    ).research(_five_factor_spec(), end="2024-01-02")
    assert backdated.frame.index.max() == pd.Timestamp("2024-01-02")


def test_region_bundle_keeps_risk_free_and_merges_momentum() -> None:
    from app.data.quant_sources import merge_region_factors

    index = pd.date_range("2024-01-02", periods=2, freq="B")
    five = pd.DataFrame(
        {
            "MKT_RF": [0.01, -0.01],
            "SMB": [0.0, 0.0],
            "HML": [0.0, 0.0],
            "RMW": [0.0, 0.0],
            "CMA": [0.0, 0.0],
            "RF": [0.0001, 0.0001],
        },
        index=index,
    )
    momentum = pd.DataFrame({"MOM": [0.02, 0.03]}, index=index)
    result = merge_region_factors(five, momentum)
    assert list(result.columns) == ["MKT_RF", "SMB", "HML", "RMW", "CMA", "MOM", "RF"]


def test_region_bundle_rejects_empty_calendar_overlap() -> None:
    from app.data.quant_sources import merge_region_factors

    five = pd.DataFrame(
        {column: [0.0] for column in ["MKT_RF", "SMB", "HML", "RMW", "CMA", "RF"]},
        index=pd.to_datetime(["2024-01-02"]),
    )
    momentum = pd.DataFrame(
        {"MOM": [0.0]},
        index=pd.to_datetime(["2024-02-02"]),
    )

    with pytest.raises(ValueError, match="no overlapping"):
        merge_region_factors(five, momentum)
