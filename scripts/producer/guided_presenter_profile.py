"""Explicit presenter metadata classes, not activated production dispatch.

The owner still authenticates actual V8 request/policy and V2 bindings, acquires
selected media, proves original-prefix pixels and separately screens captions.
These helpers never strip a plan into a legacy profile or grant delivery QC.
"""
from __future__ import annotations

from fractions import Fraction

from audio.program_finish_contract import finishing_reason
from graphics.presenter_layout_contract import PresenterCanvas
from guided_caption_layers import caption_page_bound
from guided_caption_profile import caption_preset_plan
from guided_media_profile import manual_short_geometry
from guided_presenter_assets import _windows
from guided_presenter_probe_contract import canonical_presenter_rate
from opening_prefix_contract import GRAPH_WORKLOAD_POLICY, MAX_CLIPS, PrefixClock, valid_canvas

PRESENTER_PROFILE = "unity-source-float-own-screen-presenter-layout-v1"
PRESENTER_SHORT_PROFILE = "unity-source-float-manual-short-own-screen-presenter-layout-v1"
PRESENTER_CAPTION_PROFILE = "unity-source-float-own-screen-presenter-caption-layout-v1"
PRESENTER_CAPTION_SHORT_PROFILE = "unity-source-float-manual-short-own-screen-presenter-caption-layout-v1"
PRESENTER_BODY_PROFILE = "held-source-float-own-screen-presenter-layout-body-v1"
PRESENTER_SHORT_BODY_PROFILE = "held-source-float-manual-short-own-screen-presenter-layout-body-v1"
PRESENTER_CAPTION_BODY_PROFILE = "held-source-float-own-screen-presenter-caption-layout-body-v1"
PRESENTER_CAPTION_SHORT_BODY_PROFILE = "held-source-float-manual-short-own-screen-presenter-caption-layout-body-v1"
_BODY = {PRESENTER_PROFILE: PRESENTER_BODY_PROFILE, PRESENTER_SHORT_PROFILE: PRESENTER_SHORT_BODY_PROFILE,
         PRESENTER_CAPTION_PROFILE: PRESENTER_CAPTION_BODY_PROFILE,
         PRESENTER_CAPTION_SHORT_PROFILE: PRESENTER_CAPTION_SHORT_BODY_PROFILE}


def presenter_opening_profile(value: object) -> str:
    """Read only a distinct new token; historical tokens never change their meaning."""
    if type(value) is not str or value not in _BODY:
        raise RuntimeError("presenter opening profile is unsupported")
    return value


def presenter_body_profile(value: object) -> str:
    """Keep exact one-to-one opening/body pairing, never upgrade an old result."""
    return _BODY[presenter_opening_profile(value)]


def presenter_caption_profile(value: object) -> bool:
    """A captioned presenter needs both existing graphic and new subject clearance."""
    return type(value) is str and value in (PRESENTER_CAPTION_PROFILE, PRESENTER_CAPTION_SHORT_PROFILE)


def presenter_manual_profile(value: object) -> bool:
    """This class accepts explicit geometry, not new tracking or crop authoring."""
    return type(value) is str and value in (PRESENTER_SHORT_PROFILE, PRESENTER_CAPTION_SHORT_PROFILE)


def _canvas(plan: dict, clock: PrefixClock) -> bool:
    """Require exact native destination and bounded actual clock metadata."""
    canonical_presenter_rate(clock.frame_rate)
    rate = Fraction(clock.frame_rate)
    if clock.frame_rate != f"{rate.numerator}/{rate.denominator}" or not 1 <= rate <= 60 \
            or type(clock.total_frames) is not int or not 1 <= clock.total_frames <= 72000:
        raise RuntimeError("presenter profile requires the existing bounded exact guided clock")
    target = plan.get("target")
    if type(target) is not dict or target.get("mode") not in ("longform", "short"):
        raise RuntimeError("presenter needs an explicit longform/manual-short target")
    short = target["mode"] == "short"
    dimensions = (1080, 1920) if short else (1920, 1080)
    if any(type(target.get(key)) is not int for key in ("width", "height")) \
            or (target["width"], target["height"]) != dimensions or (clock.width, clock.height) != dimensions:
        raise RuntimeError("presenter needs the exact native1080 destination")
    _windows(plan.get("presenterLayouts"), PresenterCanvas(*dimensions, clock.total_frames, "yuv420p"))
    return short


