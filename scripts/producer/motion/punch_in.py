#!/usr/bin/env python3
"""punch_in — the ZOOM engine: static punches, animated ramps, in→out brackets.

Research (LONGFORM_VISUAL_STUDY.md, 2026-07-05): a professionally-edited long-form
lays a SECOND, semantic zoom track under the cuts. This stage bakes it. It takes a
rendered clip plus a list of output-time windows and applies, per window, one of
three moves — each a DEPARTURE from the preserved-wide baseline (scale 1.0) that
resolves back to it (study Rule 5):

* STATIC punch — a constant scale-up held across the window, snapping in/out
  INSTANTLY at the edges (that hard in/out is what pairs with a jump cut). A jump
  cut reads as intentional when the reframe ALSO changes; the cheap universal way
  is a subtle scale-up (study Rule 1 punch-in, Rule 2 punch-out).
* Animated RAMP — a gradual push/pull WITHIN the window at a constant rate
  (``ramp: {direction: "in"|"out", ratePctPerS}``), for the near-imperceptible
  creep that puts tension under a story (study Rule 4). Rendered with a per-frame
  ``scale=eval=frame`` zoom expression, NOT ``zoompan`` (whose integer x/y snap
  jitters); a static punch stays a hard instant reframe, never a Ken-Burns drift.
  A ramp RECOMPOSES toward its ``centerX``/``centerY`` target as it scales
  (INTRO_MACHINE_VS_PRO_AUDIT.md §4 / study R16: the pro's +43.8%/24.9s push
  carried a −413/−286px @1080p translation vector — the zoom recomposes toward
  the face, never scales about a fixed center), and its scale trajectory takes
  an optional ``ease`` ("linear" default, "smooth" = smoothstep).
* In→out BRACKET — ``bracket: true, holdS`` — the signature move (study Rule 3):
  a punch-IN held for ``holdS`` then a punch-OUT that resolves to wide. It is TWO
  steps from one entry: the rendered in-punch ``[outStart, outStart+holdS]`` and
  the release to baseline that follows (the overlay disabling AT ``outStart+holdS``
  IS the punch-out — the base is wide, so there is nothing to overlay after).

How it renders: each distinct static (zoom, center) setting gets ONE scaled copy
of the whole clip (scale ↑ then centre-crop back), and each ramp gets its own
per-frame-scaled branch; every copy is overlaid on the untouched base ONLY inside
its windows via ``overlay=enable='between(t,s,e)'``. Overlay keeps the base's
frame count and timing exactly — so the output preserves the input frame count
(±1), the SAME assertion for static and ramped windows alike. Video is re-encoded
at mezzanine quality (CRF 12, same intermediate spec as cut_speed); audio is
stream-copied.

CLI:
    punch_in.py <in.mp4> <out.mp4> --windows <windows.json | inline-json>
where each window is one of:
    static:  ``{"outStart": s, "outEnd": e, "zoom": 1.08, "centerX"?, "centerY"?}``
    ramp:    ``{"outStart": s, "outEnd": e, "ramp": {"direction": "in"|"out",
                "ratePctPerS": 0.8}, "centerX"?, "centerY"?, "ease"?}``
    push:    ``{"outStart": s, "outEnd": e, "zoom": 1.20, "attackS": 0.5,
                "releaseS"?: 0.4, "centerX"?, "centerY"?}`` — an eased-ATTACK
                punch: smoothstep 1.0→zoom over attackS, then HOLD at zoom (a
                mid-shot push-in that does not snap; grammar G6 keeps hard
                steps for cuts only). Optional ``releaseS`` eases the HOLD back
                to the wide baseline over the LAST releaseS of the window
                (smoothstep zoom→1.0), so the overlay disable at outEnd is
                seamless — a push without it POPS back to wide, which the
                longform smooth grammar forbids off-seam (defect report
                2026-07-10 §3). role:"recompose" windows (motion/recompose.py)
                are pushes with both edges eased.
    bracket: ``{"outStart": s, "outEnd": e, "zoom": 1.25, "bracket": true,
                "holdS": 2.0, "centerX"?, "centerY"?}``
(centerX/Y are 0..1 fractions of the frame on EVERY window type, default 0.5 =
centred; a ramp's crop window tracks its center as the scale grows, so a
push-in recomposes toward that point. ``ease`` — ramps only — is "linear"
(default, the pre-R16 behavior) or "smooth" (smoothstep of the scale
trajectory).) Magnitudes are validated against a hard-safety range; the editorial
bands (punch 1.05-1.25, bracket ceiling 1.51, ramp 0.3-1.8%/s) live in
producer_config.MOTION (``punch_in`` + ``zoom``) and are enforced by the plan lint.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from producer_config import ENCODE  # noqa: E402

# Hard-safety magnitude ranges for the PRIMITIVE (wider than the editorial
# doctrine bands in MOTION, which the plan lint enforces). Below scale 1.0 we
# would have to pad rather than crop; the study's biggest bracket reached 1.51,
# so the hard ceiling clears it with a little headroom.
ZOOM_MIN_HARD = 1.0
ZOOM_MAX_HARD = 1.55
DEFAULT_ZOOM = 1.08          # a subtle, broadly-safe punch when none is given
# Ramp rate hard band (%/s of linear scale). The editorial band (0.3-1.8%/s)
# lives in MOTION["zoom"]; this only rejects a nonsensical primitive input.
RAMP_RATE_HARD_MIN = 0.05
RAMP_RATE_HARD_MAX = 3.0
# Output-timeline frame tolerance for the preserve-count assertion. Overlay
# does not add/drop frames; ±1 only absorbs container/muxer rounding.
FRAME_TOL = 1


def emit(**fields) -> None:
    """One JSON status object per line on stdout (NDJSON, like the sibling stages)."""
    print(json.dumps(fields), flush=True)


def run_ff(cmd: list[str]) -> str:
    """Run an ffmpeg/ffprobe command; raise RuntimeError with the stderr tail."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        tail = (result.stderr or result.stdout).strip().splitlines()[-12:]
        raise RuntimeError("\n".join(tail) or f"{cmd[0]} failed")
    return result.stdout.strip()


