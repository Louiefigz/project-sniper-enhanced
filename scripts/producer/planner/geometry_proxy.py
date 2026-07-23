#!/usr/bin/env python3
"""geometry_proxy — proxy mezzanine + delivery-geometry composition (v3 A1).

The feasibility lint cannot predict ``face_track``'s crop analytically (the
face-vs-center decision is a knife-edge branch measured on the mezzanine with
a different detector than the free-map sampler), so this module renders a
DOWNSCALED proxy of the stage-1 mezzanine through the REAL ``cut_speed`` code
path (``CutSpeedOptions.proxy_scale`` — same trim/setpts/atempo/concat math,
smaller canvas) and runs the REAL ``motion/face_track.py`` on it (same
detector selection: YuNet when the vendored model exists). Face boxes sampled
on the proxy are then mapped source-frame → reframe crop → delivery canvas →
punch scale (via ``punch_in``'s pure mirrors), giving the lint the SAME
geometry render-time placement will measure — by construction, not by model.

Pure mapping math lives at the top (unit-tested without a video); the
cv2/ffmpeg observation primitives sit below and import lazily.
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from producer_config import GEOMETRY_FEASIBILITY  # noqa: E402
from motion.punch_in import (PunchWindow, parse_windows,  # noqa: E402
                             push_scale_at, ramp_scale_at)


# =========================================================================== #
# Pure geometry — proxy frame → crop → delivery canvas → punch.
# =========================================================================== #
@dataclass(frozen=True)
class DeliveryGeom:
    """One window's composed delivery-canvas face geometry.

    Attributes:
        face_px: Face box ``(x, y, w, h)`` px on the delivery canvas.
        hair_top: Mapped measured hair-top y (px), or ``None``.
        punch_scale: The max punch scale applied over the window (>= 1.0).
        crop_strategy: The reframe strategy face_track chose for the shot.
    """

    face_px: tuple
    hair_top: float | None
    punch_scale: float
    crop_strategy: str


def crop_to_delivery(rect: tuple, crop: dict, canvas: tuple) -> tuple:
    """Map a proxy-frame rect through the reframe crop to the delivery canvas.

    The reframe extracts the full-height window ``[cropX, cropX+cropWidth]``
    and scales it to the delivery canvas — exactly what ``motion/reframe.py``
    executes with the face_track window.

    Args:
        rect: ``(x, y, w, h)`` px in the proxy frame.
        crop: One face_track window dict (``cropX``, ``cropWidth``,
            ``frameHeight``).
        canvas: Delivery ``(width, height)``.

    Returns:
        ``(x, y, w, h)`` px on the delivery canvas.
    """
    sx = canvas[0] / float(crop["cropWidth"])
    sy = canvas[1] / float(crop["frameHeight"])
    x, y, w, h = rect
    return ((x - float(crop["cropX"])) * sx, y * sy, w * sx, h * sy)


def punch_rect(rect: tuple, scale: float, center: tuple) -> tuple:
    """Expand a delivery-canvas rect under a punch zoom about ``center``.

    A punch scales the frame by ``scale`` about the focal point, so every
    canvas point ``p`` maps to ``center + (p - center) * scale``.

    Args:
        rect: ``(x, y, w, h)`` px on the delivery canvas.
        scale: The punch's linear scale (1.0 = untouched).
        center: The punch focal point ``(cx, cy)`` px.

    Returns:
        The expanded ``(x, y, w, h)`` px rect.
    """
    x, y, w, h = rect
    cx, cy = center
    return (cx + (x - cx) * scale, cy + (y - cy) * scale, w * scale, h * scale)


def punch_scale_at(win: PunchWindow, t: float) -> float:
    """The linear scale ANY punch window holds at output time ``t``.

    The unified pure mirror over the three window families (v3 #3): the lint
    composes the punch layer host-side from exactly the math punch_in's
    ffmpeg expressions encode (``ramp_scale_at`` / ``push_scale_at`` are
    punch_in's own mirrors; static/bracket hold ``zoom`` constant in-window).
    """
    if not win.out_start <= t <= win.out_end:
        return 1.0
    if win.is_ramp:
        return ramp_scale_at(win, t)
    if win.is_push:
        return push_scale_at(win, t)
    return win.zoom          # static / bracket in-punch: constant hold


def max_punch(windows: list, out_start: float, out_end: float) -> tuple:
    """The max punch scale (and its focal point) overlapping a graphic window.

    Samples each overlapping punch window's pure scale mirror
    (:func:`punch_scale_at`) across the overlap — the exact
    math the ffmpeg expressions encode; sampling only bounds the eases.

    Args:
        windows: Validated :class:`~motion.punch_in.PunchWindow` list.
        out_start: Graphic window start (output s).
        out_end: Graphic window end (output s).

    Returns:
        ``(scale, (center_x_frac, center_y_frac))``; ``(1.0, (0.5, 0.5))``
        when no punch overlaps.
    """
    n = GEOMETRY_FEASIBILITY["punch_samples"]
    best, center = 1.0, (0.5, 0.5)
    for win in windows:
        lo, hi = max(out_start, win.out_start), min(out_end, win.out_end)
        if hi <= lo:
            continue
        for i in range(n):
            t = lo + (hi - lo) * i / max(1, n - 1)
            s = punch_scale_at(win, t)
            if s > best:
                best, center = s, (win.center_x, win.center_y)
    return best, center


def plan_punch_windows(plan: dict) -> list:
    """The plan's validated punch windows (rationale stripped), or ``[]``.

    Same parse the renderer's punch stage runs (``parse_windows``), so an
    invalid punchIns raises here exactly as it would at render.
    """
    wins = plan.get("punchIns") or []
    if not wins:
        return []
    return parse_windows([{k: v for k, v in w.items() if k != "rationale"}
                          for w in wins])


def compose_delivery_geometry(observation: tuple, crop: dict, punch: tuple,
                              canvas: tuple) -> DeliveryGeom:
    """Compose proxy observation × reframe crop × punch into delivery geometry.

    Args:
        observation: ``(face_px_proxy, hair_top_proxy | None)``.
        crop: One face_track window dict for the shot.
        punch: ``(scale, (cx_frac, cy_frac))`` from :func:`max_punch`.
        canvas: Delivery ``(width, height)``.

    Returns:
        The composed :class:`DeliveryGeom`.
    """
    face_proxy, hair_proxy = observation
    scale, (cxf, cyf) = punch
    center = (cxf * canvas[0], cyf * canvas[1])
    face = crop_to_delivery(face_proxy, crop, canvas)
    face = punch_rect(face, scale, center)
    hair = None
    if hair_proxy is not None:
        hair_d = hair_proxy * canvas[1] / float(crop["frameHeight"])
        hair = center[1] + (hair_d - center[1]) * scale
    return DeliveryGeom(face_px=face, hair_top=hair, punch_scale=scale,
                        crop_strategy=str(crop.get("strategy", "face")))


def crops_for_window(windows: list, out_start: float, out_end: float) -> list:
    """face_track windows overlapping a graphic window, deduped by crop.

    Args:
        windows: The face_track ``windows.json`` entry list.
        out_start: Graphic window start (output s).
        out_end: Graphic window end (output s).

    Returns:
        The distinct overlapping crop windows (worst case is checked per
        crop when a graphic spans a cut into a different framing).
    """
    seen: set = set()
    out: list = []
    for win in windows:
        if float(win["outEnd"]) <= out_start or float(win["outStart"]) >= out_end:
            continue
        key = (win["cropX"], win["cropWidth"])
        if key in seen:
            continue
        seen.add(key)
        out.append(win)
    return out


# =========================================================================== #
# Observation — the REAL renderer primitives (ffmpeg + cv2), imported lazily.
# =========================================================================== #
def render_proxy(plan: dict, manifest: dict, work_dir: str,
                 scale: float | None = None) -> dict:
    """Render the downscaled stage-1 proxy mezzanine via the REAL cut_speed.

    Args:
        plan: The full edit plan.
        manifest: The asset manifest (sourceId → path).
        work_dir: Working directory (proxy + parts land here).
        scale: Downscale factor (default ``GEOMETRY_FEASIBILITY['proxy_scale']``).

    Returns:
        ``{"path", "elapsedS", "scale"}``.

    Raises:
        RuntimeError: Propagated from cut_speed (missing sources, drift, …).
    """
    import contextlib
    import io

    from cut_speed import CutSpeedOptions, render_cut_speed_opts

    scale = scale if scale is not None else GEOMETRY_FEASIBILITY["proxy_scale"]
    out_path = os.path.join(work_dir, "proxy_mezzanine.mp4")
    parts_dir = os.path.join(work_dir, "proxy-parts")
    os.makedirs(parts_dir, exist_ok=True)
    started = time.monotonic()
    with contextlib.redirect_stdout(io.StringIO()):   # NDJSON stays out of the gate output
        render_cut_speed_opts(plan, manifest, out_path,
                              CutSpeedOptions(parts_dir, proxy_scale=scale))
    return {"path": out_path, "elapsedS": round(time.monotonic() - started, 2),
            "scale": scale}


def reframe_crop_windows(proxy_path: str, tmap) -> list:
    """The REAL face_track crop windows for the proxy mezzanine.

    Same module, same detector selection (YuNet when the vendored model
    exists), same face-vs-center branch — the render's predicate.

    Args:
        proxy_path: The proxy mezzanine path.
        tmap: The compiled :class:`~compile_timeline.TimelineMap`.

    Returns:
        The per-segment window dict list (``build_windows`` output).
    """
    from motion.face_track import build_windows

    return build_windows(proxy_path, tmap)


def observe_window(proxy_path: str, out_start: float, out_end: float) -> tuple:
    """Sample a graphic window on the proxy for the face box + hair top.

    Uses the REAL free-map sampler (``free_space_sample.sample_window`` +
    ``measure_hair_top``) so the lint's face/hair observation is the same
    measurement family render-time placement uses.

    Args:
        proxy_path: The proxy mezzanine path.
        out_start: Window start (output s).
        out_end: Window end (output s).

    Returns:
        ``(face_px | None, hair_top | None)`` in PROXY pixel coordinates.
    """
    from planner.free_space_sample import measure_hair_top, sample_window

    frames, face_px, _busy = sample_window(proxy_path, out_start, out_end)
    if face_px is None:
        return None, None
    hair = measure_hair_top(frames, face_px[0] + face_px[2] / 2.0,
                            face_px[1]) if frames else None
    return face_px, hair
