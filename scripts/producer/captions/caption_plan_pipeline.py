#!/usr/bin/env python3
"""Bridge strict CaptionTrackV1 authority into the current plan renderer."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from fractions import Fraction

from captions.caption_compile import CaptionCompileContext, compile_caption_track
from captions.caption_contract import (
    CaptionContractError,
    validate_caption_track,
    validate_correction_ledger,
)
from captions.caption_fingerprints import canonical_digest
from captions.caption_operations import new_correction_ledger
from captions.caption_outputs import compile_chapters
from captions.caption_words import (
    CaptionFrameRate,
    CaptionWordClock,
    merge_resolved_words,
    resolve_kept_word_occurrences,
)
from compile_timeline import TimelineMap
from producer_config import (CANVAS_BY_ASPECT, CAPTION_LAYOUT_BY_ASPECT,
                             CAPTIONS, MODES, SAFE_BOX)

TRACK_FIELD = "captionsTrack"
LEDGER_FIELD = "captionCorrectionLedger"
STYLES_FIELD = "captionStyles"
CHAPTERS_FIELD = "captionChapters"
PROJECTION_TOOLCHAIN = {"projection": "ass-v1"}
_STYLE_KEYS = {
    "font", "size", "fill", "activeFill", "outline", "outlinePx",
    "maxCharsPerLine",
}
_COLOR = re.compile(
    r"^(?:#[0-9A-Fa-f]{6}|white|black|yellow|red)$")


@dataclass(frozen=True)
class PlanCaptionContext:
    """Immutable inputs for compiling one plan's explicit caption authority."""

    plan: dict
    manifest: dict
    timeline: TimelineMap
    rate: CaptionFrameRate
    manifest_dir: str
    sample_rate: int = 48_000
    total_frames: int | None = None


def has_explicit_caption_track(plan: object) -> bool:
    """Whether the plan selects the strict first-class caption path."""
    return isinstance(plan, dict) and isinstance(plan.get(TRACK_FIELD), dict)


def validate_plan_caption_authority(plan: object) -> tuple[dict, dict] | None:
    """Validate explicit authority; reject ghost/legacy track payloads."""
    if not isinstance(plan, dict) or TRACK_FIELD not in plan:
        return None
    track = plan.get(TRACK_FIELD)
    if track is None or track == []:
        return None
    if not isinstance(track, dict):
        raise CaptionContractError(
            "captionsTrack must be CaptionTrackV1, not a timed text array")
    normalized = validate_caption_track(track)
    raw_ledger = plan.get(LEDGER_FIELD, new_correction_ledger())
    return normalized, validate_correction_ledger(raw_ledger)


def _style_seed(style_id: str) -> dict:
    base = CAPTIONS["style"]
    result = {
        "font": CAPTIONS["font"], "size": CAPTIONS["font_size"],
        "fill": base["fill"], "activeFill": base["karaoke_highlight"],
        "outline": base["outline"], "outlinePx": base["outline_px"],
        "maxCharsPerLine": CAPTIONS["max_chars_per_line"],
    }
    if style_id == "line":
        result["activeFill"] = result["fill"]
    return result


def _normalized_style(style_id: str, supplied: dict | None) -> dict:
    value = {**_style_seed(style_id), **(supplied or {})}
    unknown = set(value) - _STYLE_KEYS
    if unknown:
        raise CaptionContractError(
            f"caption style {style_id!r} has unknown fields: "
            + ", ".join(sorted(unknown)))
    font = value["font"]
    if not isinstance(font, str) or not font.strip() \
            or len(font) > 128 or "," in font:
        raise CaptionContractError(f"caption style {style_id!r} has invalid font")
    for field in ("fill", "activeFill", "outline"):
        color = value[field]
        if not isinstance(color, str) or not _COLOR.fullmatch(color):
            raise CaptionContractError(
                f"caption style {style_id!r} has invalid {field}")
    for field in ("size", "outlinePx", "maxCharsPerLine"):
        number = value[field]
        minimum = 0 if field == "outlinePx" else 1
        if isinstance(number, bool) or not isinstance(number, int) \
                or number < minimum:
            raise CaptionContractError(
                f"caption style {style_id!r} has invalid {field}")
    return value


