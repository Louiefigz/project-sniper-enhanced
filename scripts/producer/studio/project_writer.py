"""Build the Studio review project's entry composition and sidecar files.

``index.html`` is the review timeline: the graphics-free base footage plays
as a DIRECT child of the root on track 0 (a wrapped ``<video>`` renders
blank — vendored ``variables-and-media.md``), with every graphicsTrack entry
mounted as a timed sub-composition slot above it. The project is a VIEW for
``hyperframes preview`` only; it is never rendered.
"""
from __future__ import annotations

import html
import json
from dataclasses import dataclass

from fingerprints import json_canon
from studio.comp_transform import attr_json

REVIEW_COMP_ID = "review"

_HYPERFRAMES_JSON = {
    "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
    "paths": {"blocks": "compositions",
              "components": "compositions/components",
              "assets": "assets"},
}


@dataclass(frozen=True)
class ReviewBase:
    """The base footage as it appears on track 0."""

    width: int
    height: int
    duration: float
    fps: float | None
    src_rel: str
    has_audio: bool


@dataclass(frozen=True)
class ReviewClip:
    """One graphicsTrack entry as a timed sub-composition slot."""

    slot_id: str
    instance_id: str
    kind: str
    file_rel: str
    spec: dict
    out_start: float
    out_end: float
    authored_out_end: float
    track: int
    z_index: int
    width: int
    height: int
    anchor: str
    reason: str
    plan_id: str | None
    non_panel_keys: tuple[str, ...]


def sec(value: float) -> str:
    """Deterministic seconds formatting (≤4 decimals, no trailing zeros)."""
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def readback_window(out_start: float, out_end: float) -> tuple[float, float]:
    """The slot window exactly as the review view reads it back (BUG-1).

    ``_slot_element`` writes ``data-start=sec(outStart)`` and
    ``data-duration=sec(outEnd - outStart)`` as INDEPENDENT 4-decimal
    projections; readers recover ``end = start + duration``. Timing
    baselines recorded anywhere (generation manifest, rebaseline) must be
    this projection — comparing the read-back against the raw plan floats
    false-diffs every >4-decimal authored timing.
    """
    start = float(sec(out_start))
    return round(start, 4), round(start + float(sec(out_end - out_start)), 4)


def _values_attr(spec: dict) -> str:
    """The slot's ``data-variable-values`` JSON, canonical and raw-parseable
    (Studio lint JSON.parses the attribute text straight from the file)."""
    return attr_json(json_canon(spec))


def _media_elements(base: ReviewBase) -> list[str]:
    """Emit the existing direct base-video and optional audio review elements."""
    duration = sec(base.duration)
    lines = [
        '    <video id="review-base" class="clip" data-hf-id="hf-review-base"'
        f' src="{base.src_rel}" muted playsinline'
        f' data-start="0" data-duration="{duration}" data-track-index="0"'
        ' style="position: absolute; inset: 0; width: 100%; height: 100%;'
        ' object-fit: cover; z-index: 0;"></video>']
    if base.has_audio:
        lines.append(
            '    <audio id="review-base-audio"'
            ' data-hf-id="hf-review-base-audio"'
            f' src="{base.src_rel}"'
            f' data-has-audio="true" data-start="0" data-duration="{duration}"'
            ' data-track-index="10" data-volume="1"></audio>')
    return lines


#: Same-aspect predicate shared with the renderer's overlay normalization
#: (``graphics/delivery_geometry.py`` / ``comp_measure``).
_ASPECT_TOLERANCE = 0.002


