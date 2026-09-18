"""Explicit bounded caption-preset intent, not transcription or visual approval.

The initial caption profile uses the existing captured Producer line/karaoke
defaults for ALL kept words. It does not infer custom typography, corrections,
groups, placement, scene suppression, chapters or legacy subtitle intent.
"""
from __future__ import annotations

from captions.caption_contract import validate_caption_track

CAPTION_PROFILE = "unity-source-float-own-screen-caption-pages-v1"
CAPTION_SHORT_PROFILE = "unity-source-float-manual-short-own-screen-caption-pages-v1"
CAPTION_BODY_PROFILE = "held-source-float-own-screen-caption-pages-body-v1"
CAPTION_SHORT_BODY_PROFILE = "held-source-float-manual-short-own-screen-caption-pages-body-v1"
SCREENED_CAPTION_PROFILE = "unity-source-float-own-screen-caption-layout-v2"
SCREENED_CAPTION_SHORT_PROFILE = "unity-source-float-manual-short-own-screen-caption-layout-v2"
SCREENED_CAPTION_BODY_PROFILE = "held-source-float-own-screen-caption-layout-body-v2"
SCREENED_CAPTION_SHORT_BODY_PROFILE = "held-source-float-manual-short-own-screen-caption-layout-body-v2"
_EXCLUDED = ("captionCorrectionLedger", "captionStyles", "captionChapters", "dialogueCaptionAuthority")


def caption_profile(value: object) -> bool:
    """No old token or omitted value silently opts into caption execution."""
    from guided_presenter_profile import presenter_caption_profile

    return type(value) is str and value in (CAPTION_PROFILE, CAPTION_SHORT_PROFILE,
                                            SCREENED_CAPTION_PROFILE, SCREENED_CAPTION_SHORT_PROFILE) \
        or presenter_caption_profile(value)


def screened_caption_profile(value: object) -> bool:
    """Only explicit new opening tokens require real caption/graphic screening."""
    from guided_presenter_profile import presenter_caption_profile

    return type(value) is str and value in (SCREENED_CAPTION_PROFILE, SCREENED_CAPTION_SHORT_PROFILE) \
        or presenter_caption_profile(value)


def caption_screen_fields(profile: object) -> set[str]:
    """Old results cannot acquire a new-policy screening statement."""
    from guided_presenter_profile import PRESENTER_CAPTION_BODY_PROFILE, PRESENTER_CAPTION_SHORT_BODY_PROFILE

    return {"captionLayoutScreen"} if screened_caption_profile(profile) or profile in (
        SCREENED_CAPTION_BODY_PROFILE, SCREENED_CAPTION_SHORT_BODY_PROFILE,
        PRESENTER_CAPTION_BODY_PROFILE, PRESENTER_CAPTION_SHORT_BODY_PROFILE) else set()


def caption_preset_plan(plan: dict) -> dict:
    """Validate the exact submitted preset without normalizing the candidate."""
    target = plan.get("target")
    if type(target) is not dict or target.get("mode") not in ("short", "longform"):
        raise RuntimeError("caption preset needs an explicit supported target")
    expected = (1080, 1920) if target["mode"] == "short" else (1920, 1080)
    if any(type(target.get(key)) is not int for key in ("width", "height")) \
            or (target["width"], target["height"]) != expected:
        raise RuntimeError("caption preset requires the existing exact native compiler destination")
    captions = plan.get("captions")
    if type(captions) is not dict or set(captions) != {"burn"} or captions["burn"] is not True:
        raise RuntimeError("caption preset requires only explicit captions.burn=true")
    track = plan.get("captionsTrack")
    if type(track) is not dict or set(track) != {"schemaVersion", "source", "defaultPolicy", "groups"} \
            or type(track.get("schemaVersion")) is not int or track["schemaVersion"] != 1 \
            or track.get("defaultPolicy") not in ("line", "karaoke") or track.get("groups") != []:
        raise RuntimeError("caption preset requires explicit all-kept line/karaoke with no custom groups")
    validated = validate_caption_track(track)
    if validated != track:
        raise RuntimeError("caption preset must not normalize submitted caption authority")
    if any(key in plan for key in _EXCLUDED) or plan.get("chapters"):
        raise RuntimeError("caption preset has unqualified correction/style/chapter/alternate authority")
    if any(plan.get(key) for key in ("overlays", "presenter")):
        raise RuntimeError("caption preset has unsupported additional visual intent")
    return track


def caption_full_fields(profile: object) -> set[str]:
    """Historical full-program records keep their exact original field set."""
    return {"captionProjection"} if caption_profile(profile) else set()
