from __future__ import annotations

import contextlib
import contextvars
import json
import queue
import threading
from collections.abc import AsyncIterator, Callable, Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import date as date_type
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.api.errors import http_error
from app.api.middleware import request_context_middleware
from app.api.portfolio_validation import validate_holdings, validate_nav, validate_quantities
from app.api.ratelimit import limiter, llm_limit, setup_rate_limiting, unlock_limit
from app.api.samples import SAMPLE_SCENARIOS
from app.api.schemas import (
    AccessResponse,
    AnalogEventResponse,
    AuditEntry,
    BookProfileRequest,
    BookProfileResponse,
    EventsReplayRequest,
    EventsReplayResponse,
    FactorMetadataResponse,
    NarrativeDecompositionRequest,
    Permissions,
    PortfolioSnapshotRecord,
    PortfolioSnapshotRequest,
    PortfolioValidationRequest,
    PortfolioValidationResponse,
    PurgeRequest,
    ReadinessResponse,
    SamplePortfolioResponse,
    SampleScenarioResponse,
    SavedPortfolioRecord,
    SavedScenarioListItem,
    SavedScenarioRecord,
    SavePortfolioRequest,
    SaveScenarioRequest,
    ScenarioAdjustRequest,
    ScenarioReproducibility,
    ScenarioRunRequest,
    ScenarioRunResponse,
    StatusResponse,
    TickerMetadataResponse,
    UnlockRequest,
    UsageSummary,
)
from app.api.security import (
    AccessMode,
    access_mode_for_request,
    can_use_custom_portfolio,
    can_use_free_text_scenario,
    can_use_narrative_decomposition,
    clear_admin_cookie,
    configured_passcode,
    set_admin_cookie,
    verify_passcode,
)
from app.config import load_config
from app.data.cache import CloudStorageCache
from app.data.firestore_store import (
    FirestoreStore,
    SavedScenarioStore,
    utcnow,
)
from app.data.marking import MarkingError
from app.data.sample_portfolios import (
    SAMPLE_PORTFOLIOS,
    Portfolio,
    sample_as_of,
    ticker_metadata,
)
from app.factors import warm_cache
from app.factors.analogs import HistoricalEvent, events_version, load_events
from app.factors.regression import InsufficientHistoryError, regression_spec
from app.factors.universe import factor_metadata, factor_universe_version
from app.llm.narrative_shapley import compute_narrative_shapley
from app.llm.prompts import PROMPT_VERSION
from app.llm.scenario import (
    adjust_scenario_shocks,
    compute_book_profile,
    compute_events_replay,
    compute_scenario_cache_key,
    run_scenario,
)
from app.observability.context import current_ip_hash, current_request_id
from app.observability.logging import configure_logging
from app.observability.metering import (
    BudgetExceededError,
    MeteredGeminiClient,
    RunCapExceededError,
    RunTelemetry,
    enforce_run_cap,
    today_key,
)
from app.utils.calendar import latest_market_date
from app.utils.disclaimers import DISCLAIMER_SHORT

ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST = ROOT / "frontend" / "dist"
METHODOLOGY_PATH = ROOT / "docs" / "methodology.md"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup: configure structured logging, optional Sentry, warm the cache."""
    with contextlib.suppress(Exception):
        config = load_config()
        configure_logging(config.log_level)
        if config.sentry_dsn:
            import sentry_sdk

            sentry_sdk.init(
                dsn=config.sentry_dsn,
                environment=config.environment,
                traces_sample_rate=0.0,
            )
    with contextlib.suppress(Exception):
        warm_cache.warm()
    yield


api = FastAPI(title="nami API", version="0.1.0", lifespan=lifespan)
api.middleware("http")(request_context_middleware)
setup_rate_limiting(api)

# CORS is opt-in: the SPA is served from this same origin, so by default no
# cross-origin access is granted. Set CORS_ALLOW_ORIGINS to enable an external
# client (comma-separated origins).
with contextlib.suppress(Exception):
    _cors_origins = load_config().cors_allow_origins
    if _cors_origins:
        from fastapi.middleware.cors import CORSMiddleware

        api.add_middleware(
            CORSMiddleware,
            allow_origins=list(_cors_origins),
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID", "X-Error-Code"],
        )

# nami engine version used in reproducibility metadata. Bumps with any
# release-significant change to the engine; not in lockstep with PROMPT_VERSION.
# (Display metadata only — the cache-invalidation lever for engine math is the
# `regression_spec` component inside the scenario cache key.)
NAMI_ENGINE_VERSION = "0.2.0"
MIN_SCENARIO_TEXT_CHARS = 10
MAX_SCENARIO_TEXT_CHARS = 2000


_firestore_store: SavedScenarioStore | None = None


def get_firestore_store() -> SavedScenarioStore:
    """Lazy Firestore singleton. Tests override via FastAPI dependency_overrides
    or by monkeypatching `app.api.main._firestore_store`."""
    global _firestore_store
    if _firestore_store is None:
        config = load_config()
        _firestore_store = FirestoreStore(project_id=config.google_cloud_project)
    return _firestore_store


def _metered_gemini() -> tuple[MeteredGeminiClient, RunTelemetry, str]:
    """Build a budget-metered Gemini client for a paid request.

    Enforces the daily run cap (raises `BudgetExceededError` → 429) and returns the
    client + request-scoped telemetry. The client reserves/reconciles the daily
    cost budget on every underlying model call.
    """
    config = load_config()
    store = get_firestore_store()
    day = today_key()
    enforce_run_cap(store, config, day)
    telemetry = RunTelemetry()
    gemini = MeteredGeminiClient(config, store=store, telemetry=telemetry, day=day)
    return gemini, telemetry, day


def _budget_http_error(exc: BudgetExceededError) -> HTTPException:
    """429 whose X-Error-Code distinguishes the run cap from the cost cap."""
    code = "run_cap" if isinstance(exc, RunCapExceededError) else "budget_exhausted"
    return http_error(429, code, str(exc))


def _sse_error_code(exc: Exception) -> str | None:
    """Machine-readable code for in-band SSE error events — no HTTP status exists
    mid-stream, so the event itself must carry the discriminator. Clients map an
    absent code to "unknown" (never "network": the HTTP connection was healthy)."""
    if isinstance(exc, RunCapExceededError):
        return "run_cap"
    if isinstance(exc, BudgetExceededError):
        return "budget_exhausted"
    if isinstance(exc, MarkingError):
        return "marking_unavailable"
    if isinstance(exc, ValueError):
        return "validation"
    return None


def _audit(
    store: SavedScenarioStore, action: str, target_type: str, target_id: str | None = None
) -> None:
    """Best-effort append to the audit trail (never fails the request)."""
    with contextlib.suppress(Exception):
        store.record_audit(
            action=action,
            target_type=target_type,
            target_id=target_id,
            request_id=current_request_id(),
            ip_hash=current_ip_hash(),
        )


def _build_reproducibility(
    result, portfolio_key: str, requested_as_of: date_type, effective_as_of: date_type
) -> ScenarioReproducibility:
    config = load_config()
    return ScenarioReproducibility(
        model_id=config.vertex_model_id,
        prompt_version=PROMPT_VERSION,
        factor_universe_version=factor_universe_version(),
        events_version=events_version(),
        requested_as_of_date=requested_as_of,
        effective_as_of_date=effective_as_of,
        narrative_mode=result.narrative_mode,
        beta_lookback_weeks=config.beta_lookback_weeks,
        ridge_alpha=config.ridge_alpha,
        regression_spec=regression_spec(
            lookback_weeks=config.beta_lookback_weeks, alpha=config.ridge_alpha
        ),
        selected_event_ids=list(result.selected_event_ids),
        portfolio_holdings=dict(result.portfolio_holdings),
        portfolio_key=portfolio_key,
        nami_engine_version=NAMI_ENGINE_VERSION,
        # Frozen mark-to-market block (None on return-only runs) so a saved MTM
        # scenario re-renders with the same NAV / marks / FX it was run against.
        portfolio_nav=result.portfolio_nav,
        reporting_currency=result.reporting_currency,
        position_quantities=result.position_quantities,
        position_values=result.position_values,
        mark_prices=result.mark_prices,
        price_date_by_ticker=result.price_date_by_ticker,
        fx_rates=result.fx_rates,
        fx_date_by_currency=result.fx_date_by_currency,
    )


def _permissions(mode: AccessMode) -> Permissions:
    return Permissions(
        custom_portfolio=can_use_custom_portfolio(mode),
        free_text_scenario=can_use_free_text_scenario(mode),
        narrative_decomposition=can_use_narrative_decomposition(mode),
    )


def _access_response(request: Request) -> AccessResponse:
    mode = access_mode_for_request(request)
    return AccessResponse(
        access_mode=mode,
        admin_available=configured_passcode() is not None,
        permissions=_permissions(mode),
        latest_market_date=latest_market_date().isoformat(),
        sample_weights_as_of=sample_as_of(),
    )


def _analog_events(events: dict[str, HistoricalEvent]) -> dict[str, AnalogEventResponse]:
    return {
        event_id: AnalogEventResponse(
            event_id=event.id,
            name=event.name,
            start_date=event.start_date.isoformat(),
            end_date=event.end_date.isoformat(),
            tags=list(event.tags),
            description=event.description,
        )
        for event_id, event in events.items()
    }


def _validate_scenario_text(text: str) -> str:
    stripped = text.strip()
    if len(stripped) < MIN_SCENARIO_TEXT_CHARS:
        raise HTTPException(
            status_code=422,
            detail=f"Scenario text must be at least {MIN_SCENARIO_TEXT_CHARS} characters.",
        )
    if len(stripped) > MAX_SCENARIO_TEXT_CHARS:
        raise HTTPException(
            status_code=422,
            detail=f"Scenario text must be {MAX_SCENARIO_TEXT_CHARS} characters or fewer.",
        )
    return stripped


def _reject_visitor_admin_fields(body: ScenarioRunRequest, mode: AccessMode) -> None:
    if mode != "visitor":
        return
    forbidden: list[str] = []
    if body.portfolio_holdings is not None:
        forbidden.append("portfolio_holdings")
    if body.portfolio_name is not None:
        forbidden.append("portfolio_name")
    if body.position_quantities is not None:
        forbidden.append("position_quantities")
    if body.portfolio_nav is not None:
        forbidden.append("portfolio_nav")
    if body.reporting_currency is not None:
        forbidden.append("reporting_currency")
    if body.benchmark is not None:
        forbidden.append("benchmark")
    if forbidden:
        raise HTTPException(
            status_code=403,
            detail=f"Visitor mode does not support: {', '.join(forbidden)}.",
        )


def _resolve_scenario_text(body: ScenarioRunRequest, mode: AccessMode) -> str:
    text = (body.scenario_text or "").strip()
    if mode == "visitor":
        if text:
            return _validate_scenario_text(text)
        if body.sample_scenario_key not in SAMPLE_SCENARIOS:
            raise HTTPException(
                status_code=403,
                detail="Visitor mode requires a sample scenario or custom scenario text.",
            )
        return _validate_scenario_text(SAMPLE_SCENARIOS[body.sample_scenario_key]["text"])

    if text:
        return _validate_scenario_text(text)
    if body.sample_scenario_key in SAMPLE_SCENARIOS:
        return _validate_scenario_text(SAMPLE_SCENARIOS[body.sample_scenario_key]["text"])
    raise HTTPException(status_code=400, detail="Scenario text is required.")


def _resolve_portfolio(
    body: ScenarioRunRequest | BookProfileRequest | EventsReplayRequest, mode: AccessMode
) -> Portfolio | str:
    if mode == "visitor":
        if body.portfolio_key not in SAMPLE_PORTFOLIOS:
            raise HTTPException(status_code=403, detail="Visitor mode requires a sample portfolio.")
        return body.portfolio_key

    if body.portfolio_holdings is not None:
        holdings, errors = validate_holdings(body.portfolio_holdings)
        if errors:
            raise HTTPException(status_code=400, detail={"errors": errors})
        return Portfolio(
            name=body.portfolio_name or "Custom",
            description="User-edited portfolio",
            holdings=holdings,
        )

    if body.portfolio_key in SAMPLE_PORTFOLIOS:
        return body.portfolio_key
    raise HTTPException(status_code=400, detail="Portfolio key or custom holdings are required.")


@api.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _check_firestore() -> None:
    get_firestore_store().list_portfolios()


def _check_gcs(config) -> None:
    # Probe OBJECT-level access (one list page) — that is what the runtime
    # actually uses. `bucket.exists()` needs bucket-level storage.buckets.get,
    # which roles/storage.objectAdmin deliberately lacks, so it reported
    # "unavailable" while object reads/writes worked fine.
    from google.cloud import storage

    client = storage.Client(project=config.google_cloud_project)
    next(iter(client.list_blobs(config.gcs_bucket, max_results=1)), None)


def _check_gemini(config) -> None:
    # Config + client construction (ADC resolution) only — NO paid generation:
    # a real model call would cost money and slow the probe.
    from app.llm.gemini_client import GeminiClient

    GeminiClient(config)


@api.get("/api/ready", response_model=ReadinessResponse)
def ready(response: Response) -> ReadinessResponse:
    """Readiness probe: verifies dependencies are reachable (bounded). Distinct from
    /api/health, which stays a fast, dependency-free liveness check."""
    config = load_config()
    checks = {
        "firestore": _check_firestore,
        "gcs": lambda: _check_gcs(config),
        "gemini": lambda: _check_gemini(config),
    }
    results: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=len(checks)) as pool:
        futures = {name: pool.submit(fn) for name, fn in checks.items()}
        for name, future in futures.items():
            try:
                future.result(timeout=5.0)
                results[name] = "ok"
            except Exception:  # noqa: BLE001 — coarse status only, no detail leak
                results[name] = "unavailable"
    ready_flag = all(status == "ok" for status in results.values())
    if not ready_flag:
        response.status_code = 503
    return ReadinessResponse(ready=ready_flag, checks=results)


@api.get("/api/access", response_model=AccessResponse)
def access(request: Request) -> AccessResponse:
    return _access_response(request)


@api.post("/api/auth/unlock", response_model=AccessResponse)
@limiter.limit(unlock_limit)
def unlock(body: UnlockRequest, request: Request, response: Response) -> AccessResponse:
    config = load_config()
    store = get_firestore_store()
    key = current_ip_hash() or "unknown"

    # Durable, IP-hash-keyed brute-force lockout (global across instances). Read is
    # fail-open on infra error; a real lockout fails closed with 429.
    locked = False
    with contextlib.suppress(Exception):
        locked = (
            store.unlock_failure_count(key, window_seconds=config.unlock_window_seconds)
            >= config.unlock_max_failures
        )
    if locked:
        raise http_error(429, "rate_limited", "Too many unlock attempts; try again later.")

    if not verify_passcode(body.passcode):
        with contextlib.suppress(Exception):
            store.record_failed_unlock(key, window_seconds=config.unlock_window_seconds)
        raise HTTPException(status_code=401, detail="Incorrect passcode.")
    with contextlib.suppress(Exception):
        store.clear_unlock_failures(key)
    if not set_admin_cookie(response, request):
        raise HTTPException(status_code=503, detail="Admin passcode is not configured.")
    _audit(store, "auth.unlock", "auth")
    return AccessResponse(
        access_mode="admin",
        admin_available=True,
        permissions=_permissions("admin"),
        latest_market_date=latest_market_date().isoformat(),
        sample_weights_as_of=sample_as_of(),
    )


@api.post("/api/auth/lock", response_model=AccessResponse)
def lock(request: Request, response: Response) -> AccessResponse:
    clear_admin_cookie(response, request)
    return AccessResponse(
        access_mode="visitor",
        admin_available=configured_passcode() is not None,
        permissions=_permissions("visitor"),
        latest_market_date=latest_market_date().isoformat(),
        sample_weights_as_of=sample_as_of(),
    )


@api.get("/api/portfolios/samples", response_model=list[SamplePortfolioResponse])
def sample_portfolios() -> list[SamplePortfolioResponse]:
    return [
        SamplePortfolioResponse(
            key=key,
            name=portfolio.name,
            description=portfolio.description,
            holdings=dict(portfolio.holdings),
            benchmark=portfolio.benchmark,
        )
        for key, portfolio in SAMPLE_PORTFOLIOS.items()
    ]


@api.get("/api/portfolios/ticker-metadata", response_model=TickerMetadataResponse)
def portfolio_ticker_metadata(tickers: str | None = None) -> TickerMetadataResponse:
    """Sector/country tags for exposure breakdowns.

    Baked from the sample-weight snapshot. With no `tickers` query param, returns
    the full baked map; otherwise returns one entry per requested (comma-separated)
    ticker, defaulting unknown ones to {"Unknown", "Unknown"} so custom books get
    a complete map.
    """
    baked = ticker_metadata()
    if not tickers:
        return TickerMetadataResponse(ticker_meta=baked)
    requested = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    meta = {t: baked.get(t, {"sector": "Unknown", "country": "Unknown"}) for t in requested}
    return TickerMetadataResponse(ticker_meta=meta)


@api.get("/api/factors", response_model=list[FactorMetadataResponse])
def factors() -> list[FactorMetadataResponse]:
    return [FactorMetadataResponse(**item) for item in factor_metadata()]


@api.post("/api/portfolio/validate", response_model=PortfolioValidationResponse)
def validate_portfolio(body: PortfolioValidationRequest) -> PortfolioValidationResponse:
    holdings, errors = validate_holdings(body.holdings)
    return PortfolioValidationResponse(
        ok=not errors,
        errors=errors,
        normalized_holdings=holdings,
        total_weight=sum(holdings.values()),
    )


def _run_free_engine_endpoint(
    body: BookProfileRequest | EventsReplayRequest,
    request: Request,
    compute: Callable[[Portfolio | str], dict],
) -> dict:
    """Shared plumbing for the free (zero-Gemini) engine-only endpoints (book
    profile, events replay): visitor field guard, portfolio resolution, and the
    /run-mirroring error mapping. Rate limiting stays on the endpoint decorators;
    these paths are deliberately NOT metered — no LLM call ever happens here."""
    mode = access_mode_for_request(request)
    if mode == "visitor" and (
        body.portfolio_holdings is not None or body.portfolio_name is not None
    ):
        raise HTTPException(
            status_code=403,
            detail="Visitor mode does not support: portfolio_holdings, portfolio_name.",
        )
    portfolio = _resolve_portfolio(body, mode)
    try:
        return compute(portfolio)
    except MarkingError as exc:
        # FX series unavailable for a non-USD listing — fail closed like a run.
        raise http_error(503, "marking_unavailable", str(exc)) from exc
    except InsufficientHistoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        # Remaining RuntimeErrors are transient market-data failures; MUST stay
        # LAST (the subclasses above take their own statuses).
        raise http_error(503, "unavailable", str(exc)) from exc


@api.post("/api/portfolios/profile", response_model=BookProfileResponse)
@limiter.limit(llm_limit)
def book_profile_endpoint(body: BookProfileRequest, request: Request) -> BookProfileResponse:
    """Free (zero-Gemini) pre-scenario book profile: factor exposures, per-name
    fit quality, and the 1-week idio dispersion floor."""
    return BookProfileResponse(**_run_free_engine_endpoint(body, request, compute_book_profile))


@api.post("/api/portfolios/events-replay", response_model=EventsReplayResponse)
@limiter.limit(llm_limit)
def events_replay_endpoint(body: EventsReplayRequest, request: Request) -> EventsReplayResponse:
    """Free (zero-Gemini) all-events replay: every registry event's realized
    factor moves through the current book's betas, sorted worst-first."""
    return EventsReplayResponse(**_run_free_engine_endpoint(body, request, compute_events_replay))


