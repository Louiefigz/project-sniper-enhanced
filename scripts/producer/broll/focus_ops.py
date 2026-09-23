#!/usr/bin/env python3
"""focus_ops — image-focus operators for b-roll inserts (CM-3).

Doctrine: docs/studies/EDITCRAFT_LESSONS.md §7.4. The operators belong to the
produced graphics stack, so the vocabulary is gated by treatment at the lint
gate; defaults and bands are Sniper design parameters. The operator set the
still-image b-roll lane applies ON TOP of an insert (screenshots/photos —
designed cards stay pixel-frozen, BROLL["still_drift_pct_per_s"] /
LESSON-017 own that split):

* HIGHLIGHT — translucent marker-colour LEFT-TO-RIGHT WIPE over a region,
  0.4s by default (a short key-number pass; up to 0.7s for a larger region).
  A two-stage highlight (number first, then the whole tile) is two ops.
* DARKEN-SURROUND — flat ~−25% luma on everything EXCEPT the focus region,
  applied within one frame (no ramp), hold ~1-2s.
* BLUR-SURROUND — the sibling: blur outside the sharp region, no dim.
* HUE-SHIFT-SIGNED — full-frame color fill, word-timed SIGNED semantics
  (``MOTION["hue_shift_semantics"]``): negative = RED, positive = YELLOW
  (~1.0s) then GREEN; ramped over ~233ms (7 frames @30fps), hold 0.8-4.5s.

Plan shape — a ``brollTrack`` entry gains an optional ``focusOps`` array,
times RELATIVE to the insert's ``outStart`` (comp-relative, like
``moduleLands``):

    {"assetId": "shot-1", "outStart": 40.0, "outEnd": 46.0,
     "focusOps": [
       {"op": "highlight", "region": [0.10, 0.34, 0.10, 0.06],
        "atS": 0.5, "holdS": 2.0, "wipeS": 0.4},
       {"op": "darken-surround", "region": [0.03, 0.25, 0.26, 0.24],
        "atS": 3.0, "holdS": 1.5},
       {"op": "hue-shift-signed", "sign": "negative", "atS": 4.8,
        "holdS": 1.0, "rampS": 0.233}]}

``parse_ops`` is the SINGLE validator — ``broll_insert`` parses through it
and ``plan_lint_broll.check_focus_ops`` calls the same function, so lint and
executor can never drift. All filters are 1:1 (drawbox/lutyuv/gblur/geq/
split+overlay), preserving broll_insert's exact-frame-count contract.
Thresholds/colors live in ``producer_config.MOTION["focus_ops"]``.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from producer_config import ENCODE, MOTION  # noqa: E402

CFG = MOTION["focus_ops"]
OPS = CFG["ops"]
REGION_OPS = ("highlight", "darken-surround", "blur-surround")
SIGNS = tuple(MOTION["hue_shift_semantics"])          # ("negative", "positive")
MIN_REGION_FRAC = 0.02        # a region thinner than 2% of the frame is a typo


@dataclass(frozen=True)
class FocusOp:
    """One resolved focus operator, times relative to the insert's outStart."""

    op: str
    at_s: float
    hold_s: float
    region: tuple | None = None      # (x, y, w, h) normalized 0..1
    sign: str = ""                   # hue-shift-signed only
    ramp_s: float = 0.0              # hue-shift-signed only
    wipe_s: float = 0.0              # highlight only

    @property
    def end_s(self) -> float:
        """The op's release instant (relative seconds)."""
        return self.at_s + self.hold_s


def _region(i: int, raw: object) -> tuple:
    """Validate a normalized [x, y, w, h] region (raises on bad input)."""
    ok = (isinstance(raw, (list, tuple)) and len(raw) == 4
          and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                  for v in raw))
    if not ok:
        raise ValueError(f"focusOps[{i}]: region must be [x,y,w,h] normalized")
    x, y, w, h = (float(v) for v in raw)
    if not (0.0 <= x and 0.0 <= y and w >= MIN_REGION_FRAC
            and h >= MIN_REGION_FRAC and x + w <= 1.0 and y + h <= 1.0):
        raise ValueError(f"focusOps[{i}]: region [{x},{y},{w},{h}] must sit "
                         f"inside the frame with w/h >= {MIN_REGION_FRAC}")
    return (x, y, w, h)


