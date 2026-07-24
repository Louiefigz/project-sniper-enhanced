#!/usr/bin/env python3
"""comp_catalog_probe — measured capability matrix for every registered comp.

Two passes over ``templates/motion/compositions/*.html``:

* STATIC (cheap, all comps): canvas dims from the ``#<id>-root`` CSS rule
  (explicit px or ``var(--canvas-w/h)`` resolved through tokens.css, default
  1080x1920), the ``data-composition-variables`` field ids + defaults, and
  whether the template exposes a position knob (slotX/x/align family) or is a
  fixed layout.
* RENDER (real path, content-hash cached): render each comp ONCE with its
  declared defaults through ``graphics_render.render_entry``, then measure the
  terminal-frame alpha (``frame_oracles.terminal_alpha``) into a fade class —
  ``fades-clean`` (passes the render-proof bounds) / ``hold-to-cut``
  (mean > 64) / ``partial-fade`` (between) — and the settled content bbox
  (``planner.graphics_anchors._content_bbox``). Comps that fail to render
  record ``{"renderError": msg}`` honestly.

Emits ``templates/motion/comp_capabilities.json``: a deterministic core (no
timestamps) plus a stable digest of the per-comp entries.

CLI: comp_catalog_probe.py [--out F] [--cache-dir D] [--workers N] [--static-only]
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # run-by-path: producer pkg root on sys.path
from graphics import frame_oracles
from graphics.graphics_render import (COMPOSITIONS_DIR, DEFAULT_CACHE_DIR,
                                      TOKENS_CSS, content_hash, format_for,
                                      render_entry)
from graphics.render_tools import resolve_tools
from graphics.template_contract import (composition_dimensions,
                                        declared_variables)
from graphics.template_visual_contract import _TIMING_POLICY, _latest_reveal
from planner.graphics_anchors import _content_bbox

_DEFAULT_CANVAS = (1080, 1920)
_MIN_PROBE_S = 2.5
_ROOT_CSS_RE = re.compile(r"#[\w-]*-root\s*\{(?P<body>[^}]*)\}")
_DIM_CSS_RE = re.compile(
    r"(?P<axis>width|height)\s*:\s*(?:(?P<px>\d+)px|var\(--canvas-(?P<var>[wh])\))")
_TOKEN_RE = re.compile(r"--canvas-(?P<axis>[wh])\s*:\s*(?P<px>\d+)px")
_POS_KNOB_RE = re.compile(
    r"^(x|y|align[XY]?|anchor[XY]?|side|corner|position"
    r"|(slot|pos|offset)[XY])$", re.IGNORECASE)
_ALPHA_MSG_RE = re.compile(r"max=(\d+), mean=([0-9.]+)")
# Deterministic identity/asset fill-ins where the template's own defaults are
# rejected by the fail-closed contract (empty portrait / short brand names).
_PROBE_OVERRIDES: dict[str, dict] = {
    "avatar-bio-card": {"initials": "AF"},
    "icon-badge-wide": {"icon1": "openai-color.svg",
                        "icon2": "claude-color.svg",
                        "icon3": "gemini-color.svg"},
}


def tokens_canvas(tokens_css_text: str | None = None) -> tuple[int, int]:
    """Resolve ``--canvas-w/h`` from tokens.css text (repo file by default).

    Args:
        tokens_css_text: Raw tokens.css content; ``None`` reads the repo file.

    Returns:
        The ``(width, height)`` the shared tokens declare, defaulting to
        1080x1920 when a token is absent.
    """
    if tokens_css_text is None:
        with open(TOKENS_CSS, encoding="utf-8") as handle:
            tokens_css_text = handle.read()
    found = {m.group("axis"): int(m.group("px"))
             for m in _TOKEN_RE.finditer(tokens_css_text)}
    return (found.get("w", _DEFAULT_CANVAS[0]),
            found.get("h", _DEFAULT_CANVAS[1]))


def css_canvas(comp_html: str,
               tokens_css_text: str | None = None) -> tuple[int, int]:
    """Canvas dims from the ``#<id>-root`` rule (px or canvas-var indirection).

    Args:
        comp_html: The composition's full HTML source.
        tokens_css_text: Optional tokens.css text for var resolution.

    Returns:
        The ``(width, height)`` of the root element, falling back to the
        tokens/default canvas for any axis the rule leaves implicit.
    """
    token_w, token_h = tokens_canvas(tokens_css_text)
    dims = {"width": token_w, "height": token_h}
    root = _ROOT_CSS_RE.search(comp_html)
    if root is not None:
        for match in _DIM_CSS_RE.finditer(root.group("body")):
            if match.group("px"):
                dims[match.group("axis")] = int(match.group("px"))
            else:
                dims[match.group("axis")] = (token_w if match.group("var") == "w"
                                             else token_h)
    return dims["width"], dims["height"]


def probe_spec(kind: str, declared: dict[str, dict]) -> dict:
    """Default-variable spec for one probe render (empty strings omitted)."""
    spec = {key: row["default"] for key, row in declared.items()
            if "default" in row
            and not (isinstance(row["default"], str) and not row["default"].strip())}
    spec.update(_PROBE_OVERRIDES.get(kind, {}))
    return spec


def probe_duration(kind: str, spec: dict) -> float:
    """Shortest honest probe window: 2.5s or the comp's completion floor."""
    reveal = _latest_reveal(spec)
    duration = max(_MIN_PROBE_S, reveal + 0.75)
    policy = _TIMING_POLICY.get(kind)
    if policy is not None:
        floor, settle, dwell, runway = policy
        duration = max(duration, floor, reveal + settle + dwell + runway)
    return round(duration, 2)