@api.get("/api/scenarios/samples", response_model=list[SampleScenarioResponse])
def sample_scenarios() -> list[SampleScenarioResponse]:
    return [
        SampleScenarioResponse(key=key, name=value["name"], text=value["text"])
        for key, value in SAMPLE_SCENARIOS.items()
    ]


def _resolve_as_of(body: ScenarioRunRequest, mode: AccessMode) -> date_type | None:
    """Visitor mode is locked to live runs; only admins may backdate."""
    if body.as_of_date is None:
        return None
    if mode == "visitor":
        raise HTTPException(
            status_code=403,
            detail="Visitor mode does not support backdated scenarios.",
        )
    if body.as_of_date > latest_market_date():
        raise HTTPException(
            status_code=422,
            detail="As-of date cannot be after the latest market close.",
        )
    return body.as_of_date


def _resolve_mtm(
    body: ScenarioRunRequest, mode: AccessMode
) -> tuple[dict[str, float] | None, float | None, str | None, Portfolio | str]:
    """Resolve the portfolio AND mark-to-market inputs together. Returns
    (position_quantities, portfolio_nav, reporting_currency, portfolio). MTM
    (quantities OR a NAV scalar) is admin-only.

    Quantity mode builds a PROVISIONAL weight Portfolio from the share tickers —
    `run_scenario` overrides those weights with the price-derived marks, so the
    provisional values are never used for P&L and never hashed (the cache key
    folds on the raw quantities). Non-quantity modes fall back to the normal
    weight/sample-key resolution.
    """
    has_mtm = body.position_quantities is not None or body.portfolio_nav is not None
    if has_mtm and mode == "visitor":
        raise HTTPException(status_code=403, detail="Mark-to-market requires admin mode.")

    currency: str | None = None
    if has_mtm:
        currency = (body.reporting_currency or "USD").upper()
        if currency != "USD":
            raise HTTPException(status_code=422, detail="Only USD reporting is supported in v1.")

    if body.position_quantities is not None:
        quantities, errors = validate_quantities(body.position_quantities)
        if errors:
            raise HTTPException(status_code=400, detail={"errors": errors})
        total = sum(quantities.values())
        provisional = {ticker: qty / total for ticker, qty in quantities.items()}
        mtm_portfolio = Portfolio(
            name=body.portfolio_name or "Custom (MTM)",
            description="User mark-to-market portfolio (share quantities)",
            holdings=provisional,
        )
        return quantities, None, currency, mtm_portfolio

    portfolio = _resolve_portfolio(body, mode)
    if body.portfolio_nav is not None:
        nav, nav_errors = validate_nav(body.portfolio_nav)
        if nav_errors:
            raise HTTPException(status_code=422, detail={"errors": nav_errors})
        return None, nav, currency, portfolio
    return None, None, None, portfolio


