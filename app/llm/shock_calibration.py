"""Shock-calibration study (Phase 42, Study 2): are the model's numbers better than history's?

Runs the REAL scenario pipeline in backdated, leave-one-out mode: each eligible
registry event gets an ex-ante prompt (`data/calibration_prompts.yaml`) and an
as-of date on the trading day before it began, so `filter_events_as_of` removes
the event itself (and everything later) from the analogs the model may pick.
Every run's shocks are then scored offline, through the SAME vintage betas, as:

    L0  the production headline (the model's shocks; unnamed factors at 0)
    L1  the model's named factors as anchors, completed by covariance
    L2  the same anchors at the selected analogs' MEDIAN realized magnitudes
    L3  the selected analogs' mean realized vector (pure history, no model numbers)

Gate G4 (pre-registered in docs/methodology.md): the model keeps setting
magnitudes only if L1 beats L2 on MAE. The model knows how these episodes ended,
which favors L0/L1, so "history ≥ model" is the robust direction of the test.

Paid calls are bounded by this module's own budget (the API's daily breaker only
guards the endpoints), and every finished run is appended to a JSONL checkpoint
so an interrupted study resumes instead of paying twice.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from app.config import Config, load_config
from app.data.fx import convert_weekly_returns_to_usd
from app.data.market import compute_weekly_returns, fetch_weekly_prices
from app.data.sample_portfolios import CASH_TICKER, get_portfolio, sample_benchmark
from app.factors import warm_cache
from app.factors.analogs import HistoricalEvent, load_events
from app.factors.completion import complete_shocks, shrunk_covariance
from app.factors.completion_study import StudyInputs
from app.factors.regression import (
    estimate_betas_for_portfolio,
    fetch_factor_returns_with_history,
)
from app.llm.gemini_client import GeminiClient, usage_tokens
from app.llm.prompts import PROMPT_VERSION
from app.llm.scenario import run_scenario
from app.observability.metering import cost_usd
from app.utils.calendar import resolve_effective_market_date

logger = logging.getLogger(__name__)

PROMPTS_PATH = Path(__file__).resolve().parents[2] / "data" / "calibration_prompts.yaml"
DEFAULT_PORTFOLIOS: tuple[str, ...] = (
    "msci_world",
    "us_tech_growth",
    "defensive_mix",
    "japan_equity",
)
PRIMARY_BOOK = "msci_world"
PRIMARY_SAMPLES = 3
DEFAULT_BUDGET_USD = 10.0
# Planning estimate per run at the breaker's post-promotion list prices. The real
# spend is tallied from billed tokens; this only sizes dry runs and scheduling.
EST_COST_PER_RUN_USD = 0.12
VARIANTS: tuple[str, ...] = ("L0_headline", "L0", "L1", "L2", "L3", "full_replay")
VARIANT_LABELS: dict[str, str] = {
    "L0_headline": "production headline as returned (incl. single-name shocks)",
    "L0": "model shocks, unnamed factors at 0 (factor-only, scoring betas)",
    "L1": "model's named factors as anchors, completed by covariance",
    "L2": "same anchors at analog-median magnitudes, completed",
    "L3": "mean realized vector of the selected analogs",
    "full_replay": "the event's own realized factor vector (engine upper bound)",
}
REGION_BY_BOOK = {
    "msci_world": "generic",
    "us_tech_growth": "north_america",
    "defensive_mix": "north_america",
    "japan_equity": "japan",
}


class CalibrationBudgetExceeded(Exception):
    """The study's own spending cap was reached; no further paid calls are made.

    Deliberately NOT a RuntimeError: the pipeline maps RuntimeErrors to retryable
    outcomes, and a budget stop must propagate straight out of the run.
    """


@dataclass(frozen=True)
class CalibrationCase:
    event_id: str
    as_of: date
    prompt: str


def as_of_for(event: HistoricalEvent) -> date:
    """The last NYSE trading day strictly before the event starts."""
    return resolve_effective_market_date(event.start_date - timedelta(days=1))


def load_cases(
    path: Path = PROMPTS_PATH, events: Mapping[str, HistoricalEvent] | None = None
) -> list[CalibrationCase]:
    """Cases in registry order; unknown ids or a non-pre-event as-of raise."""
    events = events if events is not None else load_events()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    unknown = sorted(set(raw) - set(events))
    if unknown:
        raise ValueError(f"Calibration prompts reference unknown events: {unknown}")
    cases: list[CalibrationCase] = []
    for event_id, event in sorted(events.items(), key=lambda kv: kv[1].start_date):
        if event_id not in raw:
            continue
        prompt = str(raw[event_id]).strip()
        if not prompt:
            raise ValueError(f"Empty calibration prompt for {event_id}")
        as_of = as_of_for(event)
        if not as_of < event.start_date:
            raise ValueError(f"as-of {as_of} is not before {event_id} starts")
        cases.append(CalibrationCase(event_id=event_id, as_of=as_of, prompt=prompt))
    return cases


def plan_runs(
    cases: Sequence[CalibrationCase],
    portfolio_keys: Sequence[str] = DEFAULT_PORTFOLIOS,
    *,
    primary_book: str = PRIMARY_BOOK,
    primary_samples: int = PRIMARY_SAMPLES,
) -> list[tuple[str, str, int]]:
    """`(event_id, portfolio_key, sample)` for every planned paid run."""
    return [
        (case.event_id, key, sample)
        for case in cases
        for key in portfolio_keys
        for sample in range(primary_samples if key == primary_book else 1)
    ]


def prewarm_market(
    cases: Sequence[CalibrationCase],
    portfolio_keys: Sequence[str],
    *,
    config: Config | None = None,
) -> list[str]:
    """Make every market fetch the backdated runs will make, before any paid call.

    The pipeline overlaps its price fetches with the model chain, so a provider
    failure only surfaces AFTER the model calls were paid for. Running the same
    fetches first (same tickers, lookback, and `end = as_of + 1 day`) fills the
    shared market cache for complete batches and the process-wide event matrix, and
    returns a description of every fetch that failed; callers refuse to spend while
    the list is non-empty.
    """
    config = config or load_config()
    failures: list[str] = []
    try:
        warm_cache.get_event_returns_matrix()
    except RuntimeError as exc:
        failures.append(f"event matrix: {exc}")
    if warm_cache.get_cached_event_returns_matrix() is None:
        failures.append("event matrix: provider gaps kept it out of the cache; retry later")
    for case in cases:
        end = case.as_of + timedelta(days=1)
        try:
            fetch_factor_returns_with_history(lookback_weeks=config.beta_lookback_weeks, end=end)
        except RuntimeError as exc:
            failures.append(f"{case.event_id} factors: {exc}")
        for key in portfolio_keys:
            portfolio = get_portfolio(key)
            tickers = [t for t in portfolio.tickers if t != CASH_TICKER]
            benchmark = portfolio.benchmark or sample_benchmark(key)
            try:
                prices = fetch_weekly_prices(
                    tickers, lookback_weeks=config.beta_lookback_weeks, end=end
                )
                missing = sorted(set(tickers) - {str(c) for c in prices.columns})
                if missing:
                    failures.append(f"{case.event_id}/{key}: no prices for {missing}")
                convert_weekly_returns_to_usd(compute_weekly_returns(prices), end=end)
                if benchmark:
                    bench = fetch_weekly_prices(
                        [benchmark], lookback_weeks=config.beta_lookback_weeks, end=end
                    )
                    if benchmark not in bench.columns:
                        failures.append(f"{case.event_id}/{key}: no benchmark {benchmark}")
            except RuntimeError as exc:
                failures.append(f"{case.event_id}/{key}: {exc}")
    return failures


@dataclass(frozen=True)
class RunRecord:
    event_id: str
    portfolio_key: str
    sample: int
    as_of: str
    model_id: str
    prompt_version: str
    factor_shocks: dict[str, float]
    periphery_shocks: dict[str, float]
    selected_event_ids: list[str]
    analog_event_returns: dict[str, dict[str, float | None]]
    headline_pnl: float | None
    cost_usd: float
    error: str | None
    generated_at: str


class _DiscardCache:
    """A scenario cache that never returns or keeps anything (no shared-cache I/O)."""

    def get_json(self, key: str, ttl_hours: int = 24 * 7) -> dict[str, Any] | None:
        return None

    def put_json(self, key: str, data: dict[str, Any]) -> None:
        return None


class TallyingGeminiClient(GeminiClient):
    """GeminiClient that books billed tokens against the study's own cap.

    Each worker thread runs one scenario at a time, so a thread-local tally gives
    the per-run cost while a shared, locked total enforces the cap.
    """

    def __init__(self, config: Config, *, budget_usd: float) -> None:
        super().__init__(config)
        self._config = config
        self._budget = budget_usd
        self._lock = threading.Lock()
        self._local = threading.local()
        self.spent_usd = 0.0

    def begin_run(self) -> None:
        self._local.cost = 0.0

    def run_cost(self) -> float:
        return float(getattr(self._local, "cost", 0.0))

    def _generate_content(self, *, contents: object, config: object) -> object:
        with self._lock:
            if self.spent_usd >= self._budget:
                raise CalibrationBudgetExceeded(
                    f"study budget ${self._budget:.2f} reached (spent ${self.spent_usd:.2f})"
                )
        response = super()._generate_content(contents=contents, config=config)
        tokens_in, tokens_out, _thinking = usage_tokens(response)
        cost = cost_usd(tokens_in, tokens_out, self._config)
        with self._lock:
            self.spent_usd += cost
        self._local.cost = self.run_cost() + cost
        return response


def read_checkpoint(path: Path) -> list[RunRecord]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(RunRecord(**json.loads(line)))
    return records


def _record_from_result(
    case: CalibrationCase,
    portfolio_key: str,
    sample: int,
    result: Any,
    *,
    cost: float,
    model_id: str,
) -> RunRecord:
    analog_returns = {
        row.event_id: dict(row.factor_returns) for row in (result.analog_event_returns or [])
    }
    return RunRecord(
        event_id=case.event_id,
        portfolio_key=portfolio_key,
        sample=sample,
        as_of=case.as_of.isoformat(),
        model_id=model_id,
        prompt_version=PROMPT_VERSION,
        factor_shocks={s.factor: float(s.shock) for s in result.factor_shocks},
        periphery_shocks={s.ticker: float(s.shock) for s in result.periphery_shocks},
        selected_event_ids=list(result.selected_event_ids),
        analog_event_returns=analog_returns,
        headline_pnl=float(result.portfolio_pnl.total_pnl),
        cost_usd=cost,
        error=None,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )


def execute_runs(
    cases: Sequence[CalibrationCase],
    planned: Sequence[tuple[str, str, int]],
    *,
    checkpoint: Path,
    budget_usd: float = DEFAULT_BUDGET_USD,
    max_runs: int | None = None,
    jobs: int = 3,
    config: Config | None = None,
    gemini: TallyingGeminiClient | None = None,
    run_fn: Callable[..., Any] = run_scenario,
) -> list[RunRecord]:
    """Run every planned case not already in the checkpoint, within the budget.

    Finished runs (successful or failed) are appended to `checkpoint` as they land;
    only successful records count as done, so a failed run is retried next time.
    Scheduling stops once the projected spend of the next wave would exceed the cap.
    """
    config = config or load_config()
    gemini = gemini or TallyingGeminiClient(config, budget_usd=budget_usd)
    by_id = {c.event_id: c for c in cases}
    done = {
        (r.event_id, r.portfolio_key, r.sample) for r in read_checkpoint(checkpoint) if not r.error
    }
    pending = [p for p in planned if p not in done]
    if max_runs is not None:
        pending = pending[: max(0, max_runs)]
    write_lock = threading.Lock()
    finished: list[RunRecord] = []

    def run_one(task: tuple[str, str, int]) -> RunRecord:
        event_id, key, sample = task
        case = by_id[event_id]
        gemini.begin_run()
        try:
            result = run_fn(
                case.prompt,
                portfolio_key=key,
                config=config,
                gemini=gemini,
                cache=_DiscardCache(),
                market_date=case.as_of,
                skip_cache=True,
            )
            record = _record_from_result(
                case, key, sample, result, cost=gemini.run_cost(), model_id=config.vertex_model_id
            )
        except CalibrationBudgetExceeded:
            raise
        except Exception as exc:  # recorded and retried on the next invocation
            logger.warning("calibration run %s/%s/%d failed: %s", event_id, key, sample, exc)
            record = RunRecord(
                event_id=event_id,
                portfolio_key=key,
                sample=sample,
                as_of=case.as_of.isoformat(),
                model_id=config.vertex_model_id,
                prompt_version=PROMPT_VERSION,
                factor_shocks={},
                periphery_shocks={},
                selected_event_ids=[],
                analog_event_returns={},
                headline_pnl=None,
                cost_usd=gemini.run_cost(),
                error=f"{type(exc).__name__}: {exc}",
                generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
            )
        with write_lock:
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            with checkpoint.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(asdict(record)) + "\n")
        return record

    wave = max(1, jobs)
    with ThreadPoolExecutor(max_workers=wave) as pool:
        for start in range(0, len(pending), wave):
            batch = pending[start : start + wave]
            if gemini.spent_usd + EST_COST_PER_RUN_USD * len(batch) > budget_usd:
                logger.warning("stopping: next wave would exceed the $%.2f budget", budget_usd)
                break
            try:
                finished.extend(pool.map(run_one, batch))
            except CalibrationBudgetExceeded as exc:
                logger.warning("stopping: %s", exc)
                break
    return finished


# ---------------------------------------------------------------- scoring (pure)


@dataclass(frozen=True)
class PairScore:
    """One (event, book) pair, model-driven variants averaged over its samples."""

    event_id: str
    portfolio_key: str
    n_samples: int
    realized_pnl: float
    modeled: dict[str, float]
    headline_spread: float | None
    shock_count_range: tuple[int, int]
    cosine_to_realized: float | None
    severity_ratio: float | None


@dataclass(frozen=True)
class VariantScore:
    variant: str
    n: int
    mae: float | None
    bias: float | None
    sign_hit_rate: float | None
    pearson_r: float | None


@dataclass(frozen=True)
class CalibrationSummary:
    n_runs: int
    n_failed: int
    n_pairs_scored: int
    spent_usd: float
    variants: list[VariantScore]
    g4_passed: bool | None
    g4_detail: str
    spread: dict[str, float | int | None]
    factor_layer: dict[str, float | None]
    paired: list[dict[str, Any]]
    challenger_legacy_half: list[dict[str, Any]]
    model_ids: list[str]
    prompt_versions: list[str]
    generated_at: str


def _vector(values: Mapping[str, float | None], names: Sequence[str]) -> np.ndarray:
    return np.array(
        [
            (
                float(values[n])
                if n in values and values[n] is not None and pd.notna(values[n])
                else 0.0
            )
            for n in names
        ]
    )


def _analog_frame(record: RunRecord) -> pd.DataFrame:
    return pd.DataFrame.from_dict(record.analog_event_returns, orient="index", dtype=float)


def score_record(
    record: RunRecord,
    *,
    exposure: pd.Series,
    cov: pd.DataFrame,
    realized: Mapping[str, float],
) -> dict[str, float]:
    """Every variant's factor P&L for one run, through one set of vintage exposures."""
    names = [str(c) for c in cov.index]
    e = exposure.reindex(names).fillna(0.0).to_numpy()
    model = {f: v for f, v in record.factor_shocks.items() if f in names}
    out: dict[str, float] = {"L0": float(e @ _vector(model, names))}
    if record.headline_pnl is not None:
        out["L0_headline"] = float(record.headline_pnl)
    out["L1"] = float(e @ complete_shocks(cov, model).shocks.reindex(names).to_numpy())

    analogs = _analog_frame(record)
    medians = {
        f: float(analogs[f].median(skipna=True))
        for f in model
        if f in analogs.columns and analogs[f].notna().any()
    }
    out["L2"] = float(e @ complete_shocks(cov, medians).shocks.reindex(names).to_numpy())
    means = analogs.mean(axis=0, skipna=True).to_dict() if not analogs.empty else {}
    out["L3"] = float(e @ _vector(means, names))
    out["full_replay"] = float(e @ _vector(realized, names))
    return out


