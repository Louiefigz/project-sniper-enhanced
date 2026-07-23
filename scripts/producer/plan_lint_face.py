#!/usr/bin/env python3
"""plan_lint_face — the face-aware placement lint pack (geometry contract v3 #6).

Plan-time checks for "the same disease in other organs": surfaces that place
content with NO face input on an operator whose normal framing is a 45-62%
face width. Every finding declares through the gate-policy layer
(:mod:`gate_policy`) and adapts into plan_lint's Report via
:func:`check_face_pack` — ``plan_lint.py`` dispatches.

* ``caption_face_band`` (a): ``captions.burn`` with a face-blind style
  (karaoke/line use the fixed ``CAPTION_LAYOUT_BY_ASPECT`` y_band with zero
  face input — ``captions_ass.py``) WARNs when the plan's ``faceBBoxNorm``
  bottom edge reaches into the band (captions-on-chin), with the overlap px.
  minimal/whisper are exempt (already face-relative). Burn on + face-blind
  style but no face data = SKIP-with-evidence, never silent.
* ``hook_card_face`` (b): titleCards place in the fixed ``HOOK_CARD.y_range``
  band with only a clamp (``captions/overlays.py``). WARNs per card window
  when the expanded face box (``free_space.expand_face`` on the plan's
  ``faceBBoxNorm`` — the hair-FALLBACK expansion; no measured hair exists at
  plan time) intersects the band.
* ``pip_hole_face_cx`` (c): a LIVE hole-comp entry
  (``graphics/pip_hole.entry_has_hole``) without a measured ``faceCx`` WARNs —
  the renderer reads ``entry["faceCx"]`` (``pip_hole.hole_clip_fields``) and
  silently defaults to 0.5 = frame center, not the face. THE STAMP: the brain
  calls :func:`stamp_face_cx` after authoring a hole entry; it measures faceCx
  from the faceBBoxNorm center and writes it onto the ENTRY — the key the
  renderer actually reads (the spec dict is never consulted for faceCx).
* ``graphic_broll_face_overlap`` (d): a face-anchored graphic window
  overlapping a ``brollTrack`` window FAILs — b-roll REPLACES the frames, so
  the face geometry the anchor assumes does not exist on screen.
* ``placement_content_bbox`` (e, plan-side half): an explicitly placed shorts
  entry with no measured ``contentBBox`` WARNs — the SAFE_BOX check
  (``plan_lint_motion._placed_box``) degenerates to the bare point. The GUI
  half ships in the editor: the preview's drag/scale commit stamps its
  measured content bbox onto the entry (``graphic-preview.tsx`` →
  ``use-editor-controller.usePlacementCommit``); entries placed through the
  properties panel's bare number fields (no preview measurement mounted) are
  exactly what this WARN catches.
"""

from __future__ import annotations

from typing import Any

import gate_policy
from gate_policy import Verdict
from graphics.pip_hole import entry_has_hole
# Reused validators — the same shape rules plan_lint_motion enforces, so the
# pack and the motion lint can never disagree on what a valid bbox is.
from plan_lint_motion import _valid_bbox, _valid_px_bbox
from planner.free_space import expand_face, norm_to_px
from producer_config import (CANVAS_BY_ASPECT, CAPTION_LAYOUT_BY_ASPECT,
                             HOOK_CARD, MODES, MOTION)

# The caption styles with zero face input (captions_ass fixed y_band);
# minimal/whisper anchor face-relative and are exempt.
_FACE_BLIND_STYLES = ("karaoke", "line")

gate_policy.register_gate("caption_face_band", "WARN")
gate_policy.register_gate("hook_card_face", "WARN")
gate_policy.register_gate("pip_hole_face_cx", "WARN")
gate_policy.register_gate("graphic_broll_face_overlap", "FAIL")
gate_policy.register_gate("placement_content_bbox", "WARN")


def _skip(gate: str, context: str, bbox: Any) -> list[Verdict]:
    """One SKIP-with-evidence verdict for a missing/malformed faceBBoxNorm.

    Args:
        gate: The declaring gate.
        context: What the plan is doing that makes the check applicable.
        bbox: The (invalid) faceBBoxNorm value found on the plan.

    Returns:
        A single-element verdict list.
    """
    why = "malformed" if bbox is not None else "missing"
    return [Verdict(gate, "SKIP",
                    f"{context} but the plan's faceBBoxNorm is {why} — the "
                    "face-geometry check cannot run; measure and stamp the "
                    "face box", lane="graphics" if gate != "caption_face_band"
                    else "captions")]


