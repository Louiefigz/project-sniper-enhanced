#!/usr/bin/env python3
"""graphics_render — hyperframes render + content-hash cache for one MG entry.

Turns a single ``graphicsTrack`` entry (docs/producer/PRODUCER_MOTION_GRAPHICS_PLAN.md
§3.1) into a rendered overlay clip, memoized by content hash so a graphic that
is unchanged across plan revisions reuses the render at $0/0s (§5.5 optimization
1 — "the single biggest lever for the feedback loop").

Two render products, chosen by ``anchor`` (§2.1 visual-state doctrine):

* ``free-band`` → transparent-alpha ProRes 4444 ``.mov``. The comps are
  full-canvas 1080x1920 and position their content in the free band internally,
  so the compositor just overlays at (0,0) and alpha handles the rest. webm is
  NOT usable — it drops the alpha channel (proven, edge G2).
* ``own-screen`` → opaque H.264 ``.mp4``. The takeover cutaway (kinetic-quote):
  it REPLACES the frame for its window instead of stacking on it.

RENDER LENGTH is the composition root's ``data-duration`` ATTRIBUTE — hyperframes
fixes it at compile time and IGNORES ``--variables`` for it (each comp's header
comment states this). So this module writes a temp comp copy under
``compositions/_gs-<key>.html`` with that one attribute rewritten to the entry's
window length, renders it, then removes the copy. No template is ever edited.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # run-by-path: producer pkg root on sys.path
from fingerprints import json_canon
from graphics.asset_proof import prove_rendered_asset
from graphics.pip_hole import entry_has_hole
from graphics.template_contract import (
    composition_dimensions,
    resolved_assets,
    validate_entry,
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINE_ROOT = os.environ.get(
    "SNIPER_PIPELINE_ROOT",
    os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", "..")))
RUNTIME_ROOT = os.environ.get("SNIPER_RUNTIME_REPO_ROOT", PIPELINE_ROOT)
MOTION_DIR = os.path.join(PIPELINE_ROOT, "templates", "motion")
COMPOSITIONS_DIR = os.path.join(MOTION_DIR, "compositions")
TOKENS_CSS = os.path.join(MOTION_DIR, "tokens.css")
MOTION_TOKENS_JS = os.path.join(MOTION_DIR, "motion-tokens.js")
DEFAULT_CACHE_DIR = os.path.join(MOTION_DIR, "renders", "cache")
HYPERFRAMES_PACKAGE = "hyperframes@0.7.33"

# own-screen takeovers are opaque (mp4); every other anchor overlays with alpha
# (mov). free-band = the free band; focus-shift = alpha graphic over a BLURRED
# base (R5); headroom/chest/beside-face = alpha graphic TRANSLATED face-relative
# (R3/R4). They all render the same transparent ProRes — the anchor only changes
# how graphics_stage COMPOSITES them, not how graphics_render RENDERS them.
_ALPHA = ("mov", "mov")
_FORMAT_BY_ANCHOR = {
    "own-screen": ("mp4", "mp4"),
    "free-band": _ALPHA,
    "focus-shift": _ALPHA,
    "headroom": _ALPHA,
    "chest": _ALPHA,
    "beside-face": _ALPHA,
}
# The composition root carries data-composition-id; its opening tag holds the
# root data-duration we rewrite. Child `.clip` elements keep their own (="60").
_ROOT_TAG_RE = re.compile(r'<[^>]*data-composition-id="[^"]*"[^>]*>')
_DURATION_RE = re.compile(r'data-duration="[^"]*"')


def format_for(kind: str, anchor: str, spec: dict | None = None) -> tuple[str, str]:
    """Render ``(fmt, ext)`` for one entry — the anchor decides, EXCEPT
    ACTIVE hole-comps (``graphics.pip_hole.entry_has_hole``): they render the
    frame AROUND a transparent face hole, so they need alpha even at anchor
    "own-screen" (an opaque mp4 would paint the hole black and bury the footage
    the compositor scales in underneath — NATEHERK_STUDY §5 item 9). The hole is
    ACTIVE only for nateherk-takeover or a card whose ``spec.presenterFrame`` is
    set — a plain opt-out card renders opaque like any own-screen takeover."""
    if anchor not in _FORMAT_BY_ANCHOR:
        raise ValueError(f"{kind}: unknown anchor '{anchor}' (free-band|own-screen)")
    if entry_has_hole({"kind": kind, "spec": spec}):
        return _ALPHA
    return _FORMAT_BY_ANCHOR[anchor]


def timeline_padded_entry(entry: dict, fps: float) -> dict:
    """Extend render media enough to cover its rounded timeline frame span."""
    if fps <= 0:
        raise ValueError("timeline fps must be positive")
    start, end = float(entry["outStart"]), float(entry["outEnd"])
    frame_span = round(end * fps) - round(start * fps)
    required = frame_span / fps
    if required <= end - start:
        return entry
    padded = dict(entry)
    padded["outEnd"] = start + required
    return padded


def comp_path(kind: str) -> str:
    """Absolute path to the ``kind`` composition; raise if it is not a template."""
    path = os.path.join(COMPOSITIONS_DIR, f"{kind}.html")
    if not os.path.isfile(path):
        raise ValueError(f"unknown graphic kind '{kind}': no compositions/{kind}.html")
    return path


def _set_root_duration(html: str, duration: float) -> str:
    """Rewrite ONLY the composition root's ``data-duration`` to ``duration`` (s).

    The root is the element carrying ``data-composition-id``; the substitution is
    scoped to that opening tag so the child clips' ``data-duration="60"`` sentinels
    are untouched. Raises if the root tag/attribute is not found (a malformed
    template must fail loudly, never silently render at the wrong length).
    """
    def _rewrite_tag(match: re.Match) -> str:
        tag = match.group(0)
        new_tag, n = _DURATION_RE.subn(f'data-duration="{duration:g}"', tag, count=1)
        if n != 1:
            raise ValueError("composition root tag has no data-duration attribute")
        return new_tag

    html, n = _ROOT_TAG_RE.subn(_rewrite_tag, html, count=1)
    if n != 1:
        raise ValueError("composition has no data-composition-id root element")
    return html


def content_hash(kind: str, spec: dict, duration: float, comp_html: str) -> str:
    """Content-addressed cache key (§5.5): identical inputs → identical key.

    Folds the kind, the canonical (sorted, integral-float-neutral) spec JSON,
    the window duration, the composition HTML, tokens.css AND motion-tokens.js
    (the shared runtime helpers the jaden/nateherk comps consume) — so editing
    a template or the shared tokens invalidates every cached render that used
    them. The spec goes through fingerprints.json_canon so a JS save-plan
    round-trip (30.0 → 30) never busts the cache for an unchanged graphic.
    """
    h = hashlib.sha1()
    h.update(kind.encode("utf-8"))
    h.update(json.dumps(json_canon(spec), sort_keys=True,
                        ensure_ascii=True).encode("utf-8"))
    h.update(f"{duration:.4f}".encode("utf-8"))
    h.update(hashlib.sha1(comp_html.encode("utf-8")).digest())
    for shared in (TOKENS_CSS, MOTION_TOKENS_JS):
        with open(shared, "rb") as f:
            h.update(hashlib.sha1(f.read()).digest())
    for asset in resolved_assets({"kind": kind, "spec": spec}, comp_html):
        with open(asset["path"], "rb") as handle:
            h.update(asset["field"].encode("utf-8"))
            h.update(hashlib.sha1(handle.read()).digest())
    return h.hexdigest()


def _render_to(temp_comp_rel: str, fmt: str, spec: dict, out_path: str) -> None:
    """Invoke the hyperframes CLI for one temp comp copy → ``out_path``.

    Runs from the repo root so the ``templates/motion`` project dir and the
    ``-c compositions/...`` block path resolve exactly as the proven MG-1 render.
    """
    cmd = ["npx", "--yes", HYPERFRAMES_PACKAGE, "render", MOTION_DIR,
           "-c", temp_comp_rel, "--format", fmt,
           "--variables", json.dumps(spec), "-o", out_path]
    proc = subprocess.run(cmd, cwd=RUNTIME_ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout).strip().splitlines()[-10:])
        raise RuntimeError(f"hyperframes render failed for {temp_comp_rel}:\n{tail}")
    if not os.path.exists(out_path):
        raise RuntimeError(f"hyperframes reported success but {out_path} is missing")


def render_entry(entry: dict, cache_dir: str | None = None) -> dict:
    """Render (or reuse) one graphicsTrack entry's overlay clip.

    Returns ``{"path", "cached", "key", "kind", "fmt"}``. On a cache miss the comp
    is rendered at the entry's window length via a throwaway ``_gs-<key>`` copy;
    on a hit the render is skipped entirely.
    """
    kind = entry["kind"]
    spec = entry.get("spec") or {}
    anchor = entry.get("anchor", "free-band")
    duration = float(entry["outEnd"]) - float(entry["outStart"])
    if duration <= 0:
        raise ValueError(f"{kind}: non-positive window {entry['outStart']}->{entry['outEnd']}")
    fmt, ext = format_for(kind, anchor, spec)

    with open(comp_path(kind), encoding="utf-8") as f:
        comp_html = f.read()
    validate_entry(entry, comp_html)
    dimensions = composition_dimensions(comp_html)
    key = content_hash(kind, spec, duration, comp_html)
    cache_dir = cache_dir or DEFAULT_CACHE_DIR
    os.makedirs(cache_dir, exist_ok=True)
    out_path = os.path.join(cache_dir, f"{key}.{ext}")
    if os.path.exists(out_path):
        proof = prove_rendered_asset(
            out_path, entry, fmt, dimensions, duration, key)
        return {"path": out_path, "cached": True, "key": key, "kind": kind,
                "fmt": fmt, "proof": proof}

    temp_rel = os.path.join("compositions", f"_gs-{key}.html")
    temp_abs = os.path.join(MOTION_DIR, temp_rel)
    try:
        with open(temp_abs, "w", encoding="utf-8") as f:
            f.write(_set_root_duration(comp_html, duration))
        _render_to(temp_rel, fmt, spec, out_path)
    finally:
        if os.path.exists(temp_abs):
            os.remove(temp_abs)
    proof = prove_rendered_asset(out_path, entry, fmt, dimensions, duration, key)
    return {"path": out_path, "cached": False, "key": key, "kind": kind,
            "fmt": fmt, "proof": proof}