def probe_dims(path: str) -> tuple[int, int]:
    """(width, height) of the first video stream (raises if there is none)."""
    out = run_ff(["ffprobe", "-v", "error", "-select_streams", "v:0",
                  "-show_entries", "stream=width,height", "-of", "json", path])
    streams = json.loads(out).get("streams", [])
    if not streams:
        raise RuntimeError(f"{path}: no video stream")
    return int(streams[0]["width"]), int(streams[0]["height"])


def probe_frames(path: str) -> int:
    """Exact video frame count via packet count (no decode) — the timeline
    length that matters, free of AAC padding that inflates format duration."""
    out = run_ff(["ffprobe", "-v", "error", "-select_streams", "v:0",
                  "-count_packets", "-show_entries", "stream=nb_read_packets",
                  "-of", "default=noprint_wrappers=1:nokey=1", path])
    return int(out.strip().splitlines()[0])


@dataclass(frozen=True)
class PunchWindow:
    """One output-time window and the zoom move to render across it.

    ``ramp_dir`` None = a STATIC punch held at ``zoom``; "in"/"out" = an animated
    ramp whose scale sweeps between the wide baseline and ``ramp_peak`` at a
    constant ``ramp_rate`` (scale-fraction per second), recomposing toward
    (``center_x``, ``center_y``) as it goes, with an ``ease`` on its trajectory
    (linear | smooth). ``origin`` records where the window came from
    (``bracket`` = the in-punch a bracket entry expanded to).
    """

    out_start: float
    out_end: float
    zoom: float = DEFAULT_ZOOM
    center_x: float = 0.5
    center_y: float = 0.5
    origin: str = "static"                 # static | bracket | ramp | push
    ramp_dir: str | None = None            # "in" | "out" (ramp only)
    ramp_rate: float = 0.0                 # scale-fraction per second (ramp only)
    ease: str = "linear"                   # "linear" | "smooth" (ramp only)
    attack_s: float = 0.0                  # >0 = an eased-ATTACK push (push only)
    release_s: float = 0.0                 # >0 = eased release tail (push only)

    @property
    def is_ramp(self) -> bool:
        """True for an animated rate-RAMP (a per-frame scale sweep)."""
        return self.ramp_dir is not None

    @property
    def is_push(self) -> bool:
        """True for an eased-ATTACK push: scale eases 1.0→``zoom`` over
        ``attack_s`` (smoothstep) then HOLDS at ``zoom`` — a mid-shot punch that
        pushes in smoothly instead of snapping (grammar G6: hard steps only on a
        cut). Rendered per-frame like a ramp, but target-zoom based, not rate."""
        return self.attack_s > 0.0 and self.ramp_dir is None

    @property
    def is_animated(self) -> bool:
        """True for any per-frame-scaled window (rate-ramp or eased-attack push)."""
        return self.is_ramp or self.is_push

    @property
    def key(self) -> tuple[float, float, float]:
        """Static windows sharing this key can share one scaled copy."""
        return (self.zoom, self.center_x, self.center_y)

    @property
    def ramp_peak(self) -> float:
        """The scale a ramp reaches at its far end (baseline is 1.0)."""
        return 1.0 + self.ramp_rate * (self.out_end - self.out_start)


