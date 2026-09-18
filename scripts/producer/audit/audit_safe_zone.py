"""Geometry-bound bottom-edge heuristic; never a caption/graphic collision proof."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PIL import Image

from audit.audit_checks import CheckResult, FAIL, PASS, WARN
from audit.audit_probe import edge_density_image
from captions.caption_context import validate_destination
from captions.caption_plan_pipeline import _destination as caption_destination

if TYPE_CHECKING:
    from audit.audit_frames import FrameRef

POLICY = "geometry-bound-bottom-edge-v2"
EDGE_STEP_THRESHOLD = 40
DANGER_EDGE_DENSITY_WARN = 0.015


class UnsupportedSafeZone(ValueError):
    """The current destination policy cannot qualify this observation."""


@dataclass(frozen=True)
class SafeZoneScope:
    """Actual expected raster and exact policy-derived half-open scan band."""

    canvas: tuple[int, int]
    top: int
    bottom: int


def _dimensions(video: object) -> tuple[int, int]:
    """Reject missing or coerced stream geometry before opening a raster."""
    if not isinstance(video, dict):
        raise ValueError("actual video geometry is missing")
    values = (video.get("width"), video.get("height"))
    if any(type(value) is not int or value < 2 for value in values):
        raise ValueError("actual video geometry must contain positive integers")
    return values


def resolve_scope(plan: object, video: object) -> SafeZoneScope:
    """Reuse renderer destination policy; never trust sidecar-selected insets.

    This measures the configured exclusion band, not actual caption glyphs.
    Caption authority remains a separate mandatory Audit B check.
    """
    actual = _dimensions(video)
    if not isinstance(plan, dict) or not isinstance(plan.get("target"), dict):
        raise ValueError("plan target geometry is missing")
    destination = validate_destination(caption_destination(plan))
    canvas = (destination["width"], destination["height"])
    if actual != canvas:
        if plan["target"].get("mode") == "longform" and "captionsTrack" not in plan:
            raise UnsupportedSafeZone("legacy passthrough canvas has no qualified scan policy")
        raise ValueError("actual video canvas differs from the caption destination policy")
    bottom = destination["safeZones"]["bottom"]
    if bottom < 2:
        raise UnsupportedSafeZone("destination bottom exclusion band is absent or unmeasurable")
    return SafeZoneScope(canvas, canvas[1] - bottom, canvas[1])


def _unmeasured(label: str, status: str, reason: str) -> CheckResult:
    """Do not present failed/unavailable measurement as a detected visual defect."""
    return CheckResult(f"safe_zone_{label}", status, "unmeasured",
        f"{POLICY}; measurement unavailable: {reason[:300]}; no visual defect inferred")


def _measure(image: Image.Image, scope: SafeZoneScope) -> float:
    """Check and measure the same opened image without a second path read."""
    if image.size != scope.canvas:
        raise ValueError("review image dimensions differ from actual video canvas")
    density = edge_density_image(image, scope.top, scope.bottom, EDGE_STEP_THRESHOLD)
    if density is None or not math.isfinite(density) or not 0 <= density <= 1:
        raise ValueError("bottom band did not produce a finite nonempty measurement")
    return density


def _scan_frame(ref: FrameRef, scope: SafeZoneScope) -> CheckResult:
    """Treat read/geometry failure as failure; image detail itself only warns."""
    try:
        with Image.open(ref.path) as image:
            density = _measure(image, scope)
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        return _unmeasured(ref.label, FAIL, str(exc))
    pixels = (scope.canvas[0] - 1) * (scope.bottom - scope.top)
    measured = f"edge density {density:.3f}; pixels={pixels}"
    detail = (f"{POLICY}; canvas={scope.canvas[0]}x{scope.canvas[1]}; "
        f"band=[{scope.top},{scope.bottom}); warn >= {DANGER_EDGE_DENSITY_WARN}; "
        "detail heuristic, not OCR/collision/creative approval; confirm by eye")
    return CheckResult(f"safe_zone_{ref.label}",
        WARN if density >= DANGER_EDGE_DENSITY_WARN else PASS, measured, detail)


def scan_safe_zone(frames: list[FrameRef], plan: dict | None = None,
                   video: dict | None = None) -> list[CheckResult]:
    """Retain old callable seam but require geometry before any new PASS."""
    selected = [ref for ref in frames if ref.kind == "caption"]
    if not selected:
        return [_unmeasured("geometry", FAIL, "no required caption review frames")]
    if plan is None or video is None:
        return [_unmeasured("geometry", WARN, "legacy caller supplied no geometry")]
    try:
        scope = resolve_scope(plan, video)
    except UnsupportedSafeZone as exc:
        return [_unmeasured("geometry", WARN, str(exc))]
    except (KeyError, TypeError, ValueError) as exc:
        return [_unmeasured("geometry", FAIL, str(exc))]
    return [_scan_frame(ref, scope) for ref in selected]
