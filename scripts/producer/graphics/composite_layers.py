"""Exact ordered-layer policies shared by the compositor and prefix verifier."""
from __future__ import annotations


def frame_window(clip: dict) -> tuple[int, int]:
    """Require controller-derived half-open frames; never infer float seconds."""
    start, end = clip.get("startFrame"), clip.get("endFrameExclusive")
    if type(start) is not int or type(end) is not int or not 0 <= start < end:
        raise ValueError("exact-frame compositor clip lacks its bounded frame window")
    return start, end


def ordered_clips(clips: list[dict], caption_tail: int | None = None) -> list[dict]:
    """Preserve legacy sort, or append a strictly declared native caption tail."""
    if caption_tail is None:
        if any("compositionRole" in row for row in clips):
            raise ValueError("caption page roles require the explicit caption-tail policy")
        return sorted(clips, key=lambda clip: float(clip["outStart"]))
    if type(caption_tail) is not int or not 0 <= caption_tail <= len(clips):
        raise ValueError("caption tail count is malformed")
    boundary = len(clips) - caption_tail
    graphics, pages = clips[:boundary], clips[boundary:]
    keys = {"path", "outStart", "outEnd", "anchor", "x", "y", "startFrame", "endFrameExclusive",
            "compositionRole", "captionPageId"}
    if any("compositionRole" in row for row in graphics):
        raise ValueError("caption page appeared among ordinary graphics")
    for page in pages:
        if set(page) != keys or page["compositionRole"] != "caption-page" \
                or page["anchor"] != "own-screen" or page["x"] != 0 or page["y"] != 0 \
                or type(page["captionPageId"]) is not str or len(page["captionPageId"]) != 64 \
                or any(char not in "0123456789abcdef" for char in page["captionPageId"]):
            raise ValueError("caption page has unqualified layout or identity")
        frame_window(page)
    if any(first["endFrameExclusive"] > second["startFrame"] for first, second in zip(pages, pages[1:])):
        raise ValueError("caption pages overlap or changed original timeline order")
    return sorted(graphics, key=lambda clip: float(clip["outStart"])) + pages


def validate_caption_tails(graphs: tuple[tuple, tuple], counts: tuple[int, int] | None) -> None:
    """Validate both explicit graph boundaries before any probing or rendering."""
    if counts is not None and (type(counts) is not tuple or len(counts) != 2
            or any(type(value) is not int or value < 0 for value in counts) or counts[0] == 0):
        raise ValueError("prefix caption-tail policy/counts are malformed")
    for index, graph in enumerate(graphs):
        ordered_clips(list(graph), counts[index] if counts is not None else None)


def caption_layer_policy(counts: tuple[int, int] | None) -> dict:
    """Omit metadata for old commands; bind explicit current layer boundaries."""
    if counts is None:
        return {}
    return {"layerPolicy": {"kind": "graphics-then-held-caption-pages-v1",
        "fullCaptionTail": counts[0], "openingCaptionTail": counts[1]}}
