#!/usr/bin/env python3
"""pip_hole — face-hole geometry for hole-comps (NATEHERK_STUDY.md §5 item 9).

A HOLE-COMP renders the FRAME around a transparent rounded PIP hole (the
canvas is masked out of the hole; only the card ring is drawn around it) and
the renderer keeps the live footage visible UNDER it: at composite time
``graphics_stage._overlay_clip`` crops the base to the hole's aspect (centred
on the face), scales it into the hole rect and overlays it BENEATH the comp —
the comp's rounded mask then covers the rectangle's corners, so the rounding
comes free from the comp's own alpha. This is the STATIC face-in-PIP takeover
the operator adjudicated LEGAL FOR LONGFORM (2026-07-10; still banned for
shorts — ``plan_lint_nateherk``). The eased shrink-to-PIP footage transform
remains §5 item 10 (``pip_takeover.py``, unwired).

GEOMETRY IS A CONTRACT: each entry's rect/radius MUST match the comp's CSS
hole exactly (the comp masks the canvas out of this rect; the renderer fills
it). Change a comp, change its entry — ``test_nateherk_longform`` pins both.

This module is pure geometry (unit-testable, no ffmpeg) except
:func:`hole_clip_fields`, which probes the base video's dims once.
"""

from __future__ import annotations

# rect = (x, y, w, h) on the 1920x1080 longform delivery canvas — measured
# from the reference (face PIP ~28%W x 89%H right, r~24: NATEHERK_STUDY §3).
# nateherk-takeover ALWAYS wears the hole; the scoreboard/pipeline/ledger-dark
# dark cards reserve the SAME right band [1344..1878] but only cut the hole +
# draw the ring when the spec opts in via ``presenterFrame`` (see
# ``entry_has_hole`` — the activation predicate every wire routes through).
HOLE_BY_KIND = {
    "nateherk-takeover": {"rect": (1344, 60, 534, 960), "radius": 24},
    "nateherk-scoreboard": {"rect": (1344, 60, 534, 960), "radius": 24},
    "nateherk-pipeline": {"rect": (1344, 60, 534, 960), "radius": 24},
    "nateherk-ledger-dark": {"rect": (1344, 60, 534, 960), "radius": 24},
}
PIP_HOLE_KINDS = tuple(HOLE_BY_KIND)
HOLE_CANVAS = (1920, 1080)
# nateherk-takeover has no opt-out — the hole IS the comp; every other
# registered kind is a plain opaque card until its spec sets presenterFrame.
_ALWAYS_HOLE_KIND = "nateherk-takeover"


def is_hole_kind(kind) -> bool:
    """True when ``kind`` names a registered hole-comp."""
    return str(kind) in HOLE_BY_KIND


def entry_has_hole(entry: dict) -> bool:
    """ACTIVATION predicate: is this entry's face hole live for THIS render?

    True iff the kind is registered AND either it is the always-hole
    ``nateherk-takeover`` or its ``spec.presenterFrame`` is truthy. This is the
    single source of truth every wire (format_for, graphics_stage, the two
    lints) keys on — so a scoreboard/pipeline/ledger-dark WITHOUT the opt-in
    behaves EXACTLY as before (opaque, free-band-legal, no own-screen gate),
    while an opted-in one becomes a framed presenter-container takeover.
    """
    kind = str(entry.get("kind", ""))
    if kind not in HOLE_BY_KIND:
        return False
    if kind == _ALWAYS_HOLE_KIND:
        return True
    return bool((entry.get("spec") or {}).get("presenterFrame"))


def hole_rect(kind: str) -> tuple[int, int, int, int]:
    """The hole's ``(x, y, w, h)`` on the delivery canvas (raises on unknown)."""
    if kind not in HOLE_BY_KIND:
        raise ValueError(f"unknown hole-comp kind {kind!r}: not in {PIP_HOLE_KINDS}")
    return HOLE_BY_KIND[kind]["rect"]


def delivery_hole_rect(kind: str, width: int, height: int) -> tuple[int, int, int, int]:
    """Scale the authored 1920x1080 hole to the actual delivery canvas."""
    base_w, base_h = HOLE_CANVAS
    if abs(width / height - base_w / base_h) > 0.002:
        raise ValueError(
            f"hole-comp '{kind}' needs a 16:9 delivery canvas; got {width}x{height}")
    x, y, w, h = hole_rect(kind)
    return (_even(x * width / base_w), _even(y * height / base_h),
            _even(w * width / base_w), _even(h * height / base_h))


def _even(v: float) -> int:
    """Nearest even integer (yuv420p needs even dims — pip_takeover twin)."""
    return int(round(v / 2.0)) * 2


def crop_for_hole(src_w: int, src_h: int, kind: str,
                  face_cx: float = 0.5) -> tuple[int, int, int, int]:
    """Largest hole-aspect crop of the source, centred on ``face_cx`` (0..1).

    The crop keeps the hole's aspect so the scale into the rect is
    distortion-free (± the even-dim quantisation, same as ``pip_takeover``).
    x tracks the face fraction, clamped inside the frame; y is centred.
    FAILS LOUDLY on a portrait source — the face-hole lane is longform-only
    (a shorts base reaching here means the lint gate was bypassed).
    """
    if src_h > src_w:
        raise ValueError(
            f"hole-comp '{kind}' needs a landscape (longform) base; got "
            f"{src_w}x{src_h} — the face-in-PIP lane is banned for shorts")
    _, _, w, h = hole_rect(kind)
    aspect = w / h
    if src_w / src_h >= aspect:                    # wider than the hole -> crop width
        ch = _even(src_h)
        cw = min(_even(ch * aspect), _even(src_w))
    else:                                          # taller -> crop height
        cw = _even(src_w)
        ch = min(_even(cw / aspect), _even(src_h))
    cx = _even(min(max(face_cx * src_w - cw / 2.0, 0), src_w - cw))
    cy = _even(min(max(src_h / 2.0 - ch / 2.0, 0), src_h - ch))
    return cw, ch, cx, cy


def hole_clip_fields(entry: dict, video_in: str) -> dict:
    """The ``pipHole`` fields ``graphics_stage`` attaches to a hole-comp clip.

    ``{"crop": (cw, ch, cx, cy), "rect": (x, y, w, h)}`` — crop of the BASE
    (centred on the entry's optional ``faceCx``, default 0.5) scaled into the
    registered hole rect. Probes the base dims once; every invalid input
    raises (never a silent mis-fill).
    """
    from graphics.pip_takeover import probe_dims

    kind = str(entry.get("kind", ""))
    face_cx = entry.get("faceCx", 0.5)
    if isinstance(face_cx, bool) or not isinstance(face_cx, (int, float)) \
            or not 0.0 <= float(face_cx) <= 1.0:
        raise ValueError(f"{kind}: faceCx must be a number in [0,1]; got {face_cx!r}")
    src_w, src_h = probe_dims(video_in)
    crop = crop_for_hole(src_w, src_h, kind, float(face_cx))
    return {"crop": crop, "rect": delivery_hole_rect(kind, src_w, src_h)}