def presenter_profile_for_plan(plan: dict, clock: PrefixClock) -> str:
    """Validate nonempty declared geometry/preset without selecting a live workflow."""
    if type(plan) is not dict or type(clock) is not PrefixClock:
        raise RuntimeError("presenter profile requires exact plan and whole-clock metadata")
    short = _canvas(plan, clock)
    if any(key in plan for key in ("presenter", "overlays")):
        raise RuntimeError("presenter profile has inherited incompatible visual intent")
    unsupported = ("titleCards", "brollTrack", "baselineLook", "punchIns", "transitions",
                   "persistentText", "faceBBoxNorm", "chapters")
    if any(plan.get(key) for key in unsupported):
        raise RuntimeError("presenter profile has additional unqualified finishing lanes")
    # audioEnhance/audioGain finish in the shared program master (audio/program_finish_bus);
    # they are validated explicitly here, never dropped and never accepted malformed.
    finishing = finishing_reason(plan)
    if finishing:
        raise RuntimeError("presenter profile rejects " + finishing)
    if any(key in plan for key in ("captionCorrectionLedger", "captionStyles", "captionChapters", "dialogueCaptionAuthority")):
        raise RuntimeError("presenter profile has unqualified alternate caption authority")
    cuts = plan.get("cutTrack")
    if type(cuts) is not list or not cuts or any(type(row) is not dict or type(row.get("speed", 1)) not in (int, float)
            or row.get("speed", 1) != 1 or type(row.get("audioLeadMs", 0)) not in (int, float)
            or row.get("audioLeadMs", 0) != 0 for row in cuts):
        raise RuntimeError("presenter profile requires unchanged speed-one cuts without J-cut leads")
    captioned = "captionsTrack" in plan
    if captioned:
        caption_preset_plan(plan)
    elif type(plan.get("captions")) is not dict or set(plan["captions"]) != {"burn"} \
            or plan["captions"]["burn"] is not False:
        raise RuntimeError("uncaptioned presenter requires explicit captions.burn=false")
    if short:
        manual_short_geometry(plan, captioned)
        return PRESENTER_CAPTION_SHORT_PROFILE if captioned else PRESENTER_SHORT_PROFILE
    if plan.get("reframe") not in (None, {}, {"strategy": "none"}):
        raise RuntimeError("longform presenter has unqualified reframe intent")
    return PRESENTER_CAPTION_PROFILE if captioned else PRESENTER_PROFILE


def presenter_graph_workload(clock: PrefixClock, graphic_count: int, captioned: bool,
                             asset_canvases: tuple[tuple[int, int], ...]) -> dict:
    """Count every prospective native input occurrence, not only unique file paths."""
    if type(clock) is not PrefixClock or not valid_canvas(clock.width, clock.height) \
            or type(graphic_count) is not int or not 0 <= graphic_count <= 128 or type(captioned) is not bool:
        raise RuntimeError("presenter graph workload metadata is malformed")
    canonical_presenter_rate(clock.frame_rate)
    PresenterCanvas(clock.width, clock.height, clock.total_frames, "yuv420p")
    if type(asset_canvases) is not tuple or not 1 <= len(asset_canvases) <= 32 or any(
            type(row) is not tuple or len(row) != 2 or not valid_canvas(*row) for row in asset_canvases):
        raise RuntimeError("presenter graph needs1–32 bounded asset-canvas occurrences")
    pages = caption_page_bound(clock, (graphic_count, graphic_count), clock.total_frames)["fullPageBound"] if captioned else 0
    count = graphic_count + pages + len(asset_canvases)
    pixels = (1 + graphic_count + pages) * clock.width * clock.height + sum(width * height for width, height in asset_canvases)
    if count > MAX_CLIPS or pixels > GRAPH_WORKLOAD_POLICY["maxGraphInputPixels"]:
        raise RuntimeError("presenter combined graph exceeds existing workload; no requested inputs may be dropped")
    return {"kind": "presenter-combined-workload-preflight", "scope": "metadata-not-observed-media-or-RSS-proof",
        "graphicCount": graphic_count, "captionPageBound": pages, "presenterOccurrences": len(asset_canvases),
        "fullGraphInputPixels": pixels, "productionPerformanceQualified": False}


def _span(row: dict, total: int) -> tuple[int, int]:
    """Use exact half-open frames, including the full authored ramp endpoints."""
    if type(row) is not dict:
        raise RuntimeError("presenter coexistence row is malformed")
    start, end = row.get("startFrame"), row.get("endFrameExclusive")
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= total:
        raise RuntimeError("presenter coexistence requires bounded original frame windows")
    return start, end


def assert_presenter_graphics_disjoint(graphics: list[dict], windows: list[dict], total: int) -> None:
    """An opaque own-screen graphic cannot cover an explicitly requested presenter."""
    if type(total) is not int or total <= 0 or type(graphics) is not list or len(graphics) > 128 \
            or type(windows) is not list or not 1 <= len(windows) <= 32:
        raise RuntimeError("presenter coexistence requires the bounded whole-candidate inventory")
    graphic_spans = [_span(row, total) for row in graphics]
    presenter_spans = [_span(row, total) for row in windows]
    if any(max(a, c) < min(b, d) for a, b in graphic_spans for c, d in presenter_spans):
        raise RuntimeError("own-screen graphic overlaps requested presenter; no automatic retiming or suppression")
