"""Resolve and bake production placement into Palmier checkpoint graphics."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from fingerprints import file_sha256, video_fingerprint
from graphics.delivery_geometry import (
    fit_delivery_geometry,
    own_screen_meta,
)
from graphics.placement_context import is_face_aware
from graphics.pip_hole import entry_has_hole
from graphics.stage_placement import resolve_placement
from ingest_probe import probe_media
from motion.recompose import requires_recompose
from palmier.checkpoint_graphics_cache import (
    PlacedAssetRequest,
    materialize_placed_asset,
)
from palmier.mcp_client import PalmierError
from planner.graphics_anchors import _clip_dims
from planner.occupancy import plan_band_offset


@dataclass(frozen=True)
class PlacementBakeContext:
    """Delivery and geometry authority for full-canvas checkpoint assets."""

    cache_dir: str
    fps: float
    width: int
    height: int
    reference_path: str | None = None
    reference_hash: str | None = None
    band_y_offset_px: float = 0.0

    @property
    def canvas(self) -> tuple[int, int]:
        return self.width, self.height


def _read_json(path: str, label: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PalmierError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise PalmierError(f"{label} is not an object")
    return value


def _base_current(out_dir: str, plan: dict) -> str | None:
    base = os.path.join(out_dir, "base_final.mp4")
    record_path = os.path.join(out_dir, "base.fingerprint.json")
    if not os.path.isfile(base) or not os.path.isfile(record_path):
        return None
    try:
        record = _read_json(record_path, "base fingerprint")
    except PalmierError:
        return None
    return base if record.get("videoFingerprint") == video_fingerprint(plan) \
        else None


def current_placement_reference(
    out_dir: str,
    plan: dict,
    canvas: tuple[int, int],
) -> tuple[str, str] | None:
    """Return the current graphics-free base iff it is exact delivery geometry."""
    base = _base_current(out_dir, plan)
    if base is None:
        return None
    try:
        probe = probe_media(base)
    except (OSError, RuntimeError, ValueError):
        return None
    facts = (probe.width, probe.height, probe.duration, probe.fps)
    if any(value is None for value in facts) or probe.vfr \
            or (int(probe.width), int(probe.height)) != canvas:
        return None
    return os.path.abspath(base), file_sha256(base)


def placement_context(
    out_dir: str,
    plan: dict,
    cache_dir: str,
    project: dict,
) -> PlacementBakeContext:
    """Build the shared checkpoint/repair placement context."""
    fps = float(project["fps"])
    width, height = int(project["width"]), int(project["height"])
    reference = current_placement_reference(
        out_dir, plan, (width, height))
    return PlacementBakeContext(
        cache_dir, fps, width, height,
        reference[0] if reference else None,
        reference[1] if reference else None,
        plan_band_offset(plan))


def _reference(context: PlacementBakeContext) -> dict | None:
    path = context.reference_path
    if path is None:
        return None
    digest = context.reference_hash or file_sha256(path)
    try:
        probe = probe_media(path)
    except (OSError, RuntimeError, ValueError) as exc:
        raise PalmierError(f"cannot probe checkpoint placement base: {exc}") from exc
    if probe.vfr or (probe.width, probe.height) != context.canvas:
        raise PalmierError(
            "checkpoint placement base does not match the delivery canvas")
    return {"path": os.path.abspath(path), "sha256": digest}


def assert_reference_current(context: PlacementBakeContext) -> None:
    """Recheck the one large placement input once after all graphics bake."""
    if context.reference_path is None:
        return
    expected = context.reference_hash
    if expected is not None and file_sha256(context.reference_path) != expected:
        raise PalmierError("checkpoint placement reference changed during bake")


def _proof(rendered: dict) -> dict:
    proof = rendered.get("proof")
    if not isinstance(proof, dict) or proof.get("schemaVersion") != 1:
        raise PalmierError("checkpoint graphic has no rendered asset proof")
    return proof


def unsupported_base_semantic(entry: dict) -> str | None:
    """Name a production base mutation an isolated alpha asset cannot carry."""
    if entry.get("takeoverBase") is not None:
        return "takeoverBase changes the footage beneath the graphic"
    if entry.get("anchor", "free-band") == "focus-shift":
        return "focus-shift blurs the footage beneath the graphic"
    if entry_has_hole(entry):
        return "presenter PIP crops and replaces the footage beneath the comp"
    return None


def _resolve(entry: dict, rendered: dict,
             context: PlacementBakeContext) -> tuple:
    unsupported = unsupported_base_semantic(entry)
    if unsupported:
        raise PalmierError(
            f"graphic {entry.get('id') or entry.get('kind')!r} cannot use a "
            f"normalized Palmier alpha asset: {unsupported}")
    raw_path = rendered["path"]
    anchor = entry.get("anchor", "free-band")
    if anchor == "own-screen" and entry.get("placement") is None:
        return own_screen_meta(_clip_dims(raw_path), context.canvas), None
    reference = _reference(context)
    needs_reference = is_face_aware(entry) and not requires_recompose(entry)
    if needs_reference and reference is None:
        raise PalmierError(
            f"graphic {entry.get('id') or entry.get('kind')!r} needs the "
            "current graphics-free base for exact face-aware placement")
    video = reference["path"] if reference else raw_path
    placed = resolve_placement(
        entry, raw_path, video, context.band_y_offset_px)
    return placed, reference if needs_reference else None


def bake_rendered_graphic(
    entry: dict,
    rendered: dict,
    context: PlacementBakeContext,
) -> dict:
    """Bake one production-resolved x/y/scale onto a full delivery canvas."""
    proof = _proof(rendered)
    placed, reference = _resolve(entry, rendered, context)
    x, y, meta = fit_delivery_geometry(
        rendered["path"], (placed[0], placed[1]), placed[2], context.canvas)
    request = PlacedAssetRequest(
        entry, rendered["path"], proof, context.cache_dir, context.fps,
        context.canvas, (x, y), meta, reference)
    result = materialize_placed_asset(request)
    return {**rendered, **result, "fmt": "mov",
            "placement": {"x": x, "y": y, "metadata": meta}}


def _rendered(path: str, entry: dict) -> dict:
    proof_path = path + ".proof.json"
    proof = _read_json(proof_path, "checkpoint graphic proof")
    return {"path": path, "proof": proof, "kind": entry.get("kind"),
            "fmt": "mov"}


def bake_checkpoint_graphics(
    plan: dict,
    graphics: dict[int, str],
    context: PlacementBakeContext,
) -> tuple[dict[int, str], list[dict]]:
    """Bake every normal graphic and synthetic transition in plan order."""
    rows = plan.get("graphicsTrack") or []
    paths: dict[int, str] = {}
    receipts: list[dict] = []
    for index, entry in enumerate(rows):
        path = graphics.get(index)
        if not isinstance(path, str):
            raise PalmierError(
                f"graphicsTrack[{index}] has no checkpoint render")
        result = bake_rendered_graphic(entry, _rendered(path, entry), context)
        paths[index] = result["path"]
        receipts.append(result["receipt"])
    assert_reference_current(context)
    return paths, receipts