@api.post("/api/scenarios/run", response_model=ScenarioRunResponse)
@limiter.limit(llm_limit)
def run_scenario_endpoint(body: ScenarioRunRequest, request: Request) -> ScenarioRunResponse:
    mode = access_mode_for_request(request)
    _reject_visitor_admin_fields(body, mode)
    scenario_text = _resolve_scenario_text(body, mode)
    requested_as_of = _resolve_as_of(body, mode)
    quantities, nav, currency, portfolio = _resolve_mtm(body, mode)
    try:
        gemini, _telemetry, _day = _metered_gemini()
        result = run_scenario(
            scenario_text,
            portfolio,
            gemini=gemini,
            market_date=requested_as_of,
            position_quantities=quantities,
            portfolio_nav=nav,
            reporting_currency=currency,
            benchmark=body.benchmark,
        )
    except BudgetExceededError as exc:
        raise _budget_http_error(exc) from exc
    except MarkingError as exc:
        # Requested valuation could not be marked (missing/stale price or FX):
        # fail closed with 503 rather than return a percentage-only result.
        raise http_error(503, "marking_unavailable", str(exc)) from exc
    except InsufficientHistoryError as exc:
        # A holding has too little weekly history for beta estimation — a
        # RuntimeError subclass that would otherwise surface as a 500.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        # Insufficient analogs / data when backdating; user-facing 422.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        # Remaining RuntimeErrors on this path are market-data failures
        # ("yfinance returned no data for ..."), i.e. transient and retryable —
        # surface as a coded 503 instead of a bare 500. MUST stay LAST: the
        # MarkingError / InsufficientHistoryError subclasses above take their
        # own statuses.
        raise http_error(503, "unavailable", str(exc)) from exc
    cache_key = compute_scenario_cache_key(
        scenario_text, portfolio, market_date=result.market_date, position_quantities=quantities
    )
    portfolio_key = portfolio if isinstance(portfolio, str) else "custom"
    reproducibility = _build_reproducibility(
        result,
        portfolio_key=portfolio_key,
        requested_as_of=result.requested_as_of_date or result.market_date,
        effective_as_of=result.market_date,
    )
    return ScenarioRunResponse(
        result=result,
        analog_events=_analog_events(load_events()),
        cache_key=cache_key,
        reproducibility=reproducibility,
    )


