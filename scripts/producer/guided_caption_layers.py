"""Exact original caption-page layers, never caption or renderer authority.

Only the execution owner supplies a strongly read actual projection. No page
is resized, re-timed, regenerated or suppressed here. Both prefix graphs keep
the original full-program page origin and append pages AFTER their graphics.
"""
from __future__ import annotations

from dataclasses import replace
from fractions import Fraction
from pathlib import Path

from captions.caption_pages import MAX_PAGE_SECONDS
from graphics.composite_core import validate_caption_tails, ordered_clips
from cut_preview_io import digest
from guided_caption_projection import HeldCaptionProjection
from opening_prefix_contract import (CompositorPrefixRequest, GRAPH_WORKLOAD_POLICY,
                                     HeldPrefixInput, MAX_CLIPS, PrefixClock)
from opening_prefix_presenter import presenter_input_pixels, validate_presenter_request


def caption_page_bound(clock: PrefixClock, graphics: tuple[int, int], review_end: int) -> dict:
    """Conservative full-program admission BEFORE ordinary caption materialization."""
    rate = Fraction(clock.frame_rate)
    if rate <= 0 or type(clock.total_frames) is not int or clock.total_frames <= 0 \
            or type(review_end) is not int or not 0 < review_end <= clock.total_frames \
            or any(type(value) is not int or value < 0 for value in graphics):
        raise RuntimeError("caption workload lacks an exact positive clock/count")
    page_frames = max(1, int(rate * MAX_PAGE_SECONDS))
    pages = tuple((frames + page_frames - 1) // page_frames for frames in (clock.total_frames, review_end))
    counts = tuple(graphic + page for graphic, page in zip(graphics, pages))
    costs = _surface_costs(clock, counts)
    return {"kind": "held-caption-page-workload-preflight", "scope": "conservative-not-rendered-proof",
        "maxPageFrames": page_frames, "fullPageBound": pages[0], "openingPageBound": pages[1], **costs}


def _surface_costs(clock: PrefixClock, counts: tuple[int, int]) -> dict:
    """Count each native decoder occurrence; repeated assets are not free inputs."""
    pixels = clock.width * clock.height
    costs = tuple((count + 1) * pixels for count in counts)
    if any(count > MAX_CLIPS for count in counts) \
            or any(cost > GRAPH_WORKLOAD_POLICY["maxGraphInputPixels"] for cost in costs):
        raise RuntimeError(f"caption combined graph exceeds existing workload: {counts} overlays at "
                           f"{clock.width}x{clock.height}; no inputs may be dropped")
    return {"fullGraphInputPixels": costs[0], "openingGraphInputPixels": costs[1]}


def caption_page_clips(held: HeldCaptionProjection, end: int | None = None) -> tuple[dict, ...]:
    """Project exact held pages without restarting a page at the opening boundary."""
    rate, total, _width, _height = held.binding.frame_clock
    limit = total if end is None else end
    if type(limit) is not int or not 0 < limit <= total:
        raise RuntimeError("caption graph selection exceeds original full-frame authority")
    fps = Fraction(rate)
    result = []
    for row in held.data["pages"]["entries"]:
        start, stop = row["startFrame"], row["endFrameExclusive"]
        if start >= limit:
            continue
        result.append({"path": str(Path(held.root) / row["media"]["name"]),
            "outStart": float(Fraction(start, 1) / fps), "outEnd": float(Fraction(stop, 1) / fps),
            "anchor": "own-screen", "x": 0, "y": 0, "startFrame": start, "endFrameExclusive": stop,
            "compositionRole": "caption-page", "captionPageId": row["pageId"]})
    return tuple(result)


def opening_caption_layers(clips: list[dict], held: HeldCaptionProjection, review_end: int) -> tuple[list[dict], dict]:
    """Bind the combined opening graph, actual page identities and original phase."""
    pages = caption_page_clips(held, review_end)
    combined = [*clips, *pages]
    ordered_clips(combined, len(pages))
    return combined, {"kind": "graphics-then-held-caption-pages-v1", "captionTail": len(pages),
        "projectionHash": held.data_hash, "combinedGraphHash": digest(combined),
        "pageIds": [row["captionPageId"] for row in pages]}


def caption_prefix_request(request: CompositorPrefixRequest, held: HeldCaptionProjection) -> CompositorPrefixRequest:
    """Extend a separately authenticated graphics request with SAME held pages."""
    clock = request.clock
    if held.binding.frame_clock != (clock.frame_rate, clock.total_frames, clock.width, clock.height) \
            or request.caption_tail is not None:
        raise RuntimeError("caption prefix clock differs or graph already has a caption tail")
    full = caption_page_clips(held)
    opening = caption_page_clips(held, request.ranges.review[1])
    counts = len(full), len(opening)
    graphs = (*request.full_clips, *full), (*request.opening_clips, *opening)
    validate_caption_tails(graphs, counts)
    costs = _surface_costs(clock, (len(graphs[0]), len(graphs[1])))
    presentation = presenter_input_pixels(request)
    if max(costs["fullGraphInputPixels"] + presentation[0],
           costs["openingGraphInputPixels"] + presentation[1]) > GRAPH_WORKLOAD_POLICY["maxGraphInputPixels"]:
        raise RuntimeError("caption/presenter combined graph exceeds existing input-pixel workload")
    inventory = {row.path: row for row in held.files}
    assets = list(request.assets)
    known = {row.path for row in assets} | {request.base.path}
    for clip in full:
        row = inventory[clip["path"]]
        if row.path in known:
            raise RuntimeError("caption page aliases the held base or graphic inventory")
        known.add(row.path)
        assets.append(HeldPrefixInput(row.path, row.sha256, row.size_bytes))
    result = replace(request, assets=tuple(assets), full_clips=graphs[0], opening_clips=graphs[1], caption_tail=counts)
    validate_presenter_request(result)
    return result
