"""Cold whole-body caption clearance beneath actual stopped-worker read authority.

One strong original caption read supplies both original-opening and whole-body
reports. Neither report recreates a live owner or decodes media. The caller
still authenticates the actual result, graphic artifacts, retained picture,
full A/V observations, current project lease and original remaining budget.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from guided_caption_layers import caption_page_clips
from guided_caption_projection import HeldCaptionProjection
from guided_opening_inputs import closed
from guided_presenter_body_read import PresenterBodyReadContext, _exact, verify_presenter_body_prefix
from guided_presenter_caption_picture import presenter_caption_picture_record
from guided_presenter_caption_read import (
    _binding, _caption_layers, _context, _cues, _guard, _report, _types_match,
)
from guided_presenter_capture_inputs import capture_selection
from guided_presenter_profile import presenter_caption_profile
from guided_presenter_read import PresenterReadContext
from guided_presenter_read_fingerprint import hold_read_metadata, same_read_metadata
from opening_prefix_contract import CompositorPrefixRequest, canonical_hash


def _caller_guard(context: PresenterBodyReadContext, request: CompositorPrefixRequest,
                  held: HeldCaptionProjection, composition: dict) -> Callable[[], None]:
    """Retain the same request, original opening, files and caller through both reports."""
    read = context.read
    caller = lambda: (request, context.opening_pictures, context.tools)
    original = hold_read_metadata(caller())
    caption_check = _guard(read, held, [composition, context.opening_pictures])

    def check() -> None:
        """Every original callback keeps full metadata, not just an earlier report hash."""
        caption_check()
        if context.read is not read or not same_read_metadata(caller(), original):
            raise RuntimeError("presenter body caption original request or context changed")

    return check


def _match_record(actual: object, expected: dict, label: str) -> None:
    """Compare exact closed derived fields while preserving receipt numeric conventions."""
    row = closed(actual, set(expected), label)
    if not _types_match(row, expected) or canonical_hash(row) != canonical_hash(expected):
        raise RuntimeError(label + " differs from independently reconstructed clearance")


def _full_pages(request: CompositorPrefixRequest, held: HeldCaptionProjection) -> tuple[dict, ...]:
    """Require the original entire page tail, including pages outside the opening."""
    pages = caption_page_clips(held)
    opening = caption_page_clips(held, request.ranges.review[1])
    counts = len(pages), len(opening)
    if type(request.caption_tail) is not tuple or len(request.caption_tail) != 2 \
            or any(type(value) is not int for value in request.caption_tail) or request.caption_tail != counts:
        raise RuntimeError("presenter body caption tail differs from its complete original pages")
    tail = request.full_clips[-len(pages):] if pages else ()
    if not _exact(list(tail), list(pages)):
        raise RuntimeError("presenter body caption graph omits or changes an original full page")
    return pages


def _original_proof(composition: dict) -> dict:
    """Remove only known body-owner fields from the actual original compositor proof."""
    from guided_presenter_caption_body_record import ORIGINAL_PROOF_FIELDS

    additions = {"originalGraphDerivation", "retainedPicture", "presenterCaptionClearance"}
    closed(composition, set(ORIGINAL_PROOF_FIELDS) | additions, "captioned presenter body composition")
    return {key: composition[key] for key in ORIGINAL_PROOF_FIELDS}


def _reports(composition: dict, request: CompositorPrefixRequest,
             context: PresenterBodyReadContext, held: HeldCaptionProjection) -> None:
    """Reconstruct both report coverages from one whole-cue original byte read."""
    from guided_presenter_caption_body_record import body_presenter_caption_picture_record

    check = _caller_guard(context, request, held, composition)
    check()
    current = replace(context, read=replace(context.read, guard=check))
    old, evidence = verify_presenter_body_prefix(composition, request, current)
    clock, opening = _context(current.read, held)
    selection = capture_selection(current.read.inputs)
    if selection is None or not selection.selected:
        raise RuntimeError("presenter body caption read has no original selected windows")
    cues = _cues(opening, selection, clock, check)
    pages = _full_pages(request, held)
    _caption_layers(context.opening_pictures, (request.opening_clips, request.caption_tail[1]), opening)
    first = _report(_binding(opening, clock, old, cues), selection, cues, check)
    _match_record(context.opening_pictures.get("presenterCaptionClearance"),
        presenter_caption_picture_record(first, context.opening_pictures), "original opening presenter caption binding")
    full = replace(opening, coverage={"startFrame": 0, "endFrameExclusive": clock["totalFrames"]}, owner_phase="body")
    report = _report(_binding(full, clock, evidence, cues), selection, cues, check)
    expected = body_presenter_caption_picture_record(report, _original_proof(composition),
                                                     composition["retainedPicture"], pages)
    _match_record(composition.get("presenterCaptionClearance"), expected, "body presenter caption binding")
    check()


def verify_presenter_body_picture(composition: dict, request: CompositorPrefixRequest,
                                  context: PresenterBodyReadContext, captions: HeldCaptionProjection | None) -> None:
    """Read schema2 graph/pictures plus mandatory new-class full caption evidence."""
    if type(composition) is not dict or type(context) is not PresenterBodyReadContext \
            or type(context.read) is not PresenterReadContext \
            or type(request) is not CompositorPrefixRequest or request.presenter is not None:
        raise RuntimeError("presenter body picture reader requires original data-only context")
    if not presenter_caption_profile(context.read.inputs.value.get("profile")):
        if captions is not None or "presenterCaptionClearance" in composition:
            raise RuntimeError("uncaptioned presenter body acquired unsupported caption clearance")
        verify_presenter_body_prefix(composition, request, context)
        return
    if type(captions) is not HeldCaptionProjection:
        raise RuntimeError("presenter body caption read lacks its actual original held captions")
    _reports(composition, request, context, captions)