def _even(v: float) -> int:
    """Floor to the nearest even integer (yuv420p needs even dims/offsets)."""
    return int(v) & ~1


def parse_windows(raw: object) -> list[PunchWindow]:
    """Validate a raw window list into ``PunchWindow``s (raises on bad input).

    Static, ramp (``ramp`` key) and bracket (``bracket`` key) entries are each
    validated against the primitive's hard ranges; a bracket expands to its
    rendered in-punch here (the release to wide is implicit). Windows may not
    overlap on the output timeline.
    """
    if not isinstance(raw, list) or not raw:
        raise ValueError("windows must be a non-empty JSON array")
    out: list[PunchWindow] = []
    for i, w in enumerate(raw):
        if not isinstance(w, dict):
            raise ValueError(f"window[{i}] must be an object")
        s, e = float(w["outStart"]), float(w["outEnd"])
        cx, cy = float(w.get("centerX", 0.5)), float(w.get("centerY", 0.5))
        if not (0.0 <= s < e):
            raise ValueError(f"window[{i}]: need 0 <= outStart < outEnd")
        if not (0.0 <= cx <= 1.0 and 0.0 <= cy <= 1.0):
            raise ValueError(f"window[{i}]: centerX/centerY must be in [0,1]")
        geom = (s, e, cx, cy)
        if w.get("bracket"):
            out.append(_bracket_window(i, w, geom))
        elif w.get("ramp") is not None:
            out.append(_ramp_window(i, w, geom))
        elif w.get("attackS") is not None:
            out.append(_push_window(i, w, geom))
        else:
            out.append(_static_window(i, w, geom))
    ordered = sorted(out, key=lambda w: w.out_start)
    for a, b in zip(ordered, ordered[1:]):
        if b.out_start < a.out_end - 1e-6:
            raise ValueError("punch-in windows overlap")
    return ordered


def _static_window(i: int, w: dict, geom: tuple) -> PunchWindow:
    """Validate a constant-zoom punch window (``geom`` = s, e, centerX, centerY)."""
    s, e, cx, cy = geom
    z = float(w.get("zoom", DEFAULT_ZOOM))
    if not (ZOOM_MIN_HARD <= z <= ZOOM_MAX_HARD):
        raise ValueError(f"window[{i}]: zoom {z} outside "
                         f"[{ZOOM_MIN_HARD},{ZOOM_MAX_HARD}]")
    return PunchWindow(s, e, z, cx, cy, "static")