def _variant_score(variant: str, pairs: Sequence[PairScore]) -> VariantScore:
    rows = [p for p in pairs if variant in p.modeled]
    if not rows:
        return VariantScore(variant, 0, None, None, None, None)
    modeled = np.array([p.modeled[variant] for p in rows])
    realized = np.array([p.realized_pnl for p in rows])
    errors = modeled - realized
    r = None
    if len(rows) >= 3 and modeled.std() > 0 and realized.std() > 0:
        r = float(np.corrcoef(modeled, realized)[0, 1])
    return VariantScore(
        variant=variant,
        n=len(rows),
        mae=float(np.mean(np.abs(errors))),
        bias=float(np.mean(errors)),
        sign_hit_rate=float(np.mean((modeled >= 0) == (realized >= 0))),
        pearson_r=r,
    )


PAIRED_COMPARISONS: tuple[tuple[str, str], ...] = (
    ("L1", "L2"),
    ("L1", "L3"),
    ("L0_headline", "L1"),
    ("L0_headline", "L3"),
)
BOOTSTRAP_DRAWS = 20_000


def paired_comparison(
    pairs: Sequence[PairScore], a: str, b: str, *, seed: int = 0
) -> dict[str, Any] | None:
    """Mean of |err_a| − |err_b| over pairs with both, with a 95% bootstrap CI.

    Negative means `a` is closer to realized. Resampling whole pairs keeps the
    comparison paired, so a common hard target does not masquerade as a difference.
    """
    rows = [p for p in pairs if a in p.modeled and b in p.modeled]
    if len(rows) < 3:
        return None
    diff = np.array(
        [abs(p.modeled[a] - p.realized_pnl) - abs(p.modeled[b] - p.realized_pnl) for p in rows]
    )
    rng = np.random.default_rng(seed)
    draws = rng.choice(diff, size=(BOOTSTRAP_DRAWS, len(diff)), replace=True).mean(axis=1)
    low, high = np.percentile(draws, [2.5, 97.5])
    return {
        "a": a,
        "b": b,
        "n": len(rows),
        "mean_abs_error_diff": float(diff.mean()),
        "ci95_low": float(low),
        "ci95_high": float(high),
        "share_a_closer": float(np.mean(diff < 0.0)),
    }


