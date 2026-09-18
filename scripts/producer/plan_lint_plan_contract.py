"""Plan-level identity, target, caption, music, and reframe lint checks."""
from __future__ import annotations

from typing import Protocol

from plan_lint_audio import check_music_source
from plan_lint_motion import check_word_lock
from plan_lint_reframe import check_reframe
from plan_lint_visual import check_form_shape
from graphics.intro_semantic_contract import check_intro_graphics
from graphics.style_profile_contract import check_style_profile
from planner.advanced_motion_gate import reject_unreleased_advanced_motion
from producer_config import CAPTION_STYLES, MODES, PLATFORMS


class FindingSink(Protocol):
    """Minimal finding interface shared with ``plan_lint.Report``."""

    def error(self, msg: str) -> None:
        """Record a blocking finding."""

    def warn(self, msg: str) -> None:
        """Record a non-blocking finding."""


def check_graphic_ids(plan: dict, rep: FindingSink) -> None:
    """Require every optional editor-stamped graphic id to be unique."""
    seen: set[str] = set()
    for index, graphic in enumerate(plan.get("graphicsTrack") or []):
        graphic_id = graphic.get("id")
        if graphic_id is None:
            continue
        if not isinstance(graphic_id, str) or not graphic_id:
            rep.error(
                f"graphicsTrack[{index}]: id must be a non-empty string "
                f"(got {graphic_id!r})")
            continue
        if graphic_id in seen:
            rep.error(
                f"graphicsTrack[{index}]: duplicate graphic id {graphic_id!r}")
        seen.add(graphic_id)


def check_target(plan: dict, rep: FindingSink) -> dict | None:
    """Validate plan target and return its canonical mode preset."""
    target = plan.get("target") or {}
    mode = target.get("mode")
    if mode not in MODES:
        rep.error(
            f"target.mode must be one of {sorted(MODES)} (got {mode!r})")
        return None
    for platform in target.get("platforms") or []:
        if platform not in PLATFORMS:
            rep.error(
                f"unknown platform {platform!r} (allowed: {PLATFORMS})")
    version = plan.get("planVersion")
    if not isinstance(version, int) or version < 1:
        rep.error("planVersion must be an integer >= 1")
    return MODES[mode]


def _legacy_chapter_order(chapters: object, rep: FindingSink) -> None:
    try:
        starts = [float(row.get("outStart", -1)) for row in chapters]  # type: ignore[union-attr]
    except (TypeError, ValueError, AttributeError):
        rep.error("chapters must contain output-time chapter objects")
        return
    if starts != sorted(starts) or (starts and starts[0] < 0):
        rep.error("chapters must have ascending non-negative outStart")


def _semantic_chapters(
    plan: dict, explicit: bool, mode: object, rep: FindingSink,
) -> None:
    semantic = plan.get("captionChapters")
    if semantic is None:
        return
    if not explicit:
        rep.error("captionChapters require CaptionTrackV1")
    if mode != "longform":
        rep.error("captionChapters are longform-only")
    from captions.caption_outputs import validate_chapter_anchors
    try:
        validate_chapter_anchors(semantic)
    except ValueError as exc:
        rep.error(f"captionChapters: {exc}")


def _check_chapters(plan: dict, explicit: bool, rep: FindingSink) -> None:
    mode = (plan.get("target") or {}).get("mode")
    chapters = plan.get("chapters")
    if chapters and explicit:
        rep.error(
            "CaptionTrackV1 uses semantic captionChapters, not legacy chapters")
    elif chapters and mode != "longform":
        rep.error("chapters are longform-only")
    if chapters and not explicit:
        _legacy_chapter_order(chapters, rep)
    _semantic_chapters(plan, explicit, mode, rep)


def _report_orphan_caption_fields(
    plan: dict, fields: tuple[str, ...], rep: FindingSink,
) -> None:
    if any(field in plan for field in fields):
        rep.error("caption sidecar authority requires CaptionTrackV1")


def _caption_authority(
    plan: dict, preset: dict, rep: FindingSink,
) -> tuple[dict, dict] | None:
    from captions.caption_plan_pipeline import (
        CHAPTERS_FIELD,
        LEDGER_FIELD,
        STYLES_FIELD,
        caption_styles,
        validate_plan_caption_authority,
    )
    try:
        authority = validate_plan_caption_authority(plan)
        if authority is None:
            _report_orphan_caption_fields(
                plan, (LEDGER_FIELD, STYLES_FIELD, CHAPTERS_FIELD), rep)
            return None
        caption_styles(plan, authority[0])
    except ValueError as exc:
        rep.error(f"CaptionTrackV1: {exc}")
        return None
    burn = (plan.get("captions") or {}).get(
        "burn", preset["captions_burn"])
    if burn is True and authority[0]["defaultPolicy"] == "off" \
            and not authority[0]["groups"]:
        rep.error("captions.burn is on but CaptionTrackV1 selects no words")
    return authority


def check_caption_plan(
    plan: dict, preset: dict, rep: FindingSink,
) -> None:
    """Validate legacy settings and first-class caption authority together."""
    style = (plan.get("captions") or {}).get(
        "style", preset["captions_style"])
    if style not in CAPTION_STYLES:
        rep.error(f"captions.style {style!r} not in {CAPTION_STYLES}")
    offset = (plan.get("captions") or {}).get("bandYOffsetPx", 0)
    if not isinstance(offset, (int, float)) or not (0 <= offset <= 400):
        rep.error("captions.bandYOffsetPx must be a number in [0, 400]")
    authority = _caption_authority(plan, preset, rep)
    _check_chapters(plan, authority is not None, rep)


def check_music_and_misc(
    plan: dict, manifest: dict, preset: dict, rep: FindingSink,
) -> None:
    """Check music asset/variants, reframe, motion gate, and captions."""
    music = plan.get("music") or {}
    if music.get("enabled"):
        variants = music.get("variants")
        if variants is not None and (
                not set(variants)
                or not set(variants) <= {"with", "without"}):
            rep.error(
                "music.variants must be a non-empty subset of "
                "['with','without']")
        check_music_source(music, manifest, rep)
    check_reframe(plan, preset, rep)
    reject_unreleased_advanced_motion(plan, rep)
    check_caption_plan(plan, preset, rep)


def check_transcript_contracts(
    plan: dict, out_duration: float, words: list | None, rep: FindingSink,
) -> None:
    """Apply style and transcript-derived semantic checks in one lane."""
    check_style_profile(plan, out_duration, rep, words)
    if words is None:
        return
    check_word_lock(plan, words, rep)
    check_form_shape(plan, words, rep)
    check_intro_graphics(plan, words, out_duration, rep)