@api.post("/api/scenarios/run-stream")
@limiter.limit(llm_limit)
def run_scenario_stream_endpoint(body: ScenarioRunRequest, request: Request) -> StreamingResponse:
    """Same as /run but emits SSE progress events while the pipeline executes.

    Event payloads:
        {"stage": "<name>", "status": "start"|"done"}
        {"stage": "done", "result": <ScenarioRunResponse>}   # final
        {"stage": "error", "message": "..."}                  # on failure
    """
    mode = access_mode_for_request(request)
    _reject_visitor_admin_fields(body, mode)
    scenario_text = _resolve_scenario_text(body, mode)
    requested_as_of = _resolve_as_of(body, mode)
    quantities, nav, currency, portfolio = _resolve_mtm(body, mode)
    try:
        gemini, _telemetry, _day = _metered_gemini()
    except BudgetExceededError as exc:
        raise _budget_http_error(exc) from exc

    events_q: queue.Queue[dict] = queue.Queue()
    SENTINEL = object()

    def progress(stage: str, status: str) -> None:
        events_q.put({"stage": stage, "status": status})

    def worker() -> None:
        try:
            result = run_scenario(
                scenario_text,
                portfolio,
                gemini=gemini,
                market_date=requested_as_of,
                progress=progress,
                position_quantities=quantities,
                portfolio_nav=nav,
                reporting_currency=currency,
                benchmark=body.benchmark,
            )
            cache_key = compute_scenario_cache_key(
                scenario_text,
                portfolio,
                market_date=result.market_date,
                position_quantities=quantities,
            )
            portfolio_key = portfolio if isinstance(portfolio, str) else "custom"
            reproducibility = _build_reproducibility(
                result,
                portfolio_key=portfolio_key,
                requested_as_of=result.requested_as_of_date or result.market_date,
                effective_as_of=result.market_date,
            )
            response = ScenarioRunResponse(
                result=result,
                analog_events=_analog_events(load_events()),
                cache_key=cache_key,
                reproducibility=reproducibility,
            )
            events_q.put({"stage": "done", "result": response.model_dump(mode="json")})
        except Exception as exc:  # noqa: BLE001 — stream errors as SSE events
            events_q.put({"stage": "error", "message": str(exc), "code": _sse_error_code(exc)})
        finally:
            events_q.put(SENTINEL)

    # Worker threads don't inherit contextvars — copy the request context (request
    # id, ip hash) so the worker's logs correlate with the originating request.
    ctx = contextvars.copy_context()

    def generator() -> Generator[str, None, None]:
        thread = threading.Thread(target=lambda: ctx.run(worker), daemon=True)
        thread.start()
        while True:
            event = events_q.get()
            if event is SENTINEL:
                break
            yield f"data: {json.dumps(event)}\n\n"
        thread.join(timeout=1.0)

    return StreamingResponse(generator(), media_type="text/event-stream")