def _nearest_horizon(window_days: int) -> int:
    trading_days = window_days * 5.0 / 7.0
    return min((5, 21, 63), key=lambda h: abs(h - trading_days))


def score_runs(
    records: Sequence[RunRecord], inputs: StudyInputs, *, config: Config | None = None
) -> tuple[list[PairScore], CalibrationSummary]:
    """Score successful runs against realized outcomes (pure; no network)."""
    config = config or load_config()
    events = {e.event_id: e for e in inputs.events}
    books = {(b.event_id, b.portfolio_key): b for b in inputs.books}
    ok = [r for r in records if r.error is None and r.headline_pnl is not None]

    covs: dict[str, pd.DataFrame] = {}
    exposures: dict[tuple[str, str], pd.Series] = {}
    grouped: dict[tuple[str, str], list[RunRecord]] = {}
    for record in ok:
        grouped.setdefault((record.event_id, record.portfolio_key), []).append(record)

    pairs: list[PairScore] = []
    for (event_id, key), runs in sorted(grouped.items()):
        ev = events.get(event_id)
        book = books.get((event_id, key))
        if ev is None or book is None or book.ticker_returns is None or book.realized_pnl is None:
            continue
        if event_id not in covs:
            covs[event_id], _ = shrunk_covariance(ev.factor_returns)
        cov = covs[event_id]
        if (event_id, key) not in exposures:
            try:
                betas, _ = estimate_betas_for_portfolio(
                    get_portfolio(key),
                    lookback_weeks=config.beta_lookback_weeks,
                    alpha=config.ridge_alpha,
                    factor_returns=ev.factor_returns,
                    ticker_returns=book.ticker_returns,
                )
            except RuntimeError as exc:
                logger.warning("cannot score %s/%s: %s", event_id, key, exc)
                continue
            weights = pd.Series(get_portfolio(key).holdings).reindex(betas.index).fillna(0.0)
            exposures[(event_id, key)] = betas.T @ weights
        scored = [
            score_record(r, exposure=exposures[(event_id, key)], cov=cov, realized=ev.realized)
            for r in runs
        ]
        modeled = {
            v: float(np.mean([s[v] for s in scored if v in s]))
            for v in VARIANTS
            if any(v in s for s in scored)
        }
        headlines = [s["L0_headline"] for s in scored if "L0_headline" in s]
        names = [str(c) for c in cov.index]
        actual = _vector(ev.realized, names)
        cosines, severities = [], []
        for r in runs:
            shock = _vector(r.factor_shocks, names)
            if np.linalg.norm(shock) > 0 and np.linalg.norm(actual) > 0:
                cosines.append(
                    float(shock @ actual / (np.linalg.norm(shock) * np.linalg.norm(actual)))
                )
                severities.append(float(shock @ actual / (actual @ actual)))
        counts = [len(r.factor_shocks) for r in runs]
        pairs.append(
            PairScore(
                event_id=event_id,
                portfolio_key=key,
                n_samples=len(runs),
                realized_pnl=float(book.realized_pnl),
                modeled=modeled,
                headline_spread=(float(np.std(headlines, ddof=1)) if len(headlines) > 1 else None),
                shock_count_range=(min(counts), max(counts)),
                cosine_to_realized=float(np.mean(cosines)) if cosines else None,
                severity_ratio=float(np.median(severities)) if severities else None,
            )
        )

    variants = [_variant_score(v, pairs) for v in VARIANTS]
    by_key = {v.variant: v for v in variants}
    l1, l2 = by_key["L1"].mae, by_key["L2"].mae
    if l1 is None or l2 is None:
        g4_passed, g4_detail = None, "insufficient scored pairs"
    else:
        g4_passed = l1 < l2
        g4_detail = (
            f"L1 (model magnitudes, completed) MAE {l1:.2%} vs L2 (analog-median magnitudes, "
            f"completed) MAE {l2:.2%} over {by_key['L1'].n} pairs"
        )

    multi = [p for p in pairs if p.n_samples > 1]
    spreads = [p.headline_spread for p in multi if p.headline_spread is not None]
    spread = {
        "pairs_with_repeats": len(multi),
        "median_headline_sd": float(np.median(spreads)) if spreads else None,
        "max_headline_sd": float(max(spreads)) if spreads else None,
        "max_shock_count_range": (
            max(p.shock_count_range[1] - p.shock_count_range[0] for p in multi) if multi else None
        ),
    }
    cos = [p.cosine_to_realized for p in pairs if p.cosine_to_realized is not None]
    sev = [p.severity_ratio for p in pairs if p.severity_ratio is not None]
    factor_layer = {
        "median_cosine_to_realized": float(np.median(cos)) if cos else None,
        "median_severity_ratio": float(np.median(sev)) if sev else None,
    }
    paired = [c for c in (paired_comparison(pairs, a, b) for a, b in PAIRED_COMPARISONS) if c]
    legacy_half = []
    for p in pairs:
        ev = events[p.event_id]
        legacy_half.append(
            {
                "case_id": f"{p.event_id}:{p.portfolio_key}",
                "region": REGION_BY_BOOK.get(p.portfolio_key, "generic"),
                "horizon": _nearest_horizon((ev.end_date - ev.start_date).days),
                "legacy_pnl": p.modeled.get("L0_headline"),
                "realized_pnl": p.realized_pnl,
            }
        )
    summary = CalibrationSummary(
        n_runs=len(records),
        n_failed=len([r for r in records if r.error is not None]),
        n_pairs_scored=len(pairs),
        spent_usd=float(sum(r.cost_usd for r in records)),
        variants=variants,
        g4_passed=g4_passed,
        g4_detail=g4_detail,
        spread=spread,
        factor_layer=factor_layer,
        paired=paired,
        challenger_legacy_half=legacy_half,
        model_ids=sorted({r.model_id for r in records}),
        prompt_versions=sorted({r.prompt_version for r in records}),
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    return pairs, summary


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:+.2f}%"


