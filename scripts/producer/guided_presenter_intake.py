"""Explicit CURRENT presenter metadata routing, never renderer dispatch.

Historical public profile selectors remain strict. Current inputs keep their
actual V8 proposal, V2 bindings and 14 documents; no plan is stripped or upgraded.
Source color, live ownership, caption clearance and result qualification remain
separate unresolved execution prerequisites, not facts established here.
"""
from __future__ import annotations

from audio.render_audio_authority import SOURCE_FLOAT_POLICY_V2, audio_policy_reason
from guided_media_profile import SHORT_PROFILE, body_profile, manual_profile, opening_profile, profile_for_plan
from guided_presenter_profile import (
    PRESENTER_PROFILE, PRESENTER_SHORT_PROFILE, PRESENTER_CAPTION_PROFILE, PRESENTER_CAPTION_SHORT_PROFILE,
    presenter_body_profile, presenter_caption_profile, presenter_graph_workload, presenter_manual_profile,
    presenter_opening_profile, presenter_profile_for_plan, assert_presenter_graphics_disjoint,
)
from opening_prefix_contract import PrefixClock

_OPENING = (PRESENTER_PROFILE, PRESENTER_SHORT_PROFILE, PRESENTER_CAPTION_PROFILE, PRESENTER_CAPTION_SHORT_PROFILE)
_BODY = tuple(presenter_body_profile(value) for value in _OPENING)


def is_presenter_profile(value: object) -> bool:
    """Identify only explicit new opening tokens; never infer from plan truthiness."""
    return type(value) is str and value in _OPENING


def is_presenter_body_profile(value: object) -> bool:
    """Recognize exact new body syntax without interpreting any execution flag."""
    return type(value) is str and value in _BODY


def current_opening_profile(value: object) -> str:
    """Add only explicit current intake, preserving every legacy parser refusal."""
    return presenter_opening_profile(value) if is_presenter_profile(value) else opening_profile(value)


def current_body_profile(value: object) -> str:
    """Keep the original opening class paired one-to-one with its body metadata."""
    return presenter_body_profile(value) if is_presenter_profile(value) else body_profile(value)


def current_manual_profile(value: object) -> bool:
    """Manual field comparison is conditional; legacy helpers retain their tokens."""
    return presenter_manual_profile(value) if is_presenter_profile(value) else manual_profile(value)


def manual_preserved_fields(value: object) -> tuple[str, ...]:
    """Uncaptioned manual inputs preserve captions-off as well as submitted crop."""
    return ("reframe", "captions") if value in (SHORT_PROFILE, PRESENTER_SHORT_PROFILE) else ("reframe",)


def _matched_clock(inputs: object) -> tuple[str, PrefixClock]:
    """Bind supplied input AND authority to the exact original native plan class."""
    from guided_opening_inputs import OpeningInputs

    if type(inputs) is not OpeningInputs or not is_presenter_profile(inputs.value.get("profile")):
        raise RuntimeError("presenter current intake requires an explicit new profile")
    authority, plan = inputs.documents["authority"], inputs.documents["candidatePlan"]
    clock = PrefixClock(authority["frameRate"], authority["totalFrames"],
                        authority["target"]["width"], authority["target"]["height"])
    profile = presenter_profile_for_plan(plan, clock)
    if inputs.value["profile"] != profile or authority.get("profile") != profile:
        raise RuntimeError("presenter current input/authority profile differs from exact plan class")
    return profile, clock


def _declared_frames(inputs: object, profile: str, clock: PrefixClock) -> list[dict]:
    """Inspect lower metadata only; this cannot replace the registry/audio gate."""
    from guided_presenter_frames import presenter_program_frames

    plan = inputs.documents["candidatePlan"]
    rows = presenter_program_frames(inputs)
    windows = plan["presenterLayouts"]
    assert_presenter_graphics_disjoint(rows, windows, clock.total_frames)
    assets = {row["assetId"]: row for row in inputs.documents["readinessPacket"]["evidence"]["presenterPolicy"]["assets"]}
    canvases = tuple((assets[row["layout"]["assetId"]]["width"], assets[row["layout"]["assetId"]]["height"])
                     for row in windows)
    presenter_graph_workload(clock, len(rows), presenter_caption_profile(profile), canvases)
    return rows


def presenter_metadata_frames(inputs: object) -> list[dict]:
    """Validate original intent only after the unchanged registry/audio policy passes."""
    profile, clock = _matched_clock(inputs)
    reason = audio_policy_reason(inputs.documents["candidatePlan"], SOURCE_FLOAT_POLICY_V2)
    if reason:
        raise RuntimeError(reason)
    return _declared_frames(inputs, profile, clock)


def current_profile_for_inputs(inputs: object) -> str:
    """Revalidate current metadata; old held profiles still use their original selector."""
    if not is_presenter_profile(inputs.value["profile"]):
        return profile_for_plan(inputs.documents["candidatePlan"], inputs.value["profile"])
    presenter_metadata_frames(inputs)
    return inputs.value["profile"]
