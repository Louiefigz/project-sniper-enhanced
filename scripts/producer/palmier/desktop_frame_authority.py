"""Resolve one exact Desktop frame authority for every editable stage."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from fingerprints import file_sha256
from palmier.desktop_audio_master_contract import \
    validate_mastered_stereo_assets
from palmier.master import MasterFacts, approved_master
from palmier.mcp_client import PalmierError


@dataclass(frozen=True)
class DesktopFrameAuthority:
    """Exact frame extent inherited from an approved, sealed visual master."""

    frames: int
    source: str
    master: MasterFacts | None = None


def _positive_frame(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PalmierError(f"{label} has no positive exact end frame")
    return value


def _visual(inputs: Any, authority: Any) -> DesktopFrameAuthority:
    master = approved_master(
        inputs.out_dir, inputs.plan_path, inputs.manifest_path,
        authority.plan_hash)
    return DesktopFrameAuthority(
        _positive_frame(master.end_frame, "approved visual master"),
        "sealed-cut-delivery", master)


def _ready_reference(project: dict) -> dict:
    reference = project.get("exactMasterReference")
    valid = isinstance(reference, dict) \
        and reference.get("status") == "ready" \
        and reference.get("startFrame") == 0 \
        and reference.get("hidden") is True \
        and reference.get("muted") is True
    if not valid:
        raise PalmierError(
            "later Desktop stage has no ready exact-master frame authority")
    path, digest = reference.get("assetPath"), reference.get("assetHash")
    if not isinstance(path, str) or not os.path.isfile(path) \
            or os.path.islink(path) or not isinstance(digest, str) \
            or file_sha256(path) != digest:
        raise PalmierError("exact-master frame-authority bytes are stale")
    return reference


def _cross_check_audio(project: dict, reference: dict, frames: int) -> None:
    audio = project.get("audioAuthority")
    route = audio.get("masterRoute") if isinstance(audio, dict) else None
    if route is None:
        return
    if not isinstance(route, dict):
        raise PalmierError("mastered-stereo frame authority is malformed")
    validate_mastered_stereo_assets(route)
    actual = (
        route.get("startFrame"), route.get("endFrame"),
        route.get("sourceFinalHash"))
    expected = (0, frames, reference.get("assetHash"))
    if actual != expected:
        raise PalmierError(
            "exact-master and mastered-stereo frame authorities disagree")


def resolve_desktop_frame_authority(
        inputs: Any, authority: Any, project: dict) -> DesktopFrameAuthority:
    """Resolve sealed initial frames or inherit the verified ready reference."""
    if inputs.stage == "visual":
        return _visual(inputs, authority)
    if inputs.stage not in {"repair", "revision"}:
        raise PalmierError(
            f"stage {inputs.stage!r} has no exact-master frame authority")
    reference = _ready_reference(project)
    frames = _positive_frame(
        reference.get("endFrame"), "ready exact-master reference")
    _cross_check_audio(project, reference, frames)
    return DesktopFrameAuthority(frames, "ready-exact-master-reference")