def caption_styles(plan: dict, track: dict) -> dict[str, dict]:
    """Resolve immutable style inputs for every selected style identifier."""
    catalog = {"default": None, "karaoke": None, "line": None}
    required = {row["styleId"] for row in track["groups"]}
    if track["defaultPolicy"] != "off":
        required.add("default")
    supplied = plan.get(STYLES_FIELD)
    if supplied is not None:
        if not isinstance(supplied, dict) or any(
                not isinstance(key, str) or not isinstance(value, dict)
                for key, value in supplied.items()):
            raise CaptionContractError(
                "captionStyles must map style ids to immutable objects")
        unused = sorted(set(supplied) - required)
        if unused:
            raise CaptionContractError(
                f"captionStyles contains unused styles: {', '.join(unused)}")
        catalog.update(supplied)
    missing = sorted(required - set(catalog))
    if missing:
        raise CaptionContractError(
            f"caption style inputs are missing: {', '.join(missing)}")
    return {
        key: _normalized_style(key, catalog.get(key))
        for key in sorted(required)
    }


def _read_transcript(path: str) -> list[dict]:
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise CaptionContractError(
            f"cannot read caption transcript {path}: {exc}") from exc
    if isinstance(value, list):
        return value
    if not isinstance(value, dict) or not isinstance(value.get("transcript"), list):
        raise CaptionContractError(
            f"caption transcript {path} has no transcript list")
    result: list[dict] = []
    for utterance in value["transcript"]:
        if not isinstance(utterance, dict) \
                or not isinstance(utterance.get("words"), list):
            raise CaptionContractError(
                f"caption transcript {path} has malformed utterances")
        result.extend(utterance["words"])
    return result


def _source_words(context: PlanCaptionContext, source: dict) -> list[dict]:
    relative = source.get("transcriptPath")
    if not isinstance(relative, str) or not relative:
        return []
    path = relative if os.path.isabs(relative) \
        else os.path.join(context.manifest_dir, relative)
    words = _read_transcript(path)
    return resolve_kept_word_occurrences(
        str(source["id"]), words, context.timeline,
        CaptionWordClock(context.rate, context.sample_rate))


def resolved_plan_words(context: PlanCaptionContext) -> list[dict]:
    """Resolve all kept transcript occurrences onto exact delivery frames."""
    rows = [
        _source_words(context, source)
        for source in context.manifest.get("sources", [])
        if isinstance(source, dict)
    ]
    words = merge_resolved_words(rows)
    return _clamp_delivery_tail(words, context)