def _bracket_window(i: int, w: dict, geom: tuple) -> PunchWindow:
    """Expand a bracket entry to its rendered in-punch ``[s, s+holdS]``.

    ``zoom`` is the in-punch magnitude; the punch-out is the overlay disabling at
    ``s+holdS`` (resolve to wide). ``holdS`` defaults to two-thirds of the window.
    """
    s, e, cx, cy = geom
    z = float(w.get("zoom", DEFAULT_ZOOM))
    if not (ZOOM_MIN_HARD <= z <= ZOOM_MAX_HARD):
        raise ValueError(f"window[{i}]: bracket zoom {z} outside "
                         f"[{ZOOM_MIN_HARD},{ZOOM_MAX_HARD}]")
    hold = float(w.get("holdS", (e - s) * 0.66))
    if not (0.0 < hold <= (e - s) + 1e-6):
        raise ValueError(f"window[{i}]: bracket holdS {hold} must be >0 and "
                         "<= the window duration")
    return PunchWindow(s, min(e, s + hold), z, cx, cy, "bracket")


def _ramp_window(i: int, w: dict, geom: tuple) -> PunchWindow:
    """Validate an animated ramp window (``ramp: {direction, ratePctPerS}``)."""
    s, e, cx, cy = geom
    ramp = w["ramp"]
    if not isinstance(ramp, dict):
        raise ValueError(f"window[{i}]: ramp must be an object")
    direction = ramp.get("direction")
    if direction not in ("in", "out"):
        raise ValueError(f"window[{i}]: ramp.direction must be 'in' or 'out'")
    rate_pct = float(ramp.get("ratePctPerS", 0.0))
    if not (RAMP_RATE_HARD_MIN <= rate_pct <= RAMP_RATE_HARD_MAX):
        raise ValueError(f"window[{i}]: ramp.ratePctPerS {rate_pct} outside hard "
                         f"[{RAMP_RATE_HARD_MIN},{RAMP_RATE_HARD_MAX}]")
    ease = w.get("ease", "linear")
    if ease not in ("linear", "smooth"):
        raise ValueError(f"window[{i}]: ease must be 'linear' or 'smooth'")
    win = PunchWindow(s, e, 1.0, cx, cy, "ramp", direction, rate_pct / 100.0, ease)
    if win.ramp_peak > ZOOM_MAX_HARD + 1e-6:
        raise ValueError(f"window[{i}]: ramp peak {win.ramp_peak:.3f} exceeds hard "
                         f"max {ZOOM_MAX_HARD} ({rate_pct}%/s over {e - s:.1f}s)")
    return win


def _push_window(i: int, w: dict, geom: tuple) -> PunchWindow:
    """Validate an eased-attack push (``attackS``): ease 1.0→``zoom`` then hold.

    A mid-shot punch that pushes in over ``attackS`` seconds (smoothstep) and holds
    at ``zoom`` for the rest of the window, recomposing toward centerX/centerY — the
    non-snapping punch the grammar wants off a cut (G6). ``attackS`` must be >0 and
    no longer than the window; the peak is a fixed ``zoom`` in the hard band.
    Optional ``releaseS`` eases the hold back to wide over the last releaseS of
    the window (attack + release must fit inside it)."""
    s, e, cx, cy = geom
    z = float(w.get("zoom", DEFAULT_ZOOM))
    if not (ZOOM_MIN_HARD <= z <= ZOOM_MAX_HARD):
        raise ValueError(f"window[{i}]: push zoom {z} outside "
                         f"[{ZOOM_MIN_HARD},{ZOOM_MAX_HARD}]")
    attack = float(w["attackS"])
    if not (0.0 < attack <= (e - s) + 1e-6):
        raise ValueError(f"window[{i}]: push attackS {attack} must be >0 and "
                         "<= the window duration")
    release = float(w.get("releaseS", 0.0))
    if release < 0.0 or attack + release > (e - s) + 1e-6:
        raise ValueError(f"window[{i}]: push releaseS {release} must be >=0 "
                         "with attackS + releaseS <= the window duration")
    return PunchWindow(s, e, z, cx, cy, "push", attack_s=attack,
                       release_s=release)