def _num(i: int, raw: object, key: str, lo: float = 0.0) -> float:
    """A finite number >= ``lo`` (raises otherwise)."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) \
            or float(raw) < lo:
        raise ValueError(f"focusOps[{i}]: {key} must be a number >= {lo:g} "
                         f"(got {raw!r})")
    return float(raw)


def _one_op(i: int, raw: dict, insert_dur: float) -> FocusOp:
    """Validate one raw focusOps entry (raises ValueError on bad input)."""
    if not isinstance(raw, dict):
        raise ValueError(f"focusOps[{i}] must be an object")
    op = raw.get("op")
    if op not in OPS:
        raise ValueError(f"focusOps[{i}]: op {op!r} not in {OPS}")
    at = _num(i, raw.get("atS", 0.0), "atS")
    hold = _num(i, raw.get("holdS", -1.0), "holdS", lo=1e-3)
    if at + hold > insert_dur + 0.05:
        raise ValueError(f"focusOps[{i}]: atS {at:g} + holdS {hold:g} leaves "
                         f"the {insert_dur:.2f}s insert window")
    region = None
    if op in REGION_OPS:
        if "region" not in raw:
            raise ValueError(f"focusOps[{i}]: {op} requires a region")
        region = _region(i, raw["region"])
    sign, ramp, wipe = "", 0.0, 0.0
    if op == "hue-shift-signed":
        sign = raw.get("sign")
        if sign not in SIGNS:
            raise ValueError(f"focusOps[{i}]: sign {sign!r} not in {SIGNS} "
                             "(MOTION['hue_shift_semantics'])")
        ramp = _num(i, raw.get("rampS", CFG["hue_shift"]["ramp_s"]), "rampS")
    if op == "highlight":
        wipe = _num(i, raw.get("wipeS", CFG["highlight"]["wipe_s"]), "wipeS",
                    lo=1e-3)
    return FocusOp(op, at, hold, region, sign, ramp, wipe)


def parse_ops(raw: object, insert_dur: float) -> tuple[FocusOp, ...]:
    """Validate a raw ``focusOps`` array (None/absent → ()).

    Same-op entries may not overlap in time (a two-stage highlight is
    SEQUENTIAL passes); different ops may stack (highlight over a darken).
    """
    if raw is None:
        return ()
    if not isinstance(raw, list) or not raw:
        raise ValueError("focusOps must be a non-empty JSON array (or absent)")
    ops = tuple(_one_op(i, o, insert_dur) for i, o in enumerate(raw))
    by_kind: dict[str, list[FocusOp]] = {}
    for o in ops:
        by_kind.setdefault(o.op, []).append(o)
    for kind, group in by_kind.items():
        group.sort(key=lambda o: o.at_s)
        for a, b in zip(group, group[1:]):
            if b.at_s < a.end_s - 1e-6:
                raise ValueError(f"focusOps: two {kind!r} ops overlap "
                                 f"({a.at_s:g}+{a.hold_s:g}s then {b.at_s:g}s)"
                                 " — same-op passes are sequential")
    return ops


def _even(v: float) -> int:
    """Floor to even (yuv420 chroma alignment for crop/overlay offsets)."""
    return int(v) & ~1


def _px_region(op: FocusOp, w: int, h: int) -> tuple[int, int, int, int]:
    """Region → even-snapped pixel (x, y, w, h) on the insert frame."""
    x, y, rw, rh = op.region
    return (_even(x * w), _even(y * h),
            max(2, _even(rw * w)), max(2, _even(rh * h)))


# The wipe is quantized to this many width steps per second (the default
# 0.4s wipe at 30fps is 12 steps = one step per frame; 30/s reads as a
# continuous wipe at 24fps too).
_WIPE_STEPS_PER_S = 30
_WIPE_STEPS_MAX = 24


def _highlight(op: FocusOp, geom: tuple, t0: float,
               io: tuple[str, str]) -> list[str]:
    """Marker-yellow region wipe: drawbox width grows left→right over wipeS.

    ffmpeg's ``drawbox`` has NO time variable — its expressions are init-time
    only and ``t`` there means THICKNESS (the first build's ``clip((t-…))``
    silently drew the FULL box for the whole window; caught by the c0679
    both-ended verify, LL-017 sibling). The wipe is therefore a LADDER of
    static drawboxes, one per width step, each enable-gated to its slice of
    ``wipeS`` — per-frame growth at 30 steps/s, still 1:1.
    """
    hcfg = CFG["highlight"]
    rx, ry, rw, rh = _px_region(op, *geom)
    at, end = t0 + op.at_s, t0 + op.end_s
    steps = max(3, min(_WIPE_STEPS_MAX, round(op.wipe_s * _WIPE_STEPS_PER_S)))
    dt = op.wipe_s / steps
    boxes = []
    for k in range(1, steps + 1):
        w_k = max(2, round(rw * k / steps))
        s_k = at + (k - 1) * dt
        e_k = end if k == steps else at + k * dt    # last step holds to end
        boxes.append(f"drawbox=x={rx}:y={ry}:w={w_k}:h={rh}:"
                     f"color={hcfg['color']}@{hcfg['alpha']}:t=fill:"
                     f"enable='between(t,{s_k:.6f},{e_k:.6f})'")
    return [f"[{io[0]}]" + ",".join(boxes) + f"[{io[1]}]"]


def _surround(op: FocusOp, geom: tuple, t0: float,
              io: tuple[str, str]) -> list[str]:
    """Darken/blur everything OUTSIDE the focus region: treat the whole
    frame, then overlay the untouched region tile back (≤1-frame apply —
    both filters gate on the same enable window — an instant apply by
    design, no ramp)."""
    rx, ry, rw, rh = _px_region(op, *geom)
    at, end = t0 + op.at_s, t0 + op.end_s
    gate = f"enable='between(t,{at:.6f},{end:.6f})'"
    treat = (f"lutyuv=y='val*{CFG['darken']['luma_gain']}':{gate}"
             if op.op == "darken-surround"
             else f"gblur=sigma={CFG['blur']['sigma']}:{gate}")
    src, dst = io
    return [f"[{src}]split=2[{dst}fa][{dst}fb]",
            f"[{dst}fa]{treat}[{dst}dim]",
            f"[{dst}fb]crop={rw}:{rh}:{rx}:{ry}[{dst}tile]",
            f"[{dst}dim][{dst}tile]overlay=x={rx}:y={ry}:eof_action=pass:"
            f"{gate}[{dst}]"]


def _hue_uv(op: FocusOp, t0: float) -> tuple[str, str]:
    """The signed target chroma (U, V) expressions per hue_shift_semantics.

    Negative = constant red. Positive = yellow for the first ~1.0s
    (``positive_yellow_s``), then a quick lerp to green (the two-stage
    positive read, EDITCRAFT_LESSONS §7.4).
    NOTE: these land INSIDE ``geq`` expressions, whose time variable is the
    UPPERCASE ``T`` (lowercase ``t`` is only the timeline/enable evaluator's
    — ffmpeg 8 rejects it inside geq; caught by the c0679 both-ended verify).
    """
    uv = CFG["hue_shift"]["uv"]
    if op.sign == "negative":
        u, v = uv["red"]
        return f"{u:.1f}", f"{v:.1f}"
    (uy, vy), (ug, vg) = uv["yellow"], uv["green"]
    swap = t0 + op.at_s + CFG["hue_shift"]["positive_yellow_s"]
    prog = f"clip((T-{swap:.6f})/0.25,0,1)"
    return (f"({uy:.1f}+{ug - uy:.1f}*{prog})",
            f"({vy:.1f}+{vg - vy:.1f}*{prog})")


def _hue_shift(op: FocusOp, geom: tuple, t0: float,
               io: tuple[str, str]) -> list[str]:
    """Full-frame signed color fill: chroma mixes toward the signed target
    under a rampS attack envelope (instant when rampS=0), hard release.
    ``T`` (not ``t``) inside geq — see :func:`_hue_uv`."""
    at, end = t0 + op.at_s, t0 + op.end_s
    mix = CFG["hue_shift"]["mix"]
    env = (f"({mix}*clip((T-{at:.6f})/{op.ramp_s:.6f},0,1))"
           if op.ramp_s > 0 else f"{mix}")
    u, v = _hue_uv(op, t0)
    return [f"[{io[0]}]geq=lum='lum(X,Y)'"
            f":cb='cb(X,Y)+{env}*({u}-cb(X,Y))'"
            f":cr='cr(X,Y)+{env}*({v}-cr(X,Y))'"
            f":enable='between(t,{at:.6f},{end:.6f})'[{io[1]}]"]


_BUILDERS = {"highlight": _highlight, "darken-surround": _surround,
             "blur-surround": _surround, "hue-shift-signed": _hue_shift}


def branch_parts(ops: tuple, ctx: tuple, in_label: str,
                 out_label: str) -> list[str]:
    """Filter parts applying ``ops`` to one insert branch (all 1:1).

    ``ctx`` = (frame_w, frame_h, insert_out_start): the branch is already
    PTS-shifted onto the output clock, so every enable window is
    ``out_start + atS`` absolute. Ops chain sequentially in list order.

    The chain head PINS ``format=yuv420p``: with the branch's ``scale``
    upstream and ``overlay`` downstream, ffmpeg 8 negotiates the branch to
    yuva420p — and ``geq`` chroma expressions SILENTLY no-op on that alpha
    format (measured: the hue fill left UAVG/VAVG at 128 with zero errors;
    caught by the c0679 both-ended verify, minimal repro
    ``scale,geq[b];[0][b]overlay``). All ops are chroma-plane math on the
    pipeline's real yuv420p, so the pin restores exactly what the base
    carries; ``format`` is 1:1 (frame-count contract unchanged).
    """
    w, h, t0 = ctx
    fmt = f"{out_label}pin"
    parts: list[str] = [f"[{in_label}]format={ENCODE['pix_fmt']}[{fmt}]"]
    cur = fmt
    for j, op in enumerate(ops):
        nxt = out_label if j == len(ops) - 1 else f"{out_label}x{j}"
        parts += _BUILDERS[op.op](op, (w, h), t0, (cur, nxt))
        cur = nxt
    return parts
