"""Early body-only workload/effective-track checks before the first graphic seal.

Structural128-row vocabulary is not executable workload. The existing prefix
oracle admits complete native input surfaces, not only simultaneous overlays.
No rows, source pixels, user intent or QC checks are removed to fit its limits.
"""
from __future__ import annotations

from cut_preview_io import digest
from graphics.exit_on_cut import apply_exit_on_cut
from guided_opening_frames import executable_frames, full_program_frames
from guided_opening_inputs import OpeningInputs
from opening_prefix_contract import GRAPH_WORKLOAD_POLICY, PrefixClock, PrefixRanges, _clock
from guided_caption_profile import caption_profile
from guided_caption_layers import caption_page_bound


def admit_body_workload(inputs: OpeningInputs, original: dict) -> dict:
    """Reuse exact frame/header policy and enforce both real graph surface bounds."""
    authority = inputs.documents["authority"]
    width, height = authority["target"]["width"], authority["target"]["height"]
    ranges = PrefixRanges((authority["core"]["startFrame"], authority["core"]["endFrameExclusive"]),
        (authority["review"]["startFrame"], authority["review"]["endFrameExclusive"]))
    _clock(PrefixClock(authority["frameRate"], authority["totalFrames"], width, height), ranges)
    full, opening = full_program_frames(inputs), executable_frames(inputs)
    pixel_count = width * height
    costs = {"fullGraphInputPixels": (len(full) + 1) * pixel_count,
             "openingGraphInputPixels": (len(opening) + 1) * pixel_count}
    if any(value > GRAPH_WORKLOAD_POLICY["maxGraphInputPixels"] for value in costs.values()):
        raise RuntimeError(f"body prefix native-surface workload unsupported: {len(full)} full graphics, "
            f"{len(opening)} opening graphics at {width}x{height}; graph limit "
            f"{GRAPH_WORKLOAD_POLICY['maxGraphInputPixels']} pixels; no graphics were rendered")
    base = original["fullProgram"]["base"]
    if type(base["sizeBytes"]) is not int or not 0 < base["sizeBytes"] <= 2 * 1024 ** 3:
        raise RuntimeError("body held base exceeds existing2GiB assembly/retention file class")
    _effective_track(inputs)
    captions = caption_page_bound(PrefixClock(authority["frameRate"], authority["totalFrames"], width, height),
        (len(full), len(opening)), authority["review"]["endFrameExclusive"]) if caption_profile(inputs.value.get("profile")) else None
    return {"schemaVersion": 1, "kind": "guided-body-native-graph-admission",
        "scope": "conservative-workload-not-rendered-pixels-quality-or-throughput",
        "policy": GRAPH_WORKLOAD_POLICY, "canvas": [width, height], "fullGraphics": len(full),
        "openingGraphics": len(opening), **costs, **({"captionWorkload": captions} if captions is not None else {}),
        "bodyRendered": False, "deliveryApproved": False}


def _effective_track(inputs: OpeningInputs) -> None:
    """Do not silently accept any assembler-side projection absent from held intent."""
    plan = inputs.documents["candidatePlan"]
    effective, clamped = apply_exit_on_cut(plan)
    if clamped or digest(effective) != digest(plan.get("graphicsTrack") or []):
        raise RuntimeError("body effective graphics projection differs from original reviewed entries")
