"""Citation extraction from Gemini's grounding_metadata.

This module is the single point of contract with `google.genai`'s grounding response
shape. SDK upgrades that move fields around touch only this file.
"""

from __future__ import annotations

from typing import Any

from app.llm.schemas import Citation


def extract_citations(response: Any) -> list[Citation]:
    """Pull Citations from `response.candidates[0].grounding_metadata`.

    The genai SDK returns grounding metadata as a structured object containing
    `grounding_chunks` (each with a `web` field carrying `uri` and `title`) plus
    `grounding_supports` and optionally `search_entry_point`. We preserve the
    chunk-level metadata in `Citation.grounding_metadata` so the rendering layer
    can satisfy Vertex's grounding-display requirements (Search Suggestions, etc.).

    Returns [] when no grounding metadata is present (the caller decides whether
    that's acceptable).
    """
    if not response or not getattr(response, "candidates", None):
        return []

    candidate = response.candidates[0]
    metadata = getattr(candidate, "grounding_metadata", None)
    if metadata is None:
        return []

    chunks = getattr(metadata, "grounding_chunks", None) or []
    citations: list[Citation] = []
    for chunk in chunks:
        web = getattr(chunk, "web", None)
        if web is None:
            continue
        url = getattr(web, "uri", None)
        if not url:
            continue
        citations.append(
            Citation(
                url=url,
                title=getattr(web, "title", None),
                snippet=None,
                grounding_metadata=_chunk_to_dict(chunk),
            )
        )
    return citations


def _chunk_to_dict(chunk: Any) -> dict[str, Any]:
    """Best-effort dict conversion of a grounding chunk for round-trip preservation."""
    if hasattr(chunk, "model_dump"):
        return chunk.model_dump()
    if hasattr(chunk, "to_dict"):
        return chunk.to_dict()
    web = getattr(chunk, "web", None)
    if web is None:
        return {}
    return {
        "web": {
            "uri": getattr(web, "uri", None),
            "title": getattr(web, "title", None),
        }
    }


def has_grounding(response: Any) -> bool:
    """True iff the response carries non-empty grounding metadata."""
    return len(extract_citations(response)) > 0