def _scaled_crop(width: int, height: int, win: PunchWindow) -> tuple[int, int, int, int]:
    """Scaled-up size + centre-crop offset for one (zoom, center) setting.

    Scale the frame to (W·z, H·z) then crop the original W×H back out, centred
    on the focal point — a static zoom-in with no drift. Dims/offsets snap even.
    """
    sw = max(width, _even(round(width * win.zoom)))
    sh = max(height, _even(round(height * win.zoom)))
    x = _even(min(max(win.center_x * sw - width / 2.0, 0), sw - width))
    y = _even(min(max(win.center_y * sh - height / 2.0, 0), sh - height))
    return sw, sh, x, y


def _eased(prog: float, ease: str) -> float:
    """Ease a ramp's 0..1 progress: linear passthrough or smoothstep.

    Smoothstep (``p²(3−2p)``) preserves both endpoints, so a smooth ramp still
    starts at the wide baseline and lands exactly on ``ramp_peak``.
    """
    if ease == "smooth":
        return prog * prog * (3.0 - 2.0 * prog)
    return prog


def ramp_scale_at(win: PunchWindow, t: float) -> float:
    """The linear scale a ramp holds at output time ``t`` — the math the ffmpeg
    ``scale=eval=frame`` expression encodes, as a pure Python mirror for
    host-side reasoning + tests. Baseline 1.0 at the near end, ``ramp_peak`` at
    the far end; ``out`` sweeps the other way (peak → baseline); ``ease``
    reshapes the trajectory between the endpoints."""
    span = win.out_end - win.out_start
    prog = 0.0 if span <= 0 else min(1.0, max(0.0, (t - win.out_start) / span))
    prog = _eased(prog, win.ease)
    sweep = (1.0 - prog) if win.ramp_dir == "out" else prog
    return 1.0 + win.ramp_rate * span * sweep


def _ramp_prog_expr(win: PunchWindow) -> str:
    """The eased 0..1 progress expression for a ramp (ffmpeg eval syntax)."""
    p = f"clip((t-{win.out_start:.6f})/{win.out_end - win.out_start:.6f},0,1)"
    if win.ease == "smooth":
        return f"({p}*{p}*(3-2*{p}))"
    return p


def _ramp_zoom_expr(win: PunchWindow) -> str:
    """The eased per-frame linear-scale expression ``z(t)`` for a ramp."""
    total = win.ramp_rate * (win.out_end - win.out_start)
    prog = _ramp_prog_expr(win)
    sweep = f"(1-{prog})" if win.ramp_dir == "out" else prog
    return f"(1+{total:.6f}*{sweep})"


def push_scale_at(win: PunchWindow, t: float) -> float:
    """The linear scale an eased-attack push holds at output time ``t`` — a pure
    Python mirror of :func:`_push_zoom_expr` for host-side reasoning + tests.
    Baseline 1.0 at the start, smoothstep up to ``zoom`` at ``attack_s``, held
    thereafter; with ``release_s`` the hold smoothsteps back to 1.0 over the
    last ``release_s`` of the window (so the overlay disable is seamless)."""
    prog = 0.0 if win.attack_s <= 0 else min(1.0, max(0.0,
                                             (t - win.out_start) / win.attack_s))
    prog = prog * prog * (3.0 - 2.0 * prog)
    if win.release_s > 0:
        rel = min(1.0, max(0.0, (t - (win.out_end - win.release_s))
                           / win.release_s))
        prog *= 1.0 - rel * rel * (3.0 - 2.0 * rel)
    return 1.0 + (win.zoom - 1.0) * prog


