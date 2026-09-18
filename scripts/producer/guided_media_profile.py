"""Versioned private media classes; explicit geometry is not framing approval.

The historical class is unchanged. The new class executes only a submitted
manual fill crop through ordinary reframe, never interprets a raw request or
enables captions, tracking, grading or other finishing lanes.
"""
from __future__ import annotations

import math

from producer_config import REFRAME_SPLIT
from guided_caption_profile import (CAPTION_PROFILE, CAPTION_SHORT_PROFILE, CAPTION_BODY_PROFILE,
    CAPTION_SHORT_BODY_PROFILE, SCREENED_CAPTION_PROFILE, SCREENED_CAPTION_SHORT_PROFILE,
    SCREENED_CAPTION_BODY_PROFILE, SCREENED_CAPTION_SHORT_BODY_PROFILE, caption_preset_plan)

OPENING_PROFILE = "unity-source-float-own-screen-v1"
SHORT_PROFILE = "unity-source-float-manual-short-own-screen-v1"
BODY_PROFILE = "held-source-float-own-screen-body-v1"
SHORT_BODY_PROFILE = "held-source-float-manual-short-own-screen-body-v1"
_OMITTED_PROFILE = object()


def opening_profile(value: object) -> str:
    """Parse a known execution class without claiming its plan is admissible."""
    if type(value) is not str or value not in (OPENING_PROFILE, SHORT_PROFILE, CAPTION_PROFILE, CAPTION_SHORT_PROFILE,
                                               SCREENED_CAPTION_PROFILE, SCREENED_CAPTION_SHORT_PROFILE):
        raise RuntimeError("private opening media profile is unsupported")
    return value


def body_profile(value: object) -> str:
    """Preserve a one-to-one opening/body class relation, never upgrade a result."""
    return {OPENING_PROFILE: BODY_PROFILE, SHORT_PROFILE: SHORT_BODY_PROFILE,
            CAPTION_PROFILE: CAPTION_BODY_PROFILE, CAPTION_SHORT_PROFILE: CAPTION_SHORT_BODY_PROFILE,
            SCREENED_CAPTION_PROFILE: SCREENED_CAPTION_BODY_PROFILE,
            SCREENED_CAPTION_SHORT_PROFILE: SCREENED_CAPTION_SHORT_BODY_PROFILE}[opening_profile(value)]


def manual_profile(value: object) -> bool:
    """Both explicit manual classes share the same actually proved crop geometry."""
    return type(value) is str and value in (SHORT_PROFILE, CAPTION_SHORT_PROFILE, SCREENED_CAPTION_SHORT_PROFILE)


def assert_no_presenter_layouts(plan: dict) -> None:
    """Reject present unsupported intent, including null, empty and false values."""
    if "presenterLayouts" in plan:
        raise RuntimeError("legacy opening profile has no presenterLayouts execution owner")


def manual_short_plan(plan: dict) -> dict:
    """Require exact current-candidate geometry and explicit captions-off intent."""
    return _manual_short_plan(plan, False)


def manual_caption_short_plan(plan: dict) -> dict:
    """Require unchanged manual geometry plus explicit qualified caption preset."""
    caption_preset_plan(plan)
    return _manual_short_plan(plan, True)


def _manual_short_plan(plan: dict, captioned: bool) -> dict:
    """Shared crop checks; the ordinary prepared BASE remains caption-free."""
    assert_no_presenter_layouts(plan)
    return manual_short_geometry(plan, captioned)


def manual_short_geometry(plan: dict, captioned: bool) -> dict:
    """Geometry validation only; callers separately enforce their exact lane/profile.

    This shared helper grants no presenter execution capability and removes no
    candidate field. The historical public profile validators retain their fence.
    """
    target, reframe, captions = (plan.get(key) for key in ("target", "reframe", "captions"))
    if type(target) is not dict or target.get("mode") != "short" \
            or type(target.get("width")) is not int or target["width"] != 1080 \
            or type(target.get("height")) is not int or target["height"] != 1920:
        raise RuntimeError("manual short profile requires explicit1080x1920 short target")
    if type(reframe) is not dict or set(reframe) != {"layout", "crop", "track"} \
            or reframe["layout"] != "fill" or reframe["track"] is not False:
        raise RuntimeError("manual short requires only explicit fill/crop/track:false")
    if type(captions) is not dict or captions.get("burn") is not captioned:
        raise RuntimeError("manual short requires explicit captions.burn=false; captioned short is unqualified")
    if any(plan.get(key) for key in ("overlays", "presenter")):
        raise RuntimeError("manual short has unsupported additional visual intent")
    crop = reframe["crop"]
    if type(crop) is not list or len(crop) != 4 or any(
            type(item) not in (int, float) or not math.isfinite(item) for item in crop):
        raise RuntimeError("manual short crop requires four finite nonboolean numbers")
    x, y, width, height = crop
    if not (0 <= x <= 1 and 0 <= y <= 1 and width >= REFRAME_SPLIT["crop_min_frac"]
            and height >= REFRAME_SPLIT["crop_min_frac"] and x + width <= 1 and y + height <= 1):
        raise RuntimeError("manual short crop is outside the existing normalized source bounds")
    cuts = plan.get("cutTrack")
    if type(cuts) is not list or not cuts or any(type(row) is not dict for row in cuts):
        raise RuntimeError("manual short needs an explicit nonempty cut track")
    source = cuts[0].get("sourceId")
    if type(source) is not str or not source or any(row.get("sourceId") != source for row in cuts):
        raise RuntimeError("manual short supports exactly one used source and one fixed crop")
    return {"sourceId": source, "reframe": reframe, "canvas": [1080, 1920], "captionsBurned": False}


def profile_for_plan(plan: dict, held_profile: object = _OMITTED_PROFILE) -> str:
    """Select fresh screened intent or validate an EXACT held compatible old class.

    The held token is already part of input/authority hashes, never a request to
    downgrade new work. No result is rewritten or upgraded by this selector.
    """
    assert_no_presenter_layouts(plan)
    selected = _fresh_profile(plan)
    if held_profile is _OMITTED_PROFILE:
        return selected
    opening_profile(held_profile)
    compatible = {SCREENED_CAPTION_PROFILE: (SCREENED_CAPTION_PROFILE, CAPTION_PROFILE),
                  SCREENED_CAPTION_SHORT_PROFILE: (SCREENED_CAPTION_SHORT_PROFILE, CAPTION_SHORT_PROFILE)}
    if held_profile not in compatible.get(selected, (selected,)):
        raise RuntimeError("held opening profile is incompatible with the exact candidate plan")
    return held_profile


def _fresh_profile(plan: dict) -> str:
    """Only fresh authored caption plans select the new explicit screened class."""
    target, reframe = plan.get("target") or {}, plan.get("reframe") or {}
    if type(plan.get("captionsTrack")) is dict:
        caption_preset_plan(plan)
        if target["mode"] == "short":
            manual_caption_short_plan(plan)
            return SCREENED_CAPTION_SHORT_PROFILE
        return SCREENED_CAPTION_PROFILE
    if type(target) is dict and target.get("mode") == "short" \
            and type(reframe) is dict and "crop" in reframe:
        manual_short_plan(plan)
        return SHORT_PROFILE
    return OPENING_PROFILE
