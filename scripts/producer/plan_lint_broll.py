#!/usr/bin/env python3
"""plan_lint_broll — slip-cover b-roll lint (FAILURE_LEDGER.md LL-010).

The c0679 v3 showpiece shipped a 45.3-47.8s wide slip-cover cut from raw
122.0-124.5s — the INTER-TAKE GAP of an abandoned line ("...you have all of
these massive?" trails off at 122.33, the restart lands at 124.34). The
operator read it as "def an outtake" with a momentary AV desync (the visible
mouth speaks words that are not the underlying audio). ``edit/cover_select``
excludes such windows at PROPOSAL time, but nothing validated the PLAN's
actual ``brollTrack`` windows — a hand-authored or drifted window bypassed
the scorer entirely. This module closes that gap at the lint gate:

* SLIP-COVER DETECTION — a broll entry whose manifest asset path resolves to
  the same file as a manifest SOURCE is footage of the same take/speaker
  (the slip-cover move); library b-roll (screen recordings, receipts) is
  untouched.
* RETAKE EXCLUSION (ERROR) — the asset window ``[assetStart, assetStart +
  (outEnd - outStart)]`` must not overlap a ``retake_scan`` cut span padded
  by ``COVER_SELECT["retake_pad_s"]``: that footage is outtake material BY
  CONSTRUCTION (the same hard-exclude cover_select applies).
* LIP-FLAP (ERROR) — spoken words overlapping the asset window for more
  than ``COVER_SELECT["lip_flap_max_s"]`` seconds mean visibly mismatched
  mouth movement over the timeline audio — it reads as an AV-sync fault
  (measured on c0679: the real mux offset was a constant −15ms; the percept
  was 0.49s of wrong lips).

A slip-cover whose source transcript cannot be resolved gets a loud WARN
(never a silent skip); resolution follows the render.py convention —
``transcriptPath`` relative to the manifest file's dir (``manifest["_path"]``).
"""

from __future__ import annotations

import os
from typing import Any

from producer_config import (COVER_SELECT, MOTION, TREATMENTS,
                             TREATMENT_DEFAULT)


def _source_for_asset(manifest: dict, asset_id: str) -> dict | None:
    """The manifest SOURCE whose file the broll asset points at (else None)."""
    catalog = {b.get("id"): b for b in manifest.get("broll", [])}
    entry = catalog.get(asset_id)
    if not entry or not entry.get("path"):
        return None
    apath = os.path.realpath(str(entry["path"]))
    for src in manifest.get("sources", []):
        if src.get("path") and os.path.realpath(str(src["path"])) == apath:
            return src
    return None


def _transcript_path(manifest: dict, src: dict) -> str | None:
    """Absolute transcript path for a source (None when unresolvable)."""
    rel = src.get("transcriptPath") or src.get("transcript")
    if not rel:
        return None
    if not os.path.isabs(rel):
        base = manifest.get("_path")
        if not base:
            return None
        rel = os.path.join(os.path.dirname(os.path.abspath(base)), rel)
    return rel if os.path.isfile(rel) else None


def _speech_overlap_s(words: list[dict], s: float, e: float) -> float:
    """Seconds of ``[s, e]`` covered by spoken words (clamped union)."""
    from edit.cover_select import speech_share  # shared math, no drift
    return speech_share(words, s, e) * (e - s)


def _check_entry(tag: str, window: tuple[float, float],
                 ctx: tuple[list, list], rep: Any) -> None:
    """Retake + lip-flap rules for one slip-cover asset window."""
    a0, a1 = window
    retake_spans, words = ctx
    pad = COVER_SELECT["retake_pad_s"]
    for rs, re in retake_spans:
        if a0 < float(re) + pad and float(rs) - pad < a1:
            rep.error(
                f"{tag}: slip-cover asset window [{a0:.2f},{a1:.2f}]s "
                f"overlaps the retake cut span [{rs:.2f},{re:.2f}]s "
                f"(±{pad:g}s pad) — that footage is an outtake by "
                "construction (LL-010: re-pick via edit/cover_select.py)")
            break
    flap = _speech_overlap_s(words, a0, a1)
    if flap > COVER_SELECT["lip_flap_max_s"]:
        rep.error(
            f"{tag}: slip-cover asset window [{a0:.2f},{a1:.2f}]s shows "
            f"{flap:.2f}s of visible speech — the same speaker mouths words "
            "that are not the underlying audio, which reads as an AV-sync "
            f"error (LL-010: keep spoken overlap ≤ "
            f"{COVER_SELECT['lip_flap_max_s']:g}s; re-pick via "
            "edit/cover_select.py)")


