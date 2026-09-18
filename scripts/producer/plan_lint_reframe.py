#!/usr/bin/env python3
"""plan_lint_reframe — reframe-section lint (called from plan_lint, mirrors _audio).

Validates ``plan.reframe`` against the LAYOUT CONTRACT (2026-07-09):

- ``layout``: "fill" (default when absent — today's behavior) | "split".
- ``crop``: [x,y,w,h] normalized 0-1 SOURCE rect — fill-mode manual override
  that wins over the automatic face crop. Scales to cover the 9:16 canvas,
  so it is shorts-only.
- ``split``: {"top": {"crop": [...], "frac": 0.5}, "bottom": {"crop": [...]}}
  — two crops of the same source vstacked to 1080x1920. 9:16 shorts ONLY
  (a 16:9 longform has no vertical canvas to stack into).
- ``track``: reserved for the v2 tracker; only ``false`` accepted in v1.

The executor's geometry lives in ``motion/reframe_split.py``; this gate keeps
a malformed plan from ever reaching it. Loud, specific messages — no silent
field-dropping (house rule: no fallback matching).
"""

from __future__ import annotations

from typing import Any

from producer_config import REFRAME_LAYOUTS, REFRAME_SPLIT, REFRAME_STRATEGIES


def _is_number(v: Any) -> bool:
    """True for int/float but NOT bool (True would pass isinstance checks)."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _check_crop(crop: Any, tag: str, rep: Any) -> None:
    """One [x,y,w,h] rect: 4 numbers in [0,1], w/h floor, inside the frame."""
    if (not isinstance(crop, (list, tuple)) or len(crop) != 4
            or not all(_is_number(v) for v in crop)):
        rep.error(f"{tag} must be [x,y,w,h] — 4 numbers normalized to [0,1] "
                  f"(got {crop!r})")
        return
    x, y, w, h = (float(v) for v in crop)
    lo = REFRAME_SPLIT["crop_min_frac"]
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        rep.error(f"{tag}: x/y must be in [0,1] (got x={x}, y={y})")
    if w < lo or h < lo:
        rep.error(f"{tag}: w/h must be >= {lo} of the source frame "
                  f"(got w={w}, h={h})")
    if x + w > 1.0 + 1e-9 or y + h > 1.0 + 1e-9:
        rep.error(f"{tag}: rect leaves the source frame "
                  f"(x+w={x + w:.3f}, y+h={y + h:.3f} must be <= 1)")


def _check_frac(top: dict, rep: Any) -> None:
    """split.top.frac — the top cell's share of output height, default 0.5."""
    frac = top.get("frac", REFRAME_SPLIT["frac_default"])
    lo, hi = REFRAME_SPLIT["frac_range"]
    if not _is_number(frac) or not (lo <= float(frac) <= hi):
        rep.error(f"reframe.split.top.frac must be a number in [{lo},{hi}] "
                  f"(got {frac!r})")


def _check_split_cells(split: dict, rep: Any) -> None:
    """Both cells must carry a valid crop; frac lives on top ONLY."""
    for cell in ("top", "bottom"):
        spec = split.get(cell)
        if not isinstance(spec, dict) or "crop" not in spec:
            rep.error(f"reframe.split.{cell} must be an object with a 'crop' "
                      f"rect (got {spec!r})")
            continue
        _check_crop(spec["crop"], f"reframe.split.{cell}.crop", rep)
    if isinstance(split.get("bottom"), dict) and "frac" in split["bottom"]:
        rep.error("reframe.split.bottom.frac is not a field — the bottom cell's "
                  "height is 1 - top.frac")
    if isinstance(split.get("top"), dict):
        _check_frac(split["top"], rep)


def _check_split_layout(reframe: dict, mode: str, rep: Any) -> None:
    """layout 'split': shorts-only, no strategy/crop, both cells required."""
    if mode != "short":
        rep.error("reframe.layout 'split' renders 9:16 shorts only — "
                  "not applicable to 16:9/longform")
    if "strategy" in reframe:
        rep.error("reframe.strategy does not apply to layout 'split' — remove "
                  "it (split defines its own geometry, face_track is skipped)")
    if "crop" in reframe:
        rep.error("reframe.crop is the fill-layout override — layout 'split' "
                  "takes split.top/bottom crops instead")
    split = reframe.get("split")
    if not isinstance(split, dict) or not {"top", "bottom"} <= set(split):
        rep.error("reframe.layout 'split' requires reframe.split with BOTH "
                  f"'top' and 'bottom' cells (got {split!r})")
        return
    extras = sorted(set(split) - {"top", "bottom"})
    if extras:
        rep.error(f"reframe.split has unknown cells {extras} — only 'top' "
                  "and 'bottom' exist")
    _check_split_cells(split, rep)


def _check_fill_layout(reframe: dict, mode: str, preset: dict, rep: Any) -> None:
    """layout 'fill' (or absent): the original strategy rules + crop override."""
    if "split" in reframe:
        rep.error("reframe.split requires reframe.layout 'split' "
                  "(layout is 'fill')")
    strategy = reframe.get("strategy", preset["reframe_default"])
    if strategy not in REFRAME_STRATEGIES:
        rep.error(f"reframe.strategy {strategy!r} not in {REFRAME_STRATEGIES}")
    elif mode == "short" and strategy == "none":
        # Edge X15: a 16:9 short would get 1080x1920-authored captions
        # rescaled wrong. Shorts must produce a 9:16 canvas.
        rep.error("short mode requires a 9:16 reframe strategy "
                  "(face|center|blurpad), not 'none'")
    if "crop" not in reframe:
        return
    _check_crop(reframe["crop"], "reframe.crop", rep)
    if mode != "short":
        rep.error("reframe.crop scales to cover the 9:16 shorts canvas — "
                  "not applicable to longform/16:9")
    if reframe.get("strategy") in ("center", "blurpad"):
        rep.warn(f"reframe.crop overrides strategy {reframe['strategy']!r} "
                 "(the manual crop wins over any strategy)")


def check_reframe(plan: dict, preset: dict, rep: Any) -> None:
    """Validate plan.reframe: layout enum, track guard, then per-layout rules."""
    reframe = plan.get("reframe") or {}
    if not isinstance(reframe, dict):
        rep.error(f"reframe must be an object, got {reframe!r}")
        return
    mode = (plan.get("target") or {}).get("mode", "")
    if ("crop" in reframe or "split" in reframe) and plan.get("baselineLook"):
        # V1: fail loud, don't transform — render.py runs baseline_stage
        # (chest-up recrop) BEFORE reframe_stage, so a rect drawn on the raw
        # source frame would land on the wrong pixels.
        rep.error("manual reframe crops are drawn on the raw source frame; "
                  "baselineLook re-frames the footage before reframe — remove "
                  "baselineLook or the manual crop (coordinate transform not "
                  "yet supported)")
    if "track" in reframe and reframe["track"] is not False:
        rep.error("reframe.track: tracker not yet wired — only false accepted "
                  f"in v1 (got {reframe['track']!r})")
    layout = reframe.get("layout", "fill")
    if layout not in REFRAME_LAYOUTS:
        rep.error(f"reframe.layout {layout!r} not in {REFRAME_LAYOUTS}")
        return
    if layout == "split":
        _check_split_layout(reframe, mode, rep)
    else:
        _check_fill_layout(reframe, mode, preset, rep)