@api.post("/api/scenarios/adjust-shocks", response_model=ScenarioRunResponse)
@limiter.limit(llm_limit)
def adjust_shocks_endpoint(body: ScenarioAdjustRequest, request: Request) -> ScenarioRunResponse:
    mode = access_mode_for_request(request)
    if not can_use_free_text_scenario(mode):
        raise HTTPException(status_code=403, detail="Shock adjustment requires admin mode.")

    if (body.overrides is None) == (body.adjustment_text is None):
        raise HTTPException(
            status_code=400,
            detail="Exactly one of `overrides` or `adjustment_text` must be set.",
        )

    try:
        gemini, _telemetry, _day = _metered_gemini()
        result = adjust_scenario_shocks(
            body.cache_key,
            gemini=gemini,
            overrides=body.overrides,
            adjustment_text=body.adjustment_text,
            benchmark=body.benchmark,
        )
    except BudgetExceededError as exc:
        raise _budget_http_error(exc) from exc
    except LookupError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except MarkingError as exc:
        # Re-marking the adjusted result failed (missing/stale price or FX) —
        # fail closed. MUST precede RuntimeError (MarkingError subclasses it).
        raise http_error(503, "marking_unavailable", str(exc)) from exc
    except InsufficientHistoryError as exc:
        # MUST precede RuntimeError (it subclasses it): too little weekly
        # history is a data problem, NOT the LLM's "rerun_required" rejection —
        # mislabeling it would make the UI offer a rerun CTA that cannot help.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        # scope="rerun_required" from the LLM patch path. The message is the
        # rejection_reason the UI surfaces to the user — it is LLM free text, so
        # the X-Error-Code header is the only sound way for clients to detect it.
        raise http_error(422, "rerun_required", str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ScenarioRunResponse(
        result=result,
        analog_events=_analog_events(load_events()),
        cache_key=body.cache_key,
    )


@api.post("/api/scenarios/decompose", response_model=ScenarioRunResponse)
@limiter.limit(llm_limit)
def decompose_endpoint(
    body: NarrativeDecompositionRequest,
    request: Request,
) -> ScenarioRunResponse:
    mode = access_mode_for_request(request)
    if not can_use_narrative_decomposition(mode):
        raise HTTPException(status_code=403, detail="Narrative decomposition requires admin mode.")

    config = load_config()
    try:
        # The WHOLE compute stays inside the try: the metered client raises
        # BudgetExceededError mid-pipeline (during the 2^N subset Gemini calls),
        # not just at construction.
        gemini, _telemetry, _day = _metered_gemini()
        scenario_cache = CloudStorageCache(config.gcs_bucket, prefix="scenario_cache")
        decomposition_cache = CloudStorageCache(config.gcs_bucket, prefix="decomposition_cache")
        result = compute_narrative_shapley(
            body.result,
            config=config,
            gemini=gemini,
            cache=scenario_cache,
            decomposition_cache=decomposition_cache,
            market_date=body.result.market_date,
        )
    except BudgetExceededError as exc:
        raise _budget_http_error(exc) from exc
    except InsufficientHistoryError as exc:
        # Subset reruns re-estimate betas; surface a data problem as 422, not 500.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ScenarioRunResponse(result=result, analog_events=_analog_events(load_events()))


@api.post("/api/scenarios/decompose-stream")
@limiter.limit(llm_limit)
def decompose_stream_endpoint(
    body: NarrativeDecompositionRequest, request: Request
) -> StreamingResponse:
    """SSE variant of /decompose. Emits subset-progress so the UI can show
    "X / Y subset runs" during the (slow) 2^N pipeline reruns.

    Event payloads:
        {"stage": "subset", "done": <int>, "total": <int>}
        {"stage": "done", "result": <ScenarioRunResponse>}   # final
        {"stage": "error", "message": "..."}                  # on failure
    """
    mode = access_mode_for_request(request)
    if not can_use_narrative_decomposition(mode):
        raise HTTPException(status_code=403, detail="Narrative decomposition requires admin mode.")

    config = load_config()
    try:
        gemini, _telemetry, _day = _metered_gemini()
    except BudgetExceededError as exc:
        raise _budget_http_error(exc) from exc
    scenario_cache = CloudStorageCache(config.gcs_bucket, prefix="scenario_cache")
    decomposition_cache = CloudStorageCache(config.gcs_bucket, prefix="decomposition_cache")

    events_q: queue.Queue[dict] = queue.Queue()
    SENTINEL = object()

    def progress(done: int, total: int) -> None:
        events_q.put({"stage": "subset", "done": done, "total": total})

    def worker() -> None:
        try:
            result = compute_narrative_shapley(
                body.result,
                config=config,
                gemini=gemini,
                cache=scenario_cache,
                decomposition_cache=decomposition_cache,
                market_date=body.result.market_date,
                progress=progress,
            )
            response = ScenarioRunResponse(
                result=result, analog_events=_analog_events(load_events())
            )
            events_q.put({"stage": "done", "result": response.model_dump(mode="json")})
        except Exception as exc:  # noqa: BLE001 — stream errors as SSE events
            events_q.put({"stage": "error", "message": str(exc), "code": _sse_error_code(exc)})
        finally:
            events_q.put(SENTINEL)

    ctx = contextvars.copy_context()

    def generator() -> Generator[str, None, None]:
        thread = threading.Thread(target=lambda: ctx.run(worker), daemon=True)
        thread.start()
        while True:
            event = events_q.get()
            if event is SENTINEL:
                break
            yield f"data: {json.dumps(event)}\n\n"
        thread.join(timeout=1.0)

    return StreamingResponse(generator(), media_type="text/event-stream")


# ============================================================================
# Saved analytics (Firestore-backed) — Phase 11
# ============================================================================


def _require_admin(request: Request, action: str) -> None:
    if not can_use_free_text_scenario(access_mode_for_request(request)):
        raise HTTPException(status_code=403, detail=f"{action} requires admin mode.")


@contextlib.contextmanager
def _store_errors() -> Generator[None, None, None]:
    """Map saved-analytics store failures to a coded 503 whose detail names the
    real cause. Firestore problems surface as google-cloud exception types (NOT
    RuntimeError) — missing database, missing permissions, bad local credentials
    — and would otherwise leak as a bare 500 "Internal Server Error" that hides
    the actionable message (e.g. the store's composite-index instructions)."""
    try:
        yield
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — surfaced with detail, never swallowed
        raise http_error(503, "unavailable", f"Saved-analytics store unavailable: {exc}") from exc


@api.post("/api/saved-scenarios", response_model=SavedScenarioRecord)
def save_scenario_endpoint(body: SaveScenarioRequest, request: Request) -> SavedScenarioRecord:
    _require_admin(request, "Saving scenarios")
    full = SavedScenarioRecord(
        id="pending",
        name=body.name,
        tags=body.tags,
        notes=body.notes,
        created_at=utcnow(),
        owner_label=body.owner_label,
        scenario_text=body.result.scenario_text,
        portfolio_snapshot_ref=body.portfolio_snapshot_ref,
        portfolio_holdings=dict(body.result.portfolio_holdings),
        portfolio_key=body.result.portfolio_key,
        portfolio_name=body.result.portfolio_name,
        analog_events_snapshot=body.analog_events_snapshot,
        result=body.result,
        reproducibility=body.reproducibility,
    )
    with _store_errors():
        store = get_firestore_store()
        try:
            record_id = store.save_scenario(full)
        except ValueError as exc:
            # Firestore doc-size guard — 413, NOT a store-availability failure.
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        _audit(store, "scenario.save", "scenario", record_id)
    return full.model_copy(update={"id": record_id})


@api.get("/api/saved-scenarios", response_model=list[SavedScenarioListItem])
def list_saved_scenarios_endpoint(
    request: Request, tag: str | None = None, limit: int = 50
) -> list[SavedScenarioListItem]:
    _require_admin(request, "Listing saved scenarios")
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be in [1, 200].")
    with _store_errors():
        store = get_firestore_store()
        return store.list_scenarios(tag=tag, limit=limit)


@api.get("/api/saved-scenarios/{scenario_id}", response_model=SavedScenarioRecord)
def get_saved_scenario_endpoint(scenario_id: str, request: Request) -> SavedScenarioRecord:
    _require_admin(request, "Reading saved scenarios")
    with _store_errors():
        store = get_firestore_store()
        rec = store.get_scenario(scenario_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"Saved scenario {scenario_id} not found.")
    return rec


@api.get("/api/saved-scenarios/{scenario_id}/json")
def download_saved_scenario_json(scenario_id: str, request: Request) -> Response:
    _require_admin(request, "Downloading saved scenarios")
    with _store_errors():
        store = get_firestore_store()
        rec = store.get_scenario(scenario_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"Saved scenario {scenario_id} not found.")
    body = rec.model_dump_json(indent=2)
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in rec.name)[:64]
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="nami-scenario-{safe_name}-{scenario_id}.json"'
        },
    )


