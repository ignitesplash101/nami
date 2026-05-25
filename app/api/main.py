from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.api.portfolio_validation import validate_holdings
from app.api.samples import SAMPLE_SCENARIOS
from app.api.schemas import (
    AccessResponse,
    AnalogEventResponse,
    NarrativeDecompositionRequest,
    Permissions,
    PortfolioValidationRequest,
    PortfolioValidationResponse,
    SamplePortfolioResponse,
    SampleScenarioResponse,
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
from app.data.sample_portfolios import SAMPLE_PORTFOLIOS, Portfolio
from app.factors.analogs import HistoricalEvent, load_events
from app.llm.gemini_client import GeminiClient
from app.llm.narrative_shapley import compute_narrative_shapley
from app.llm.scenario import run_scenario
from app.utils.disclaimers import DISCLAIMER_SHORT

ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST = ROOT / "frontend" / "dist"
METHODOLOGY_PATH = ROOT / "docs" / "methodology.md"

api = FastAPI(title="nami API", version="0.1.0")


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


@api.post("/api/scenarios/run", response_model=ScenarioRunResponse)
def run_scenario_endpoint(body: ScenarioRunRequest, request: Request) -> ScenarioRunResponse:
    mode = access_mode_for_request(request)
    scenario_text = _resolve_scenario_text(body, mode)
    portfolio = _resolve_portfolio(body, mode)
    result = run_scenario(scenario_text, portfolio)
    return ScenarioRunResponse(result=result, analog_events=_analog_events(load_events()))


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