def static_probe(kind: str, comp_html: str) -> dict:
    """STATIC pass: canvas, aspect, declared fields, and position knobs."""
    canvas = css_canvas(comp_html)
    entry: dict = {"canvas": list(canvas),
                   "aspect": "9:16" if canvas[1] > canvas[0] else "16:9"}
    declared_dims = composition_dimensions(comp_html)
    if declared_dims != canvas:
        entry["canvasNote"] = (f"css root {canvas} != declared data-width/"
                               f"height {declared_dims}")
    declared = declared_variables(comp_html)
    entry["specFields"] = sorted(declared)
    entry["specDefaults"] = {key: row.get("default")
                             for key, row in sorted(declared.items())}
    entry["positionKnobs"] = sorted(
        key for key in declared if _POS_KNOB_RE.match(key))
    return entry


def _fade_class(max8: int, mean8: float) -> str:
    """Classify a terminal-frame alpha measurement into the fade taxonomy."""
    if (max8 <= frame_oracles._TERMINAL_MAX_ALPHA_8
            and mean8 <= frame_oracles._TERMINAL_MEAN_ALPHA_8):
        return "fades-clean"
    return "hold-to-cut" if mean8 > 64 else "partial-fade"


def _terminal_measure(path: str, frame_count: int) -> tuple[int, float]:
    """Terminal max/mean alpha via the shared oracle (values, not verdict)."""
    environment = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                   "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC"}
    try:
        result = frame_oracles.terminal_alpha(
            path, frame_count, resolve_tools()["ffmpeg"], environment)
        return result["maxAlpha8"], result["meanAlpha8"]
    except RuntimeError as exc:
        match = _ALPHA_MSG_RE.search(str(exc))
        if match is None:
            raise
        return int(match.group(1)), float(match.group(2))


def _quarantined_artifact(entry: dict, cache_dir: str) -> str | None:
    """Newest quarantined render for this probe key (proof-rejected holds)."""
    kind, spec = entry["kind"], entry["spec"]
    duration = float(entry["outEnd"]) - float(entry["outStart"])
    _, ext = format_for(kind, entry["anchor"], spec)
    with open(os.path.join(COMPOSITIONS_DIR, f"{kind}.html"),
              encoding="utf-8") as handle:
        key = content_hash(kind, spec, duration, handle.read())
    rejected = glob.glob(os.path.join(cache_dir, f"{key}.{ext}.rejected-*"))
    media = [path for path in rejected if not path.split(".rejected-")[0]
             .endswith((".proof.json", ".runtime.json", ".input.tar"))]
    return max(media, key=os.path.getmtime) if media else None