@api.delete("/api/saved-scenarios/{scenario_id}", status_code=204)
def delete_saved_scenario_endpoint(scenario_id: str, request: Request) -> Response:
    _require_admin(request, "Deleting saved scenarios")
    with _store_errors():
        store = get_firestore_store()
        store.delete_scenario(scenario_id)
        _audit(store, "scenario.delete", "scenario", scenario_id)
    return Response(status_code=204)


@api.post("/api/portfolios", response_model=SavedPortfolioRecord)
def create_portfolio_endpoint(body: SavePortfolioRequest, request: Request) -> SavedPortfolioRecord:
    _require_admin(request, "Creating portfolios")
    rec = SavedPortfolioRecord(
        id="pending",
        name=body.name,
        description=body.description,
        created_at=utcnow(),
        owner_label=body.owner_label,
    )
    with _store_errors():
        store = get_firestore_store()
        pid = store.save_portfolio(rec)
        _audit(store, "portfolio.create", "portfolio", pid)
    return rec.model_copy(update={"id": pid})


@api.get("/api/portfolios", response_model=list[SavedPortfolioRecord])
def list_saved_portfolios_endpoint(request: Request) -> list[SavedPortfolioRecord]:
    _require_admin(request, "Listing saved portfolios")
    with _store_errors():
        store = get_firestore_store()
        return store.list_portfolios()


