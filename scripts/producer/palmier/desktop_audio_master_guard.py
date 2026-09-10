"""Mutation and stage guards for a verified mastered-stereo route."""
from __future__ import annotations

from palmier.desktop_audio_master_binding import (
    expected_route_args, mastered_step)
from palmier.desktop_audio_master_route import assert_standalone_route
from palmier.desktop_audio_master_types import PLACEMENT_OP
from palmier.mcp_client import PalmierError


def _contains_identity(value: object, identities: set[str]) -> bool:
    if isinstance(value, str):
        return value in identities
    if isinstance(value, list):
        return any(_contains_identity(item, identities) for item in value)
    if isinstance(value, dict):
        return any(_contains_identity(item, identities)
                   for item in value.values())
    return False


def _touched_track_indices(args: dict) -> set[int]:
    result = {value for value in args.get("remove") or []
              if isinstance(value, int) and not isinstance(value, bool)}
    for row in args.get("set") or []:
        if isinstance(row, dict) and isinstance(row.get("index"), int) \
                and not isinstance(row["index"], bool):
            result.add(row["index"])
    for key in ("trackIndex", "toTrack", "fromTrack"):
        value = args.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            result.add(value)
    for key in ("entries", "moves", "splits"):
        for row in args.get(key) or []:
            if isinstance(row, dict):
                result.update(_touched_track_indices(row))
    return result


def assert_mastered_stereo_mutation_allowed(
        tool: str, args: dict, state: dict, timeline: dict) -> None:
    """Force provisional routing next and protect a ready route thereafter."""
    provisional = state.get("audioMasterRoute")
    if isinstance(provisional, dict):
        if tool != "manage_tracks" \
                or args != expected_route_args(state, timeline):
            raise PalmierError(
                "mastered-stereo route must be isolated before more edits")
        return
    authority = state.get("audioAuthority")
    route = authority.get("masterRoute") if isinstance(authority, dict) else None
    if not isinstance(route, dict) or route.get("routeKind") != "standalone-audio":
        return
    location = assert_standalone_route(route, timeline)
    identities = {value for value in (
        route.get("clipId"), route.get("mediaRef"))
        if isinstance(value, str)}
    if _contains_identity(args, identities):
        raise PalmierError("mastered-stereo route identities are immutable")
    if location.track_index in _touched_track_indices(args):
        raise PalmierError("mastered-stereo route track is immutable")


def assert_mastered_stereo_ready(state: dict, timeline: dict,
                                 coverage: dict | None) -> None:
    """Revalidate an authority that has already completed routing."""
    authority = state.get("audioAuthority")
    route = authority.get("masterRoute") if isinstance(authority, dict) else None
    if not isinstance(route, dict) or route.get("routeKind") != "standalone-audio":
        return
    if not isinstance(coverage, dict) or coverage.get("complete") is not True:
        raise PalmierError("mastered-stereo route readback is incomplete")
    assert_standalone_route(route, timeline)


def require_mastered_stereo_ready(state: dict, timeline: dict,
                                  coverage: dict | None) -> None:
    """Block stage completion when the declared route is not authoritative."""
    authority = state.get("audioAuthority")
    has_authority = isinstance(authority, dict) \
        and isinstance(authority.get("masterRoute"), dict)
    if mastered_step(state, PLACEMENT_OP) is None and not has_authority:
        return
    if isinstance(state.get("audioMasterRoute"), dict):
        raise PalmierError("mastered-stereo route isolation is incomplete")
    if not isinstance(authority, dict):
        raise PalmierError("mastered-stereo route has not been placed")
    assert_mastered_stereo_ready(state, timeline, coverage)