def _push_zoom_expr(win: PunchWindow) -> str:
    """The per-frame linear-scale expression ``z(t)`` for an eased-attack push:
    smoothstep 1.0→``zoom`` over ``attack_s``, a hold at ``zoom``, and (when
    ``release_s`` > 0) a smoothstep back to 1.0 over the window's last
    ``release_s`` — both edges eased, nothing pops."""
    p = f"clip((t-{win.out_start:.6f})/{win.attack_s:.6f},0,1)"
    prog = f"({p}*{p}*(3-2*{p}))"
    if win.release_s > 0:
        r = (f"clip((t-{win.out_end - win.release_s:.6f})"
             f"/{win.release_s:.6f},0,1)")
        prog = f"({prog}*(1-{r}*{r}*(3-2*{r})))"
    return f"(1+{win.zoom - 1.0:.6f}*{prog})"


def _anim_zoom_expr(win: PunchWindow) -> str:
    """Per-frame scale expression for either animated window kind."""
    return _push_zoom_expr(win) if win.is_push else _ramp_zoom_expr(win)


def _scaled_dim_expr(dim: int, z: str) -> str:
    """One scaled dimension: ``dim·z(t)`` snapped even, never below source."""
    return f"max({dim},trunc({dim}*{z}/2)*2)"


def _anim_scale_exprs(width: int, height: int, win: PunchWindow) -> tuple[str, str]:
    """Per-frame even width/height ``scale`` expressions for an animated window.

    The ffmpeg translation of :func:`ramp_scale_at` / :func:`push_scale_at`: the
    eased scale ``z(t)`` (a rate-ramp sweep or a push's attack-then-hold), clamped
    even and never below the source size. Commas live inside the single-quoted
    option value the caller emits, so ffmpeg does not read them as filter
    separators.
    """
    z = _anim_zoom_expr(win)
    return _scaled_dim_expr(width, z), _scaled_dim_expr(height, z)


def _anim_crop_exprs(width: int, height: int, win: PunchWindow) -> tuple[str, str]:
    """Per-frame crop x/y expressions steering an animated window toward its center.

    The crop window is centred on (center_x, center_y) of the SCALED frame, so
    the translation accumulates with the eased scale exactly like the pro's
    ramps (audit §4 / R16: the +43.8%/24.9s push carried ≈ −413/−286px @1080p;
    a fixed-center scale reads mechanical). The scaled dims are recomputed from
    ``t`` with the SAME closed form the scale branch uses — crop's ``in_w`` /
    ``in_h`` constants are frozen at the pre-zoom link config and never track
    the mid-stream growth ``scale=eval=frame`` produces (measured 2026-07-05:
    the old bare ``crop=W:H`` default "centred" crop resolved to a constant
    (0,0), silently anchoring every ramp top-left). Clamping pins the window
    inside the frame; at scale 1.0 it forces (0,0), the untouched wide baseline.
    """
    z = _anim_zoom_expr(win)
    sw, sh = _scaled_dim_expr(width, z), _scaled_dim_expr(height, z)
    x = f"clip({win.center_x:.6f}*{sw}-{width / 2.0:.1f},0,{sw}-{width})"
    y = f"clip({win.center_y:.6f}*{sh}-{height / 2.0:.1f},0,{sh}-{height})"
    return x, y