@api.post(
    "/api/portfolios/{portfolio_id}/snapshots",
    response_model=PortfolioSnapshotRecord,
)
def create_portfolio_snapshot_endpoint(
    portfolio_id: str, body: PortfolioSnapshotRequest, request: Request
) -> PortfolioSnapshotRecord:
    _require_admin(request, "Creating portfolio snapshots")
    with _store_errors():
        store = get_firestore_store()
        portfolio_exists = store.get_portfolio(portfolio_id) is not None
    if not portfolio_exists:
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found.")
    # Validate snapshot is not future-dated relative to the latest NYSE close
    # (the same live anchor used by run_scenario).
    today_effective = latest_market_date()
    if body.as_of_date > today_effective:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Snapshot as_of_date {body.as_of_date.isoformat()} is in the "
                f"future relative to the latest NYSE close ({today_effective.isoformat()})."
            ),
        )
    snap = PortfolioSnapshotRecord(
        id="pending",
        portfolio_id=portfolio_id,
        as_of_date=body.as_of_date,
        holdings=body.holdings,
        notes=body.notes,
        created_at=utcnow(),
        owner_label=body.owner_label,
    )
    with _store_errors():
        sid = store.save_snapshot(portfolio_id, snap)
        _audit(store, "snapshot.create", "snapshot", sid)
    return snap.model_copy(update={"id": sid})