def _clamp_delivery_tail(
        words: list[dict], context: PlanCaptionContext) -> list[dict]:
    """Clamp only an encoder-rounded tail to the sealed picture boundary."""
    total = context.total_frames
    if total is None:
        return words
    if isinstance(total, bool) or not isinstance(total, int) or total <= 0:
        raise CaptionContractError(
            "caption delivery frame authority must be positive")
    sample_end = (
        total * context.sample_rate * context.rate.denominator
        // context.rate.numerator)
    result = []
    for index, row in enumerate(words):
        if row["startFrame"] >= total:
            raise CaptionContractError(
                f"resolved caption word {index} starts beyond delivery")
        current = dict(row)
        if current["endFrameExclusive"] > total:
            current["endFrameExclusive"] = total
            if "endSampleExclusive" in current:
                current["endSampleExclusive"] = min(
                    current["endSampleExclusive"], sample_end)
                if current["endSampleExclusive"] <= current["startSample"]:
                    raise CaptionContractError(
                        "caption tail clamp leaves no exact samples")
        result.append(current)
    return merge_resolved_words([result])


def _frame(value: object, rate: Fraction, ceiling: bool) -> int:
    seconds = Fraction(str(float(value)))
    frames = seconds * rate
    return (-(-frames.numerator // frames.denominator) if ceiling
            else frames.numerator // frames.denominator)


def _scene_window(entry: object, rate: CaptionFrameRate) -> dict | None:
    if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
        return None
    try:
        start = _frame(entry["outStart"], rate.fraction, False)
        end = _frame(entry["outEnd"], rate.fraction, True)
    except (KeyError, TypeError, ValueError):
        return None
    if end <= start:
        return None
    return {
        "sceneId": entry["id"], "startFrame": max(0, start),
        "endFrameExclusive": end,
    }


def _scene_windows(plan: dict, rate: CaptionFrameRate) -> list[dict]:
    candidates = [
        _scene_window(entry, rate)
        for key in ("graphicsTrack", "titleCards")
        for entry in plan.get(key) or []
    ]
    return [row for row in candidates if row is not None]


def _destination(plan: dict) -> dict:
    """Keep portrait exact; use the existing layout's insets on other aspects."""
    mode = (plan.get("target") or {}).get("mode")
    if mode not in MODES:
        raise CaptionContractError("caption plan target mode is unsupported")
    aspect = MODES[mode]["aspect"]
    canvas = CANVAS_BY_ASPECT[aspect]
    safe_zones = dict(SAFE_BOX)
    if aspect != "9:16":
        layout = CAPTION_LAYOUT_BY_ASPECT[aspect]
        safe_zones = {
            "top": round(SAFE_BOX["top"] * canvas["height"] / CANVAS_BY_ASPECT["9:16"]["height"]),
            "bottom": canvas["height"] - layout["baseline_max_y"],
            "left": layout["margin_l"], "right": layout["margin_r"],
        }
    return {
        "profileId": f"{mode}-{aspect.replace(':', 'x')}",
        "width": canvas["width"], "height": canvas["height"],
        "safeZones": safe_zones,
    }


def _map_slices(words: list[dict], timeline: TimelineMap) -> dict[str, str]:
    segments = [segment.__dict__ for segment in timeline.segments]
    result = {}
    for word in words:
        owner = word.get("cutSegmentIndex")
        relevant = ([row for row in segments if row["index"] == owner]
                    if type(owner) is int else [
                        row for row in segments
                        if row["source_id"] == word["sourceId"]
                        and row["src_start"] <= word["sourceStart"]
                        <= row["src_end"]
                    ])
        result[word["wordId"]] = canonical_digest(
            "sniper-caption-map-slice-v1", {
                "word": word, "segments": relevant,
            })
    return result


def plan_dialogue_compile_context(
    plan: dict,
    rate: CaptionFrameRate,
    timeline_map_hash: str,
    sample_rate: int,
) -> CaptionCompileContext:
    """Build immutable plan inputs while dialogue authority owns word timing."""
    authority = validate_plan_caption_authority(plan)
    if authority is None:
        raise CaptionContractError(
            "dialogue caption compilation requires CaptionTrackV1")
    if plan.get("chapters"):
        raise CaptionContractError(
            "CaptionTrackV1 requires semantic captionChapters")
    track, ledger = authority
    return CaptionCompileContext(
        track=track, ledger=ledger, words=[], rate=rate,
        timeline_map_hash=timeline_map_hash,
        style_inputs=caption_styles(plan, track),
        destination=_destination(plan),
        scene_windows=_scene_windows(plan, rate),
        sample_rate=sample_rate, toolchain=PROJECTION_TOOLCHAIN,
    )


def compile_plan_caption_track(context: PlanCaptionContext) -> dict | None:
    """Compile the explicit track, or return None for an untouched legacy plan."""
    authority = validate_plan_caption_authority(context.plan)
    if authority is None:
        return None
    if context.plan.get("chapters"):
        raise CaptionContractError(
            "CaptionTrackV1 requires semantic captionChapters; legacy "
            "output-time chapters would be silently stale")
    track, ledger = authority
    words = resolved_plan_words(context)
    styles = caption_styles(context.plan, track)
    timeline_hash = canonical_digest(
        "sniper-caption-timeline-map-v1", context.timeline.to_dict())
    compilation = compile_caption_track(CaptionCompileContext(
        track=track, ledger=ledger, words=words, rate=context.rate,
        timeline_map_hash=timeline_hash,
        timeline_slices=_map_slices(words, context.timeline),
        style_inputs=styles, destination=_destination(context.plan),
        scene_windows=_scene_windows(context.plan, context.rate),
        segment_versions={}, toolchain=PROJECTION_TOOLCHAIN,
        sample_rate=context.sample_rate,
    ))
    if CHAPTERS_FIELD in context.plan:
        compilation["chapterProjection"] = compile_chapters(
            context.plan[CHAPTERS_FIELD], words, context.rate)
    return compilation