def _focus_hold_band(op: Any) -> tuple | None:
    """The measured hold band for one parsed FocusOp (None = no band)."""
    cfg = MOTION["focus_ops"]
    return {"darken-surround": cfg["darken"]["hold_band_s"],
            "blur-surround": cfg["darken"]["hold_band_s"],
            "hue-shift-signed": cfg["hue_shift"]["hold_band_s"]}.get(op.op)


def check_focus_ops(plan: dict, rep: Any) -> None:
    """Image-focus operators on b-roll inserts (LIAM move 3; EC2 vocabulary).

    Hard shape/vocabulary/window rules run through the EXECUTOR's own
    validator (``broll.focus_ops.parse_ops`` — broll_insert parses the same
    way, no drift). Doctrine on top: the ops are EC2's produced-graphics
    vocabulary (EC1 uses zero), so a treatment whose graphics lane is off
    (clean-cut) may not carry them — ERROR; holds outside the measured bands
    WARN (legal, off-grammar).
    """
    from broll.focus_ops import parse_ops
    entries = [(i, b) for i, b in enumerate(plan.get("brollTrack") or [])
               if b.get("focusOps") is not None]
    if not entries:
        return
    treatment = (plan.get("target") or {}).get("treatment", TREATMENT_DEFAULT)
    flags = TREATMENTS.get(treatment, TREATMENTS[TREATMENT_DEFAULT])
    for i, b in entries:
        tag = f"brollTrack[{i}]"
        if not flags["graphics"]:
            rep.error(f"{tag}: focusOps under treatment {treatment!r} — the "
                      "image-focus vocabulary is part of the produced "
                      "graphics stack (EC2), not a clean cut")
            continue
        try:
            dur = float(b.get("outEnd", 0)) - float(b.get("outStart", 0))
            ops = parse_ops(b.get("focusOps"), max(0.0, dur))
        except (ValueError, TypeError) as exc:
            rep.error(f"{tag}: {exc}")
            continue
        for op in ops:
            band = _focus_hold_band(op)
            if band and not (band[0] <= op.hold_s <= band[1]):
                rep.warn(f"{tag}: {op.op} hold {op.hold_s:g}s outside the "
                         f"measured band [{band[0]},{band[1]}]s — legal but "
                         "off the measured grammar")


def check_slipcover(plan: dict, manifest: dict, rep: Any) -> None:
    """LL-010 — every slip-cover brollTrack window passes the cover excludes.

    Pure plan/manifest in, Report out. Transcript loading and retake_scan run
    lazily per source (rapidfuzz stays a deferred dependency, matching
    ``edit/cover_select``); an unresolvable transcript is a loud WARN.
    """
    cache: dict[str, tuple[list, list]] = {}
    for i, b in enumerate(plan.get("brollTrack") or []):
        tag = f"brollTrack[{i}]"
        src = _source_for_asset(manifest, str(b.get("assetId", "")))
        if src is None:
            continue                       # library b-roll — not a slip-cover
        try:
            a0 = float(b.get("assetStart", 0.0))
            dur = float(b["outEnd"]) - float(b["outStart"])
        except (KeyError, TypeError, ValueError):
            continue                       # window shape errors are plan_lint_overlays.check_broll's
        if dur <= 0:
            continue
        sid = str(src.get("id"))
        if sid not in cache:
            tpath = _transcript_path(manifest, src)
            if tpath is None:
                rep.warn(f"{tag}: slip-cover from source {sid!r} but its "
                         "transcript is unresolvable — the LL-010 retake/"
                         "lip-flap checks did NOT run (fix transcriptPath / "
                         "manifest _path)")
                cache[sid] = ([], None)    # warn once per source
                continue
            from edit.cover_select import _load_words, _retake_spans
            cache[sid] = (_retake_spans(tpath), _load_words(tpath))
        spans, words = cache[sid]
        if words is None:
            continue                       # already warned for this source
        _check_entry(tag, (a0, a0 + dur), (spans, words), rep)