def check_caption_band(plan: dict) -> list[Verdict]:
    """(a) Karaoke/line caption band vs the face bottom edge.

    Args:
        plan: The edit plan.

    Returns:
        Verdicts (empty when burn is off, the style is face-aware, or the
        face clears the band).
    """
    preset = MODES.get((plan.get("target") or {}).get("mode"))
    if preset is None:
        return []
    cap = plan.get("captions") or {}
    if not cap.get("burn", preset["captions_burn"]):
        return []
    style = cap.get("style", preset["captions_style"])
    if style not in _FACE_BLIND_STYLES:
        return []
    bbox = plan.get("faceBBoxNorm")
    if not _valid_bbox(bbox):
        return _skip("caption_face_band",
                     f"captions burn with the face-blind {style!r} style", bbox)
    aspect = preset["aspect"]
    canvas_h = CANVAS_BY_ASPECT[aspect]["height"]
    top, bottom = CAPTION_LAYOUT_BY_ASPECT[aspect]["y_band"]
    offset = cap.get("bandYOffsetPx", 0)
    if isinstance(offset, (int, float)) and not isinstance(offset, bool):
        top, bottom = top - int(offset), bottom - int(offset)  # C12 up-shift
    face_bottom = (float(bbox[1]) + float(bbox[3])) * canvas_h
    overlap = min(face_bottom, bottom) - top
    if overlap <= 0:
        return []
    return [Verdict("caption_face_band", "WARN",
                    f"face bottom edge y={face_bottom:.0f}px reaches "
                    f"{overlap:.0f}px into the {style} caption band "
                    f"[{top},{bottom}] — the style is face-blind (captions_ass "
                    "fixed y_band), so captions land on the chin; use a "
                    "face-relative style (minimal/whisper) or shift the band "
                    "up via captions.bandYOffsetPx", lane="captions")]


def check_hook_cards(plan: dict) -> list[Verdict]:
    """(b) Expanded face box vs the fixed hook-card band, per card window.

    Args:
        plan: The edit plan.

    Returns:
        One WARN per title card while the face intersects the band; a SKIP
        when cards exist but no usable face box does.
    """
    cards = plan.get("titleCards") or []
    preset = MODES.get((plan.get("target") or {}).get("mode"))
    if not cards or preset is None:
        return []
    bbox = plan.get("faceBBoxNorm")
    if not _valid_bbox(bbox):
        return _skip("hook_card_face", f"plan has {len(cards)} titleCards in "
                     "the fixed hook band", bbox)
    canvas = CANVAS_BY_ASPECT[preset["aspect"]]
    face_px = norm_to_px(list(bbox), canvas["width"], canvas["height"])
    _, ey0, _, ey1 = expand_face(face_px)        # hair-FALLBACK expansion
    y_lo, y_hi = HOOK_CARD["y_range"]
    overlap = min(ey1, y_hi) - max(ey0, y_lo)
    if overlap <= 0:
        return []
    return [Verdict("hook_card_face", "WARN",
                    f"titleCards[{i}] window [{c.get('outStart')},"
                    f"{c.get('outEnd')}]: the expanded face box "
                    f"(y {ey0:.0f}-{ey1:.0f}px) overlaps the fixed hook band "
                    f"y [{y_lo},{y_hi}] by {overlap:.0f}px — overlays.py only "
                    "clamps inside the band and cannot avoid the face; "
                    "reframe, or drop/retime the card", lane="graphics")
            for i, c in enumerate(cards)]


def check_pip_hole_face_cx(plan: dict) -> list[Verdict]:
    """(c) Live hole-comp entries must carry a measured ``faceCx``.

    Args:
        plan: The edit plan.

    Returns:
        One WARN per live hole entry whose ``faceCx`` is absent.
    """
    out: list[Verdict] = []
    for i, g in enumerate(plan.get("graphicsTrack") or []):
        if not entry_has_hole(g) or g.get("faceCx") is not None:
            continue
        out.append(Verdict("pip_hole_face_cx", "WARN",
                           f"graphicsTrack[{i}] ({g.get('kind')}): pip-hole "
                           "entry has no measured faceCx — the renderer "
                           "defaults the face crop to 0.5 (frame center, "
                           "pip_hole.hole_clip_fields), which misses any "
                           "off-center speaker; measure + stamp it via "
                           "plan_lint_face.stamp_face_cx", lane="graphics"))
    return out


def _window(entry: dict) -> tuple[float, float]:
    """The entry's ``(outStart, outEnd)`` as floats (malformed → ``(-1, -1)``).

    Args:
        entry: Any windowed track entry.

    Returns:
        The float window; window-shape ERRORs remain the base lints' job.
    """
    try:
        return float(entry.get("outStart", -1)), float(entry.get("outEnd", -1))
    except (TypeError, ValueError):
        return -1.0, -1.0