def build_filter(width: int, height: int, windows: list[PunchWindow]) -> str:
    """filter_complex: base + one copy per static setting and per animated window
    (ramp or push), each overlaid only inside its windows. Overlay preserves the
    base frame count."""
    statics = [w for w in windows if not w.is_animated]
    animated = [w for w in windows if w.is_animated]
    groups: dict[tuple, list[PunchWindow]] = {}
    for w in statics:
        groups.setdefault(w.key, []).append(w)
    n = len(groups) + len(animated)
    parts = [f"[0:v]setsar=1,split={n + 1}[base]"
             + "".join(f"[s{i}]" for i in range(n))]
    cur, idx = "base", 0
    for _, wins in groups.items():
        sw, sh, x, y = _scaled_crop(width, height, wins[0])
        parts.append(f"[s{idx}]scale={sw}:{sh},crop={width}:{height}:{x}:{y},"
                     f"setsar=1[z{idx}]")
        enable = "+".join(f"between(t,{w.out_start:.6f},{w.out_end:.6f})"
                          for w in wins)
        cur = _overlay(parts, cur, idx, enable)
        idx += 1
    for w in animated:
        wexpr, hexpr = _anim_scale_exprs(width, height, w)
        xexpr, yexpr = _anim_crop_exprs(width, height, w)
        parts.append(f"[s{idx}]scale=w='{wexpr}':h='{hexpr}':eval=frame,"
                     f"crop={width}:{height}:x='{xexpr}':y='{yexpr}',"
                     f"setsar=1[z{idx}]")
        cur = _overlay(parts, cur, idx,
                       f"between(t,{w.out_start:.6f},{w.out_end:.6f})")
        idx += 1
    parts.append(f"[{cur}]format={ENCODE['pix_fmt']}[vout]")
    return ";".join(parts)


def _overlay(parts: list[str], cur: str, idx: int, enable: str) -> str:
    """Append the overlay chaining ``z{idx}`` onto ``cur``; return the new label."""
    nxt = f"o{idx}"
    parts.append(f"[{cur}][z{idx}]overlay=enable='{enable}'[{nxt}]")
    return nxt


def apply_punch_ins(src_path: str, windows: list[PunchWindow],
                    out_path: str) -> dict:
    """Render ``src_path`` with the punch-in windows into ``out_path``.

    Video is re-encoded at mezzanine CRF; audio (if any) is stream-copied.
    Asserts the output frame count matches the input within ``FRAME_TOL``.
    """
    width, height = probe_dims(src_path)
    in_frames = probe_frames(src_path)
    fc = build_filter(width, height, windows)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-i", src_path, "-filter_complex", fc,
           "-map", "[vout]", "-map", "0:a?",
           "-c:v", "libx264", "-crf", str(ENCODE["mezzanine_crf"]),
           "-preset", ENCODE["mezzanine_preset"], "-pix_fmt", ENCODE["pix_fmt"],
           "-fps_mode", "passthrough", "-c:a", "copy",
           "-movflags", "+faststart", out_path]
    run_ff(cmd)
    out_frames = probe_frames(out_path)
    drift = abs(out_frames - in_frames)
    ramps = sum(1 for w in windows if w.is_ramp)
    pushes = sum(1 for w in windows if w.is_push)
    brackets = sum(1 for w in windows if w.origin == "bracket")
    result = {"width": width, "height": height, "windows": len(windows),
              "groups": len({w.key for w in windows if not w.is_animated}),
              "ramps": ramps, "pushes": pushes, "brackets": brackets,
              "inFrames": in_frames, "outFrames": out_frames, "driftFrames": drift}
    if drift > FRAME_TOL:
        raise RuntimeError(
            f"punch-in changed frame count: in {in_frames} -> out {out_frames} "
            f"(drift {drift} > {FRAME_TOL})")
    return result


def _load_windows(spec: str) -> object:
    """Windows are either a path to a JSON file or an inline JSON string."""
    if os.path.exists(spec):
        with open(spec) as f:
            return json.load(f)
    return json.loads(spec)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="PRODUCER zoom engine: static punches, animated ramps, "
                    "and in→out brackets (per output-time window)")
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--windows", required=True,
                    help="JSON file path OR inline JSON array of punch windows")
    args = ap.parse_args()
    try:
        windows = parse_windows(_load_windows(args.windows))
        emit(stage="punch_in", status="start", windows=len(windows))
        result = apply_punch_ins(args.src, windows, args.out)
        emit(stage="punch_in", status="done", **result)
        return 0
    except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
        emit(error=str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