def slot_scale(comp: tuple[int, int], stage: tuple[int, int]) -> tuple[float,
                                                                       float]:
    """The mounted comp's stage transform, mirroring the renderer.

    ``fit_delivery_geometry`` scales a same-aspect full-canvas overlay by
    ``delivery / authored`` (own-screen takeovers included via
    ``own_screen_meta``); a different-aspect overlay composites unscaled at
    its authored size. Studio mounts a comp at its literal authored pixels,
    so the review view applies the same factor to stay truthful — without
    it a 1920x1080 comp on a 3840x2160 base occupies the top-left quarter.
    """
    comp_w, comp_h = comp
    stage_w, stage_h = stage
    if (comp_w, comp_h) == (stage_w, stage_h):
        return 1.0, 1.0
    if abs(comp_w / comp_h - stage_w / stage_h) > _ASPECT_TOLERANCE:
        return 1.0, 1.0
    return stage_w / comp_w, stage_h / comp_h


def _slot_element(clip: ReviewClip, scale: tuple[float, float]) -> str:
    """Emit one original host with its existing scale, identity, values and timing."""
    duration = sec(clip.out_end - clip.out_start)
    style = f"z-index: {clip.z_index};"
    if scale != (1.0, 1.0):
        style += (f" --review-sx: {sec(scale[0])};"
                  f" --review-sy: {sec(scale[1])};")
    return (
        f'    <div id="{clip.slot_id}" class="clip"'
        f' data-hf-id="hf-slot-{html.escape(clip.slot_id, quote=True)}"'
        f' data-composition-id="{clip.instance_id}"'
        f' data-composition-src="{clip.file_rel}"'
        f" data-variable-values='{_values_attr(clip.spec)}'"
        f' data-start="{sec(clip.out_start)}" data-duration="{duration}"'
        f' data-track-index="{clip.track}" data-width="{clip.width}"'
        f' data-height="{clip.height}" style="{style}">'
        "</div>")


def _head(title: str, need_split_text: bool) -> list[str]:
    """Preserve the original head bytes and conditional SplitText dependency."""
    lines = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '  <meta charset="UTF-8">',
        f"  <title>{html.escape(title)}</title>",
        '  <link rel="stylesheet" href="assets/tokens.css">',
        '  <script src="assets/vendor/gsap.min.js"></script>']
    if need_split_text:
        lines.append('  <script src="assets/vendor/SplitText.min.js"></script>')
    lines += [
        '  <script src="assets/vendor/motion-tokens.js"></script>',
        "  <style>",
        "    html, body { margin: 0; padding: 0; background: #111; }",
        # Keyed on .clip, NOT [data-composition-src]: the preview runtime
        # strips that attribute from the host slot when it mounts the comp,
        # which would silently drop this rule mid-session (verified live).
        "    #review-root > div.clip "
        "{ position: absolute; inset: 0; transform-origin: 0 0;"
        " transform: scale(var(--review-sx, 1), var(--review-sy, 1)); }",
        "  </style>",
        "</head>"]
    return lines


def provenance_bindings(clips: list[ReviewClip]) -> str:
    """Encode the exact generator-owned statement shared with deletion sync."""
    bindings = [[clip.slot_id, clip.instance_id, clip.file_rel] for clip in clips]
    encoded = json.dumps(bindings, ensure_ascii=True).replace("<", "\\u003c")
    return f"const bindings = {encoded};"