def _abs(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.2f}%"


def render_markdown(pairs: Sequence[PairScore], summary: CalibrationSummary) -> str:
    """The human-readable study artifact (fully regenerated, never hand-edited)."""
    verdict = "n/a" if summary.g4_passed is None else ("PASS" if summary.g4_passed else "FAIL")
    lines = [
        "# Shock calibration — the model's magnitudes versus history",
        "",
        "> Generated by `uv run python scripts/run_shock_calibration.py`. Do not hand-edit.",
        "",
        "## What this measures",
        "",
        "The real pipeline runs in backdated, leave-one-out mode: each event gets an "
        "ex-ante prompt and an as-of date on the trading day before it began, so the "
        "event itself can never be one of the analogs the model selects. Each run's "
        "shocks are scored through the same vintage betas as variants that differ only in "
        "who sets the numbers.",
        "",
        "| variant | meaning |",
        "|---|---|",
        *(f"| {v} | {VARIANT_LABELS[v]} |" for v in VARIANTS),
        "",
        "Honest read: the model knows how every one of these episodes ended (its knowledge "
        "is not vintage-controlled), which favors the model-driven variants. A result "
        "where history matches or beats the model is therefore robust; the reverse is "
        "not. Books are today's frozen weights; the model-driven variants are averaged "
        "over a pair's repeated samples.",
        "",
        "The targets are hard by construction. Several registry windows are anchored "
        "on ex-post peaks and troughs (`covid-crash-2020` runs exactly peak to trough), "
        "and some include the reversal that ended the episode (`us-tariffs-2025` ends "
        "after the tariff pause and rebound). No ex-ante scenario could be expected to "
        "hit those numbers, so the absolute error level overstates what a scenario tool "
        "could achieve. The comparison BETWEEN variants is fair: every variant faces the "
        "same targets through the same betas.",
        "",
        "## Gate G4 (pre-registered)",
        "",
        f"**{verdict}** — {summary.g4_detail}. The model keeps setting magnitudes only "
        "if its completed shocks beat analog-median magnitudes.",
        "",
        "Paired comparisons (mean of |error a| − |error b|; negative means a is closer; "
        "95% bootstrap interval over pairs):",
        "",
        "| a | b | pairs | mean difference | 95% interval | a closer |",
        "|---|---|---:|---:|---|---:|",
        *(
            f"| {c['a']} | {c['b']} | {c['n']} | {_pct(c['mean_abs_error_diff'])} | "
            f"[{_pct(c['ci95_low'])}, {_pct(c['ci95_high'])}] | {_abs(c['share_a_closer'])} |"
            for c in summary.paired
        ),
        "",
        "## Variants",
        "",
        "| variant | pairs | MAE | bias | sign | r |",
        "|---|---:|---:|---:|---:|---:|",
        *(
            f"| {v.variant} | {v.n} | {_abs(v.mae)} | {_pct(v.bias)} | "
            f"{_abs(v.sign_hit_rate)} | {'—' if v.pearson_r is None else f'{v.pearson_r:.3f}'} |"
            for v in summary.variants
        ),
        "",
        "## Run-to-run variation (repeated samples of the same prompt)",
        "",
        f"- pairs with repeats: {summary.spread.get('pairs_with_repeats')}",
        f"- median headline standard deviation: {_abs(summary.spread.get('median_headline_sd'))}",
        f"- largest headline standard deviation: {_abs(summary.spread.get('max_headline_sd'))}",
        "- largest spread in the number of factors shocked: "
        f"{summary.spread.get('max_shock_count_range')}",
        "",
        "## Factor layer",
        "",
        "- median cosine similarity between the model's shock vector (unnamed factors at "
        f"0) and the realized factor vector: {summary.factor_layer.get('median_cosine_to_realized')}",
        "- median severity ratio (projection of the shocks on the realized vector; 1.0 = "
        f"right size, below 1 = too mild): {summary.factor_layer.get('median_severity_ratio')}",
        "",
        "## Per pair",
        "",
        "| event | book | samples | realized | headline | L1 | L2 | L3 | full replay |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
        *(
            f"| {p.event_id} | {p.portfolio_key} | {p.n_samples} | {_pct(p.realized_pnl)} | "
            f"{_pct(p.modeled.get('L0_headline'))} | {_pct(p.modeled.get('L1'))} | "
            f"{_pct(p.modeled.get('L2'))} | {_pct(p.modeled.get('L3'))} | "
            f"{_pct(p.modeled.get('full_replay'))} |"
            for p in pairs
        ),
        "",
        "## Provenance",
        "",
        f"- runs: {summary.n_runs} ({summary.n_failed} failed), spend ${summary.spent_usd:.2f} "
        "at the breaker's list prices",
        f"- model: {', '.join(summary.model_ids) or '—'}; prompt version: "
        f"{', '.join(summary.prompt_versions) or '—'}",
        f"- generated: {summary.generated_at}",
        "",
    ]
    return "\n".join(lines)
