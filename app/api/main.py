from __future__ import annotations

import json
import queue
import threading
from collections.abc import Generator
from datetime import date as date_type
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.api.portfolio_validation import validate_holdings
from app.api.samples import SAMPLE_SCENARIOS
from app.api.schemas import (
    AccessResponse,
    AnalogEventResponse,
    NarrativeDecompositionRequest,
    Permissions,
    PortfolioSnapshotRecord,
    PortfolioSnapshotRequest,
    PortfolioValidationRequest,
    PortfolioValidationResponse,
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
    UnlockRequest,
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
from app.data.sample_portfolios import SAMPLE_PORTFOLIOS, Portfolio
from app.factors.analogs import HistoricalEvent, events_version, load_events
from app.factors.universe import factor_universe_version
from app.llm.gemini_client import GeminiClient
from app.llm.narrative_shapley import compute_narrative_shapley
from app.llm.prompts import PROMPT_VERSION
from app.llm.scenario import (
    adjust_scenario_shocks,
    compute_scenario_cache_key,
    run_scenario,
)
from app.utils.calendar import resolve_effective_market_date
from app.utils.disclaimers import DISCLAIMER_SHORT

ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST = ROOT / "frontend" / "dist"
METHODOLOGY_PATH = ROOT / "docs" / "methodology.md"

api = FastAPI(title="nami API", version="0.1.0")

# nami engine version used in reproducibility metadata. Bumps with any
# release-significant change to the engine; not in lockstep with PROMPT_VERSION.
NAMI_ENGINE_VERSION = "0.1.0"


_firestore_store: SavedScenarioStore | None = None


def get_firestore_store() -> SavedScenarioStore:
    """Lazy Firestore singleton. Tests override via FastAPI dependency_overrides
    or by monkeypatching `app.api.main._firestore_store`."""
    global _firestore_store
    if _firestore_store is None:
        config = load_config()
        _firestore_store = FirestoreStore(project_id=config.google_cloud_project)
    return _firestore_store


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
        selected_event_ids=list(result.selected_event_ids),
        portfolio_holdings=dict(result.portfolio_holdings),
        portfolio_key=portfolio_key,
        nami_engine_version=NAMI_ENGINE_VERSION,
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


def _resolve_scenario_text(body: ScenarioRunRequest, mode: AccessMode) -> str:
    if mode == "visitor":
        if body.sample_scenario_key not in SAMPLE_SCENARIOS:
            raise HTTPException(status_code=403, detail="Visitor mode requires a sample scenario.")
        return SAMPLE_SCENARIOS[body.sample_scenario_key]["text"]

    text = (body.scenario_text or "").strip()
    if text:
        return text
    if body.sample_scenario_key in SAMPLE_SCENARIOS:
        return SAMPLE_SCENARIOS[body.sample_scenario_key]["text"]
    raise HTTPException(status_code=400, detail="Scenario text is required.")


def _resolve_portfolio(body: ScenarioRunRequest, mode: AccessMode) -> Portfolio | str:
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


@api.get("/api/access", response_model=AccessResponse)
def access(request: Request) -> AccessResponse:
    return _access_response(request)


@api.post("/api/auth/unlock", response_model=AccessResponse)
def unlock(body: UnlockRequest, request: Request, response: Response) -> AccessResponse:
    if not verify_passcode(body.passcode):
        raise HTTPException(status_code=401, detail="Incorrect passcode.")
    if not set_admin_cookie(response, request):
        raise HTTPException(status_code=503, detail="Admin passcode is not configured.")
    return AccessResponse(
        access_mode="admin",
        admin_available=True,
        permissions=_permissions("admin"),
    )


@api.post("/api/auth/lock", response_model=AccessResponse)
def lock(request: Request, response: Response) -> AccessResponse:
    clear_admin_cookie(response, request)
    return AccessResponse(
        access_mode="visitor",
        admin_available=configured_passcode() is not None,
        permissions=_permissions("visitor"),
    )


@api.get("/api/portfolios/samples", response_model=list[SamplePortfolioResponse])
def sample_portfolios() -> list[SamplePortfolioResponse]:
    return [
        SamplePortfolioResponse(
            key=key,
            name=portfolio.name,
            description=portfolio.description,
            holdings=dict(portfolio.holdings),
        )
        for key, portfolio in SAMPLE_PORTFOLIOS.items()
    ]


@api.post("/api/portfolio/validate", response_model=PortfolioValidationResponse)
def validate_portfolio(body: PortfolioValidationRequest) -> PortfolioValidationResponse:
    holdings, errors = validate_holdings(body.holdings)
    return PortfolioValidationResponse(
        ok=not errors,
        errors=errors,
        normalized_holdings=holdings,
        total_weight=sum(holdings.values()),
    )


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
    return body.as_of_date


@api.post("/api/scenarios/run", response_model=ScenarioRunResponse)
def run_scenario_endpoint(body: ScenarioRunRequest, request: Request) -> ScenarioRunResponse:
    mode = access_mode_for_request(request)
    scenario_text = _resolve_scenario_text(body, mode)
    portfolio = _resolve_portfolio(body, mode)
    requested_as_of = _resolve_as_of(body, mode)
    try:
        result = run_scenario(scenario_text, portfolio, market_date=requested_as_of)
    except ValueError as exc:
        # Insufficient analogs / data when backdating; user-facing 422.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    cache_key = compute_scenario_cache_key(scenario_text, portfolio, market_date=result.market_date)
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
def run_scenario_stream_endpoint(body: ScenarioRunRequest, request: Request) -> StreamingResponse:
    """Same as /run but emits SSE progress events while the pipeline executes.

    Event payloads:
        {"stage": "<name>", "status": "start"|"done"}
        {"stage": "done", "result": <ScenarioRunResponse>}   # final
        {"stage": "error", "message": "..."}                  # on failure
    """
    mode = access_mode_for_request(request)
    scenario_text = _resolve_scenario_text(body, mode)
    portfolio = _resolve_portfolio(body, mode)
    requested_as_of = _resolve_as_of(body, mode)

    events_q: queue.Queue[dict] = queue.Queue()
    SENTINEL = object()

    def progress(stage: str, status: str) -> None:
        events_q.put({"stage": stage, "status": status})

    def worker() -> None:
        try:
            result = run_scenario(
                scenario_text, portfolio, market_date=requested_as_of, progress=progress
            )
            cache_key = compute_scenario_cache_key(
                scenario_text, portfolio, market_date=result.market_date
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
            events_q.put({"stage": "error", "message": str(exc)})
        finally:
            events_q.put(SENTINEL)

    def generator() -> Generator[str, None, None]:
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        while True:
            event = events_q.get()
            if event is SENTINEL:
                break
            yield f"data: {json.dumps(event)}\n\n"
        thread.join(timeout=1.0)

    return StreamingResponse(generator(), media_type="text/event-stream")


@api.post("/api/scenarios/adjust-shocks", response_model=ScenarioRunResponse)
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
        result = adjust_scenario_shocks(
            body.cache_key,
            overrides=body.overrides,
            adjustment_text=body.adjustment_text,
        )
    except LookupError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except RuntimeError as exc:
        # scope="rerun_required" from the LLM patch path. The message is the
        # rejection_reason the UI surfaces to the user.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ScenarioRunResponse(
        result=result,
        analog_events=_analog_events(load_events()),
        cache_key=body.cache_key,
    )


@api.post("/api/scenarios/decompose", response_model=ScenarioRunResponse)
def decompose_endpoint(
    body: NarrativeDecompositionRequest,
    request: Request,
) -> ScenarioRunResponse:
    mode = access_mode_for_request(request)
    if not can_use_narrative_decomposition(mode):
        raise HTTPException(status_code=403, detail="Narrative decomposition requires admin mode.")

    config = load_config()
    gemini = GeminiClient(config)
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
    return ScenarioRunResponse(result=result, analog_events=_analog_events(load_events()))


# ============================================================================
# Saved analytics (Firestore-backed) — Phase 11
# ============================================================================


def _require_admin(request: Request, action: str) -> None:
    if not can_use_free_text_scenario(access_mode_for_request(request)):
        raise HTTPException(status_code=403, detail=f"{action} requires admin mode.")


@api.post("/api/saved-scenarios", response_model=SavedScenarioRecord)
def save_scenario_endpoint(body: SaveScenarioRequest, request: Request) -> SavedScenarioRecord:
    _require_admin(request, "Saving scenarios")
    store = get_firestore_store()
    record_id = ""  # filled by store
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
    try:
        record_id = store.save_scenario(full)
    except ValueError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    return full.model_copy(update={"id": record_id})


@api.get("/api/saved-scenarios", response_model=list[SavedScenarioListItem])
def list_saved_scenarios_endpoint(
    request: Request, tag: str | None = None, limit: int = 50
) -> list[SavedScenarioListItem]:
    _require_admin(request, "Listing saved scenarios")
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be in [1, 200].")
    store = get_firestore_store()
    try:
        return store.list_scenarios(tag=tag, limit=limit)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@api.get("/api/saved-scenarios/{scenario_id}", response_model=SavedScenarioRecord)
def get_saved_scenario_endpoint(scenario_id: str, request: Request) -> SavedScenarioRecord:
    _require_admin(request, "Reading saved scenarios")
    store = get_firestore_store()
    rec = store.get_scenario(scenario_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"Saved scenario {scenario_id} not found.")
    return rec


@api.get("/api/saved-scenarios/{scenario_id}/json")
def download_saved_scenario_json(scenario_id: str, request: Request) -> Response:
    _require_admin(request, "Downloading saved scenarios")
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
    store = get_firestore_store()
    store.delete_scenario(scenario_id)
    return Response(status_code=204)


@api.post("/api/portfolios", response_model=SavedPortfolioRecord)
def create_portfolio_endpoint(body: SavePortfolioRequest, request: Request) -> SavedPortfolioRecord:
    _require_admin(request, "Creating portfolios")
    store = get_firestore_store()
    rec = SavedPortfolioRecord(
        id="pending",
        name=body.name,
        description=body.description,
        created_at=utcnow(),
        owner_label=body.owner_label,
    )
    pid = store.save_portfolio(rec)
    return rec.model_copy(update={"id": pid})


@api.get("/api/portfolios", response_model=list[SavedPortfolioRecord])
def list_saved_portfolios_endpoint(request: Request) -> list[SavedPortfolioRecord]:
    _require_admin(request, "Listing saved portfolios")
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
    store = get_firestore_store()
    if store.get_portfolio(portfolio_id) is None:
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found.")
    # Validate snapshot is not future-dated relative to today's effective trading day.
    today_effective = resolve_effective_market_date(date_type.today())
    if body.as_of_date > today_effective:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Snapshot as_of_date {body.as_of_date.isoformat()} is in the "
                f"future relative to today's NYSE close ({today_effective.isoformat()})."
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
    sid = store.save_snapshot(portfolio_id, snap)
    return snap.model_copy(update={"id": sid})


@api.get(
    "/api/portfolios/{portfolio_id}/snapshots",
    response_model=list[PortfolioSnapshotRecord],
)
def list_portfolio_snapshots_endpoint(
    portfolio_id: str, request: Request
) -> list[PortfolioSnapshotRecord]:
    _require_admin(request, "Listing portfolio snapshots")
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
    store = get_firestore_store()
    snap = store.get_snapshot(portfolio_id, snapshot_id)
    if snap is None:
        raise HTTPException(
            status_code=404,
            detail=f"Snapshot {snapshot_id} not found under portfolio {portfolio_id}.",
        )
    return snap


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