def _measure_artifact(result: dict, path: str, frame_count: int,
                      proof_terminal: dict | None) -> None:
    """Fill fadeClass + contentBBox from one rendered alpha artifact."""
    if proof_terminal is not None:
        max8, mean8 = proof_terminal["maxAlpha8"], proof_terminal["meanAlpha8"]
    else:
        max8, mean8 = _terminal_measure(path, frame_count)
    result["terminalAlpha"] = {"maxAlpha8": max8, "meanAlpha8": round(mean8, 2)}
    result["fadeClass"] = _fade_class(max8, mean8)
    bbox = _content_bbox(path)
    result["contentBBox"] = list(bbox)
    result["contentDims"] = [bbox[2] - bbox[0], bbox[3] - bbox[1]]


def render_probe(kind: str, declared: dict[str, dict], cache_dir: str) -> dict:
    """RENDER pass: one default-variable render, honestly measured."""
    spec = probe_spec(kind, declared)
    duration = probe_duration(kind, spec)
    entry = {"kind": kind, "spec": spec, "anchor": "free-band",
             "outStart": 0.0, "outEnd": duration}
    result: dict = {"probeDurationS": duration}
    try:
        rendered = render_entry(entry, cache_dir)
        _measure_artifact(result, rendered["path"],
                          rendered["proof"]["asset"]["frameCount"],
                          rendered["proof"].get("terminalFrame"))
        return result
    except (RuntimeError, ValueError, OSError) as exc:
        message = str(exc)
    if "retains alpha" in message:  # proof-rejected hold: measure the evidence
        artifact = _quarantined_artifact(entry, cache_dir)
        if artifact is not None:
            try:
                _measure_artifact(result, artifact, round(duration * 30), None)
                result["renderNote"] = ("render proof rejected the terminal "
                                       "frame (unregistered hold-to-cut); "
                                       "measured from the quarantined artifact")
                return result
            except (RuntimeError, ValueError, OSError) as exc:
                message = f"{message}; quarantined-artifact measure failed: {exc}"
    result["renderError"] = message
    return result


def build_catalog(cache_dir: str, workers: int, static_only: bool) -> dict:
    """Probe every registered composition; return the deterministic core."""
    paths = [path for path
             in sorted(glob.glob(os.path.join(COMPOSITIONS_DIR, "*.html")))
             if not os.path.basename(path).startswith("_gs-")]
    sources = {}
    for path in paths:
        with open(path, encoding="utf-8") as handle:
            sources[os.path.splitext(os.path.basename(path))[0]] = handle.read()
    comps = {kind: static_probe(kind, html) for kind, html in sources.items()}
    if not static_only:
        kinds = sorted(sources)
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            rendered = pool.map(
                lambda kind: render_probe(
                    kind, declared_variables(sources[kind]), cache_dir), kinds)
            for kind, measured in zip(kinds, rendered):
                comps[kind].update(measured)
    digest = hashlib.sha1(json.dumps(
        comps, sort_keys=True, ensure_ascii=True).encode("utf-8")).hexdigest()
    return {"schemaVersion": 1, "comps": comps, "digest": digest}


def main() -> int:
    """CLI entry point: probe the catalog and write comp_capabilities.json."""
    parser = argparse.ArgumentParser(
        description="Measured capability matrix for every motion composition")
    parser.add_argument("--out", default=os.path.join(
        os.path.dirname(COMPOSITIONS_DIR), "comp_capabilities.json"))
    parser.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--static-only", action="store_true",
                        help="skip the render pass (canvas/fields/knobs only)")
    args = parser.parse_args()
    catalog = build_catalog(args.cache_dir, args.workers, args.static_only)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(catalog, handle, indent=2, sort_keys=True)
        handle.write("\n")
    errors = sorted(kind for kind, row in catalog["comps"].items()
                    if "renderError" in row)
    print(json.dumps({"comps": len(catalog["comps"]), "renderErrors": errors,
                      "digest": catalog["digest"], "out": args.out}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