def check_graphic_broll_overlap(plan: dict) -> list[Verdict]:
    """(d) Face-anchored graphics may not overlap b-roll windows.

    Args:
        plan: The edit plan.

    Returns:
        One FAIL per (face-anchored graphic, b-roll insert) window overlap.
    """
    broll = [(j, *_window(b)) for j, b in enumerate(plan.get("brollTrack") or [])]
    if not broll:
        return []
    out: list[Verdict] = []
    for i, g in enumerate(plan.get("graphicsTrack") or []):
        if g.get("anchor") not in MOTION["face_anchors"]:
            continue
        out.extend(_broll_conflicts((i, g), _window(g), broll))
    return out


def _broll_conflicts(entry: tuple[int, dict], window: tuple[float, float],
                     broll: list[tuple]) -> list[Verdict]:
    """FAIL verdicts for one face-anchored entry against every b-roll window.

    Args:
        entry: ``(index, graphics entry)``.
        window: The entry's ``(outStart, outEnd)``.
        broll: ``[(index, outStart, outEnd), ...]`` b-roll windows.

    Returns:
        One FAIL verdict per overlapping insert.
    """
    i, g = entry
    gs, ge = window
    out: list[Verdict] = []
    for j, bs, be in broll:
        if not (gs < be and bs < ge):
            continue
        out.append(Verdict("graphic_broll_face_overlap", "FAIL",
                           f"graphicsTrack[{i}] ({g.get('kind')}, anchor "
                           f"{g.get('anchor')!r}) window [{gs:g},{ge:g}] "
                           f"overlaps brollTrack[{j}] [{bs:g},{be:g}] — "
                           "b-roll REPLACES the frames, so the face this "
                           "anchor assumes is not on screen; retime the "
                           "graphic or the insert", lane="graphics"))
    return out


def check_placement_content_bbox(plan: dict) -> list[Verdict]:
    """(e, plan side) Placed shorts entries need a measured ``contentBBox``.

    Args:
        plan: The edit plan.

    Returns:
        One WARN per explicitly placed non-own-screen shorts entry whose
        ``contentBBox`` is absent/invalid (point-degenerate SAFE_BOX net).
    """
    if (plan.get("target") or {}).get("mode") != "short":
        return []
    out: list[Verdict] = []
    for i, g in enumerate(plan.get("graphicsTrack") or []):
        if g.get("placement") is None or g.get("anchor") == "own-screen":
            continue
        if _valid_px_bbox(g.get("contentBBox")):
            continue
        out.append(Verdict("placement_content_bbox", "WARN",
                           f"graphicsTrack[{i}] ({g.get('kind')}) carries an "
                           "explicit placement but no measured contentBBox — "
                           "the SAFE_BOX check degenerates to the bare point; "
                           "re-drag it in the editor (the commit stamps the "
                           "measured bbox) or author contentBBox "
                           "[x0,y0,x1,y1] comp px", lane="graphics"))
    return out


def stamp_face_cx(entry: dict, plan: dict) -> float:
    """Measure ``faceCx`` from the faceBBoxNorm center and stamp the ENTRY.

    The renderer reads ``entry["faceCx"]`` (``graphics/pip_hole.
    hole_clip_fields``) and silently defaults to 0.5 (frame center) when
    absent — so the brain calls THIS after authoring a pip-hole entry.
    Resolution: the entry's own ``faceBBoxNorm`` wins, else the plan's global
    one (the compositor's per-entry-first precedence).

    Args:
        entry: The graphicsTrack pip-hole entry (mutated in place).
        plan: The full plan (global ``faceBBoxNorm`` fallback).

    Returns:
        The stamped faceCx in ``[0, 1]``.

    Raises:
        ValueError: When neither the entry nor the plan carries a valid
            faceBBoxNorm — fail-closed, never stamp a guessed center.
    """
    bbox = entry.get("faceBBoxNorm") or plan.get("faceBBoxNorm")
    if not _valid_bbox(bbox):
        raise ValueError(
            "stamp_face_cx: no valid faceBBoxNorm on the entry or the plan — "
            "measure the face first; never stamp a guessed center")
    cx = min(max(float(bbox[0]) + float(bbox[2]) / 2.0, 0.0), 1.0)
    entry["faceCx"] = round(cx, 4)
    return entry["faceCx"]


def check_face_pack(plan: dict, rep: Any) -> None:
    """Run the whole pack; adapt verdicts through the gate-policy table.

    Blocking resolutions land in ``rep.errors``; advisories and labeled skips
    land in ``rep.warnings`` (``gate_policy.to_gate_json`` semantics).

    Args:
        plan: The edit plan (``target.mode`` already validated by the caller).
        rep: plan_lint's Report accumulator.
    """
    verdicts = (check_caption_band(plan) + check_hook_cards(plan)
                + check_pip_hole_face_cx(plan)
                + check_graphic_broll_overlap(plan)
                + check_placement_content_bbox(plan))
    if not verdicts:
        return
    resolved = gate_policy.to_gate_json(verdicts, plan.get("target") or {})
    for msg in resolved["errors"]:
        rep.error(msg)
    for msg in resolved["warnings"]:
        rep.warn(msg)