def _provenance_script(clips: list[ReviewClip]) -> list[str]:
    """Repair pinned Studio's mounted-host attribution, never source files.

    CLI 0.7.33 inlining assigns the child file to the parent host. Its UI
    consequently tries saving parent timing into the child file. Preserve
    descendant provenance and restore only exact generated review hosts.
    This script is part of index.html's immutable generation fingerprint.
    """
    return ["  (() => {", f"    {provenance_bindings(clips)}",
            "    const root = document.getElementById('review-root');",
            "    const errors = new Set();",
            "    const fail = (id) => {",
            "      if (errors.has(id)) return; errors.add(id);",
            "      console.error('Sniper Studio source attribution blocked: ' + id);",
            "    };",
            "    if (!root || root.getAttribute('data-hf-id') !== 'hf-review-root') { fail('root'); return; }",
            "    const repair = () => bindings.forEach(([id, instance, file]) => {",
            "      const host = document.getElementById(id);",
            "      if (!host || host.parentElement !== root ||",
            "          host.getAttribute('data-hf-id') !== 'hf-slot-' + id ||",
            "          host.getAttribute('data-composition-id') !== instance) { fail(id); return; }",
            "      const pending = host.getAttribute('data-composition-src');",
            "      if (pending !== null) { if (pending !== file) fail(id); return; }",
            "      const mounted = host.getAttribute('data-composition-file');",
            "      if (mounted !== file && mounted !== 'index.html') { fail(id); return; }",
            "      for (const child of host.children) {",
            "        if (!child.hasAttribute('data-composition-file') && !child.hasAttribute('data-composition-src'))",
            "          child.setAttribute('data-composition-file', file);",
            "      }",
            "      if (mounted !== 'index.html') host.setAttribute('data-composition-file', 'index.html');",
            "    });",
            "    repair();",
            "    new MutationObserver(repair).observe(root, { childList: true, subtree: true,",
            "      attributes: true, attributeFilter: ['data-composition-file', 'data-composition-src'] });",
            "  })();"]


def build_index_html(base: ReviewBase, clips: list[ReviewClip],
                     title: str, need_split_text: bool) -> str:
    """Build the entry timeline with stable Studio selection IDs.

    Pinned Studio persists a DOM-serialized file when any body element
    needs ``data-hf-id``. Seed every eligible host element so opening a
    fresh view cannot rewrite raw JSON attributes or create false edits.
    These IDs intentionally survive copy, timing and placement changes.
    """
    fps = f' data-fps="{sec(base.fps)}"' if base.fps else ""
    root_open = (
        f'  <div id="review-root" data-composition-id="{REVIEW_COMP_ID}"'
        ' data-hf-id="hf-review-root"'
        f' data-width="{base.width}" data-height="{base.height}"'
        f' data-duration="{sec(base.duration)}"{fps} data-start="0"'
        f' style="position: relative; width: {base.width}px;'
        f' height: {base.height}px; overflow: hidden; background: #000;">')
    script = [
        "  <script>",
        "    const tl = gsap.timeline({ paused: true });",
        f"    tl.to({{}}, {{ duration: {sec(base.duration)} }});",
        "    window.__timelines = window.__timelines || {};",
        f'    window.__timelines["{REVIEW_COMP_ID}"] = tl;']
    script += _provenance_script(clips) + ["  </script>"]
    stage = (base.width, base.height)
    return "\n".join(
        _head(title, need_split_text)
        + ["<body>", root_open]
        + _media_elements(base)
        + [_slot_element(clip, slot_scale((clip.width, clip.height), stage))
           for clip in clips]
        + ["  </div>"] + script
        + ["</body>", "</html>", ""])


def build_storyboard(base: ReviewBase, clips: list[ReviewClip],
                     title: str) -> str:
    """Contact-sheet STORYBOARD.md — one frame per graphicsTrack entry."""
    lines = [f"# {title}", "",
             f"Base: {base.src_rel} ({base.width}x{base.height}, "
             f"{sec(base.duration)}s)", ""]
    if not clips:
        lines += ["No graphics are authored in this plan. The base is available "
                  "for playback review; cut changes belong in edit_plan.json, "
                  "followed by rebuild and regeneration of this view.", ""]
    for i, clip in enumerate(clips, start=1):
        duration = sec(clip.out_end - clip.out_start)
        lines += [
            f"## Frame {i} — {clip.kind}", "",
            f"- src: {clip.file_rel}",
            f"- window: {sec(clip.out_start)}–{sec(clip.out_end)}s "
            f"(duration {duration}s, track {clip.track})",
            f"- scene: {clip.reason}", ""]
    return "\n".join(lines)


def hyperframes_json_text() -> str:
    """The project descriptor Studio reads paths from."""
    return json.dumps(_HYPERFRAMES_JSON, indent=2, sort_keys=False) + "\n"
