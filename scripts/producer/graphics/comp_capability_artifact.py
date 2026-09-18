#!/usr/bin/env python3
"""Integrity and freshness contract for the measured comp-capability artifact."""
from __future__ import annotations

import glob
import hashlib
import json
import os
from typing import Optional

from headless.source_closure import discover_root_sources, discover_source_set

SCHEMA_VERSION = 2
MOTION_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "templates", "motion"))
COMPOSITIONS_DIR = os.path.join(MOTION_DIR, "compositions")
_FADE_CLASSES = {"fades-clean", "hold-to-cut", "partial-fade"}
_SHARED_RUNTIME_FILES = (
    "hyperframes.json", "index.html", "motion-tokens.js", "package-lock.json",
    "package.json", "tokens.css",
)


def composition_paths() -> list[str]:
    """Registered composition paths, excluding throwaway render copies."""
    return [path for path in sorted(glob.glob(
        os.path.join(COMPOSITIONS_DIR, "*.html")))
        if not os.path.basename(path).startswith("_gs-")]


def composition_kinds() -> set[str]:
    """The exact registered comp inventory represented by a fresh artifact."""
    return {os.path.splitext(os.path.basename(path))[0]
            for path in composition_paths()}


def _read_motion(relative: str) -> bytes:
    """Read one regular, non-symlink source below the motion root."""
    candidate = os.path.abspath(os.path.join(MOTION_DIR, relative))
    if (os.path.commonpath((candidate, MOTION_DIR)) != MOTION_DIR
            or os.path.islink(candidate) or not os.path.isfile(candidate)):
        raise RuntimeError(f"invalid motion source dependency: {relative}")
    with open(candidate, "rb") as handle:
        return handle.read()


def composition_source_closure(comp_html: str) -> dict[str, bytes]:
    """Local files HyperFrames may read for one composition."""
    return discover_root_sources(comp_html, MOTION_DIR)


def current_source_digest() -> str:
    """Digest every comp plus its local runtime closure and selectable icons."""
    paths = set(composition_paths())
    sources = (_read_motion(os.path.relpath(path, MOTION_DIR)).decode("utf-8")
               for path in sorted(paths))
    dependencies = discover_source_set(sources, _read_motion)
    paths.update(os.path.join(MOTION_DIR, relative) for relative in dependencies)
    paths.update(os.path.join(MOTION_DIR, name)
                 for name in _SHARED_RUNTIME_FILES)
    for subdir in ("icons", "reference", os.path.join("vendor", "gsap")):
        paths.update(glob.glob(
            os.path.join(MOTION_DIR, subdir, "**", "*"), recursive=True))
    digest = hashlib.sha256()
    for path in sorted(path for path in paths if os.path.isfile(path)):
        relative = os.path.relpath(path, MOTION_DIR)
        data = _read_motion(relative)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(data).digest())
    return digest.hexdigest()


def capability_digest(comps: dict) -> str:
    """Stable digest of the measured per-comp rows."""
    encoded = json.dumps(
        comps, sort_keys=True, ensure_ascii=True).encode("utf-8")
    return hashlib.sha1(encoded).hexdigest()


def build_artifact(comps: dict) -> dict:
    """Wrap measured rows in the release-critical integrity envelope."""
    return {"schemaVersion": SCHEMA_VERSION, "comps": comps,
            "digest": capability_digest(comps),
            "sourceDigest": current_source_digest()}


def capability_row_issue(row: object) -> Optional[str]:
    """Why one referenced row is not a complete measured capability."""
    if not isinstance(row, dict):
        return "capability row is not an object"
    if row.get("renderError"):
        return f"render probe failed: {row['renderError']}"
    canvas = row.get("canvas")
    if (not isinstance(canvas, list) or len(canvas) != 2
            or any(type(value) is not int or value <= 0 for value in canvas)):
        return "measured canvas is missing or malformed"
    expected_aspect = "9:16" if canvas[1] > canvas[0] else "16:9"
    if row.get("aspect") != expected_aspect:
        return "measured aspect is missing or disagrees with the canvas"
    if row.get("fadeClass") not in _FADE_CLASSES:
        return "fadeClass is missing or unmeasured"
    bbox = row.get("contentBBox")
    if (not isinstance(bbox, list) or len(bbox) != 4
            or any(type(value) is not int for value in bbox)):
        return "settled contentBBox is missing or malformed"
    x0, y0, x1, y1 = bbox
    if not (0 <= x0 <= x1 < canvas[0] and 0 <= y0 <= y1 < canvas[1]):
        return "settled contentBBox falls outside the measured canvas"
    terminal = row.get("terminalAlpha")
    if not isinstance(terminal, dict):
        return "terminal alpha measurement is missing"
    return None


def load_artifact(path: str) -> tuple[Optional[dict], str]:
    """Load only a fresh, integral, inventory-complete capability artifact."""
    if not os.path.isfile(path):
        return None, f"matrix file missing: {path}"
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"matrix unreadable: {path} — {exc}"
    if not isinstance(data, dict) or data.get("schemaVersion") != SCHEMA_VERSION:
        return None, (f"matrix schema is stale: expected {SCHEMA_VERSION}, got "
                      f"{data.get('schemaVersion') if isinstance(data, dict) else None}")
    comps = data.get("comps")
    if not isinstance(comps, dict) or not comps:
        return None, f"matrix malformed: {path} carries no comps map"
    if data.get("digest") != capability_digest(comps):
        return None, "matrix capability digest does not match its comp rows"
    try:
        current_digest = current_source_digest()
    except (OSError, RuntimeError, UnicodeDecodeError) as exc:
        return None, f"motion source closure is invalid: {exc}"
    if data.get("sourceDigest") != current_digest:
        return None, "matrix is stale: motion source digest changed"
    missing = sorted(composition_kinds() - set(comps))
    extra = sorted(set(comps) - composition_kinds())
    if missing or extra:
        return None, f"matrix inventory mismatch: missing={missing}, extra={extra}"
    return comps, ""
