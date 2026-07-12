from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

AREA_DOCS = {
    "engine.md",
    "llm-pipeline.md",
    "data-market.md",
    "api-backend.md",
    "frontend.md",
    "design-system.md",
    "deploy-ops.md",
    "phase-log.md",
}


def test_agent_doc_routers_are_byte_identical() -> None:
    claude = (ROOT / "CLAUDE.md").read_bytes()
    agents = (ROOT / "AGENTS.md").read_bytes()
    assert claude == agents, (
        "CLAUDE.md and AGENTS.md are the same router for different tool "
        "ecosystems and must stay byte-identical: edit one, copy it over the "
        "other in the same commit."
    )


def test_agent_area_docs_exist() -> None:
    present = {p.name for p in (ROOT / "docs" / "agents").glob("*.md")}
    missing = AREA_DOCS - present
    assert not missing, (
        f"missing agent area docs: {sorted(missing)} — the router in CLAUDE.md "
        "points at every doc in this set."
    )


def test_router_links_every_area_doc() -> None:
    router = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    unlinked = [name for name in AREA_DOCS if f"docs/agents/{name}" not in router]
    assert not unlinked, f"router does not link: {sorted(unlinked)}"