@api.get(
    "/api/portfolios/{portfolio_id}/snapshots",
    response_model=list[PortfolioSnapshotRecord],
)
def list_portfolio_snapshots_endpoint(
    portfolio_id: str, request: Request
) -> list[PortfolioSnapshotRecord]:
    _require_admin(request, "Listing portfolio snapshots")
    with _store_errors():
        store = get_firestore_store()
        if store.get_portfolio(portfolio_id) is None:
            raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found.")
        return store.list_snapshots(portfolio_id)


@api.get(
    "/api/portfolios/{portfolio_id}/snapshots/{snapshot_id}",
    response_model=PortfolioSnapshotRecord,
)
def get_portfolio_snapshot_endpoint(
    portfolio_id: str, snapshot_id: str, request: Request
) -> PortfolioSnapshotRecord:
    _require_admin(request, "Reading portfolio snapshots")
    with _store_errors():
        store = get_firestore_store()
        snap = store.get_snapshot(portfolio_id, snapshot_id)
    if snap is None:
        raise HTTPException(
            status_code=404,
            detail=f"Snapshot {snapshot_id} not found under portfolio {portfolio_id}.",
        )
    return snap


# ============================================================================
# Trust surfaces — audit, data export/delete, status, usage
# ============================================================================


@api.get("/api/audit", response_model=list[AuditEntry])
def audit_log_endpoint(request: Request, limit: int = 100) -> list[AuditEntry]:
    _require_admin(request, "Reading the audit log")
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="limit must be in [1, 500].")
    with _store_errors():
        store = get_firestore_store()
        return [AuditEntry.model_validate(entry) for entry in store.list_audit(limit=limit)]


@api.get("/api/export")
def export_all_endpoint(request: Request) -> Response:
    """Admin-only full export of saved analytics (scenarios + portfolios +
    snapshot subcollections) as one downloadable JSON attachment."""
    _require_admin(request, "Exporting data")
    with _store_errors():
        store = get_firestore_store()
        payload = store.export_all()
    body = json.dumps(payload, indent=2, default=str)
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="nami-export.json"'},
    )


@api.post("/api/admin/purge")
def purge_all_endpoint(body: PurgeRequest, request: Request) -> dict[str, int]:
    """Admin-only destructive purge of all saved scenarios + portfolios (+ their
    snapshot subcollections). Requires an explicit confirmation token. The audit
    log is preserved and a final purge event is written after deletion."""
    _require_admin(request, "Purging data")
    if body.confirm != "DELETE":
        raise HTTPException(
            status_code=400, detail='Confirmation required: send {"confirm":"DELETE"}.'
        )
    with _store_errors():
        store = get_firestore_store()
        counts = store.purge_all()
        _audit(store, "admin.purge", "all")
    return counts


@api.get("/api/status", response_model=StatusResponse)
def status_endpoint(request: Request) -> StatusResponse:
    """Public status + guardrails. Spend (`est_cost_today_usd`) is admin-only."""
    config = load_config()
    is_admin = access_mode_for_request(request) == "admin"
    usage: dict = {}
    ready_flag = True
    # Status must ALWAYS return 200 — store construction itself can raise
    # (bad local credentials, missing database), and `ready` should honestly
    # flip false instead of the old no-op suppress that never did.
    try:
        store = get_firestore_store()
        with contextlib.suppress(Exception):
            usage = store.usage_daily(today_key())
        store.list_portfolios()
    except Exception:  # noqa: BLE001 — coarse readiness only
        ready_flag = False
    return StatusResponse(
        service="nami",
        nami_engine_version=NAMI_ENGINE_VERSION,
        prompt_version=PROMPT_VERSION,
        model_id=config.vertex_model_id,
        environment=config.environment,
        ready=ready_flag,
        disclaimer=DISCLAIMER_SHORT,
        rate_limits={"llm": config.rate_limit_llm, "unlock": config.rate_limit_unlock},
        daily_cost_cap_usd=config.daily_llm_cost_cap_usd,
        daily_run_cap=config.daily_llm_run_cap,
        runs_today=int(usage.get("runs", 0)),
        est_cost_today_usd=float(usage.get("spent", 0.0)) if is_admin else None,
    )


@api.get("/api/usage", response_model=UsageSummary)
def usage_endpoint(request: Request) -> UsageSummary:
    _require_admin(request, "Reading usage")
    config = load_config()
    day = today_key()
    usage: dict = {}
    with contextlib.suppress(Exception):
        usage = get_firestore_store().usage_daily(day)
    return UsageSummary(
        day=day,
        runs=int(usage.get("runs", 0)),
        calls=int(usage.get("calls", 0)),
        tokens_in=int(usage.get("tokens_in", 0)),
        tokens_out=int(usage.get("tokens_out", 0)),
        spent_usd=float(usage.get("spent", 0.0)),
        reserved_usd=float(usage.get("reserved", 0.0)),
        cost_cap_usd=config.daily_llm_cost_cap_usd,
        run_cap=config.daily_llm_run_cap,
    )


@api.get("/api/docs/methodology")
def methodology() -> PlainTextResponse:
    if not METHODOLOGY_PATH.exists():
        raise HTTPException(status_code=404, detail="Methodology document not found.")
    return PlainTextResponse(METHODOLOGY_PATH.read_text(encoding="utf-8"))


@api.get("/api/meta")
def meta() -> dict[str, str]:
    return {"disclaimer": DISCLAIMER_SHORT}


if FRONTEND_DIST.exists():
    api.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


@api.get("/{path:path}", include_in_schema=False)
def frontend(path: str) -> FileResponse:
    index = FRONTEND_DIST / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="Frontend build not found.")
    requested = FRONTEND_DIST / path
    if path and requested.is_file() and requested.resolve().is_relative_to(FRONTEND_DIST.resolve()):
        return FileResponse(requested)
    return FileResponse(index)
