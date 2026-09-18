"""Paged, resumable mutation progress for Desktop Palmier revision sets."""
from __future__ import annotations

from palmier.desktop_state import read_record
from palmier.mcp_client import PalmierError


def _revision_manifest(state: dict) -> dict | None:
    value = read_record(state["operations"]["path"], "operation manifest")
    revision = value.get("revision")
    return revision if isinstance(revision, dict) else None


def initialize_revision_progress(state: dict, revision: object) -> None:
    """Reset progress for one newly authorized revision set."""
    if not isinstance(revision, dict):
        state.pop("revisionProgress", None)
        return
    state["revisionProgress"] = {
        "revisionSetId": revision["revisionSetId"],
        "verifiedMutationIds": [], "currentPage": 0,
        "pageCount": len(revision.get("pages") or []),
    }


def _mutation_ids(binding: object) -> list[str]:
    if not isinstance(binding, dict):
        return []
    values = binding.get("mutationIds")
    if isinstance(values, list):
        return [value for value in values if isinstance(value, str)]
    value = binding.get("mutationId")
    return [value] if isinstance(value, str) else []


def _pages(state: dict) -> list[dict]:
    revision = _revision_manifest(state)
    rows = revision.get("pages") if isinstance(revision, dict) else None
    return [row for row in rows or [] if isinstance(row, dict)]


def _first_open_page(state: dict) -> int:
    verified = set((state.get("revisionProgress") or {}).get(
        "verifiedMutationIds") or [])
    for page in _pages(state):
        ids = set(page.get("mutationIds") or [])
        if ids - verified:
            return int(page.get("index", 0))
    return len(_pages(state))


def authorize_revision_binding(state: dict, binding: object) -> None:
    """Require every revision mutation to belong to the current page."""
    if state.get("stage") != "revision":
        return
    ids = _mutation_ids(binding)
    if not ids:
        raise PalmierError("Palmier revision mutation is not worklist-bound")
    progress = state.get("revisionProgress") or {}
    verified = set(progress.get("verifiedMutationIds") or [])
    if verified.intersection(ids):
        raise PalmierError("Palmier revision mutation was already verified")
    page_index = _first_open_page(state)
    pages = _pages(state)
    allowed = set(pages[page_index].get("mutationIds") or []) \
        if page_index < len(pages) else set()
    if not set(ids) <= allowed:
        raise PalmierError("Palmier revision mutation is outside the current page")


def record_revision_binding(state: dict, binding: object) -> None:
    """Mark verified mutation ids and advance the durable page cursor."""
    if state.get("stage") != "revision":
        return
    progress = state.get("revisionProgress")
    if not isinstance(progress, dict):
        raise PalmierError("Palmier revision progress disappeared")
    current = list(progress.get("verifiedMutationIds") or [])
    for ident in _mutation_ids(binding):
        if ident not in current:
            current.append(ident)
    progress["verifiedMutationIds"] = current
    progress["currentPage"] = _first_open_page(state)


def revision_complete(state: dict) -> bool:
    """Whether every exact mutation in the active revision was verified."""
    if state.get("stage") != "revision":
        return True
    return _first_open_page(state) >= len(_pages(state))
