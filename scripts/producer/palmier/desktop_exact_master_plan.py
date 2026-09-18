"""Plan the approved master as a disabled reference in an editable build."""
from __future__ import annotations

import os
import re
from fractions import Fraction
from typing import Any

from ingest_probe import probe_media
from palmier.master import approved_master
from palmier.mcp_client import PalmierError

ELEMENT_ID = "exact-master-reference"
MEDIA_KEY = "exact-master-reference"
ADD_OP = "exact-master-reference-add"
DISABLE_OP = "exact-master-reference-disable"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _project_facts(project: dict) -> tuple[str, int, int, int]:
    settings = project.get("projectSettings") or {}
    values = (settings.get("fps"), settings.get("width"),
              settings.get("height"))
    valid = all(not isinstance(value, bool)
                and isinstance(value, (int, float)) and value > 0
                for value in values)
    if not valid:
        raise PalmierError(
            "exact-master reference has no complete project timing/canvas")
    try:
        rate = Fraction(str(values[0]))
    except (ValueError, ZeroDivisionError) as exc:
        raise PalmierError(
            "exact-master project rate is not a usable scalar") from exc
    canvas_exact = all(float(value).is_integer() for value in values[1:])
    if rate.denominator != 1 or not canvas_exact:
        raise PalmierError(
            "Palmier exposes no exact rational rate for this non-integer project")
    return (f"{rate.numerator}/1", rate.numerator,
            int(values[1]), int(values[2]))


def _master_rate(master: Any) -> str:
    raw = getattr(master, "frame_rate", None)
    if not isinstance(raw, str):
        raise PalmierError("approved exact-master has no exact r_frame_rate")
    try:
        rate = Fraction(raw)
    except (ValueError, ZeroDivisionError) as exc:
        raise PalmierError(
            "approved exact-master r_frame_rate is malformed") from exc
    if rate <= 0:
        raise PalmierError("approved exact-master r_frame_rate is not positive")
    return f"{rate.numerator}/{rate.denominator}"


def _validate_master(master: Any, project: dict,
                     target_frames: int) -> dict:
    frame_rate, fps, width, height = _project_facts(project)
    probe = probe_media(master.path)
    if probe.audio_present is not True:
        raise PalmierError(
            "approved exact-master reference has no audio to prove muted")
    if not _SHA256.fullmatch(str(master.content_hash)):
        raise PalmierError("approved exact-master reference hash is malformed")
    actual = (_master_rate(master), master.width, master.height)
    expected = (frame_rate, width, height)
    if actual != expected:
        raise PalmierError(
            f"approved exact-master reference {actual} != project {expected}")
    if master.end_frame != target_frames or target_frames <= 0:
        raise PalmierError(
            "approved exact-master duration differs from editable build")
    return {
        "assetHash": master.content_hash,
        "assetPath": os.path.abspath(master.path),
        "startFrame": 0, "endFrame": target_frames,
        "fps": fps, "frameRate": frame_rate,
        "width": width, "height": height,
        "audioChannels": probe.audio_channels,
        "audioSampleRate": probe.audio_sample_rate,
    }


def prepare_exact_master_reference(inputs: Any, authority: Any,
                                   project: dict,
                                   frame_authority: Any) -> tuple[list[dict], dict]:
    """Return exact import/add/disable steps or fail on stale master authority."""
    master = getattr(frame_authority, "master", None)
    target_frames = getattr(frame_authority, "frames", None)
    if master is None:
        master = approved_master(
            inputs.out_dir, inputs.plan_path, inputs.manifest_path,
            authority.plan_hash)
    if isinstance(target_frames, bool) or not isinstance(target_frames, int):
        raise PalmierError("exact-master frame authority is malformed")
    facts = _validate_master(master, project, target_frames)
    name = f"Sniper · exact master · {facts['assetHash'][:8]}"
    steps = [
        {
            "op": "import", "key": MEDIA_KEY, "elementId": ELEMENT_ID,
            "lane": "exact-master-reference", "path": facts["assetPath"],
            "importName": name, "approvedPlanHash": authority.plan_hash,
        },
        {
            "op": ADD_OP, "lane": "exact-master-reference",
            "elementId": ELEMENT_ID, "mediaKey": MEDIA_KEY,
            **facts, "trackPolicy": "auto-create-dedicated-linked-pair",
            "requiredNextOp": DISABLE_OP,
        },
        {
            "op": DISABLE_OP, "lane": "exact-master-reference",
            "elementId": ELEMENT_ID,
            "videoFlags": {"hidden": True, "syncLocked": True},
            "audioFlags": {"muted": True, "syncLocked": True},
        },
    ]
    capability = {
        "status": "required", "assetHash": facts["assetHash"],
        "endFrame": facts["endFrame"], "audioPresent": True,
        "visibility": "hidden-track", "audibility": "muted-track",
        "connectedReadbackQualified": False,
    }
    return steps, capability
