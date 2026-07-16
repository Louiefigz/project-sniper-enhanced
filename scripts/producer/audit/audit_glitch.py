#!/usr/bin/env python3
"""audit_glitch — glitch-screen detection for Audit B (black / freeze / flash).

A render can conform on every codec/loudness metric and still ship a *visible*
glitch: a dropped-to-black segment, a frozen frame, or a one-frame flash from a
bad splice. Audit B's deterministic checks don't catch those, so this module
adds three ffmpeg-driven screen-integrity checks, wired in as ONE line in
``audit_render`` (the render.py chain stays untouched):

  * BLACK — ``blackdetect``: unexpected black (> ~0.2s) in the BODY of the video
    is a real defect ⇒ FAIL. Black inside the first/last 0.5s is a legitimate
    fade-in/out ⇒ allowed.
  * FREEZE — ``freezedetect``: a frozen stretch (> 1.5s) ⇒ WARN, never FAIL.
    Livestream/screen-share content legitimately holds a static frame (a slide,
    a paused screen), so this is a heads-up for the human, not a hard failure.
  * FLASH — a single-frame luma spike (bright or dark) that its neighbours don't
    share ⇒ WARN. Usually a splice artefact; occasionally an intentional strobe,
    hence a heuristic-honest warning rather than a failure.

Measurement + verdict live together here (like audit_checks); the thresholds are
this module's config. See docs/producer/PRODUCER_PLAN.md §5 (Audit B).
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audit.audit_checks import CheckResult, FAIL, PASS, WARN  # noqa: E402
from audit.audit_probe import run_ff  # noqa: E402

BLACK_MIN_DUR = 0.2            # blackdetect minimum black run to report (s)
EDGE_MARGIN_S = 0.5            # black wholly inside this head/tail window is OK
FREEZE_MIN_DUR = 1.5          # freezedetect minimum frozen run to warn (s)
FREEZE_NOISE = "-60dB"        # freezedetect sensitivity
FLASH_LUMA_DELTA = 45.0       # per-frame YAVG jump (0-255) that reverts = flash

_BLACK_RE = re.compile(
    r"black_start:(\d+(?:\.\d+)?)\s+black_end:(\d+(?:\.\d+)?)")
_FREEZE_START_RE = re.compile(r"freezedetect\.freeze_start:\s*(\d+(?:\.\d+)?)")
_FREEZE_DUR_RE = re.compile(r"freezedetect\.freeze_duration:\s*(\d+(?:\.\d+)?)")
_PTS_RE = re.compile(r"pts_time:(-?\d+(?:\.\d+)?)")
_YAVG_RE = re.compile(r"lavfi\.signalstats\.YAVG=(-?\d+(?:\.\d+)?)")


def _ff_output(cmd: list[str]) -> str:
    """Combined stderr+stdout of an ffmpeg run (blackdetect/freeze log to stderr;
    the signalstats metadata print goes to stdout). Reuses the sibling wrapper."""
    proc = run_ff(cmd)
    return proc.stderr + proc.stdout


ALLOW_SLACK_S = 0.25           # black run inside an allowed window, +/- this


def detect_black(final_path: str, duration: float,
                 allow: "list[tuple[float, float]] | None" = None) -> CheckResult:
    """FAIL on any black run (> BLACK_MIN_DUR) in the body; head/tail fades OK.

    ``allow`` windows (plan-declared own-screen takeovers — a dark quote world
    IS near-black by design) demote a fully-contained run to WARN: intentional,
    but still surfaced for the eye pass (v3 intro finding, 2026-07-06).
    """
    out = _ff_output(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", final_path,
         "-vf", f"blackdetect=d={BLACK_MIN_DUR}:pic_th=0.98", "-an",
         "-f", "null", "-"])
    body: list[str] = []
    allowed: list[str] = []
    for start, end in ((float(a), float(b)) for a, b in _BLACK_RE.findall(out)):
        if end <= EDGE_MARGIN_S or start >= duration - EDGE_MARGIN_S:
            continue
        span = f"{start:.2f}-{end:.2f}s"
        if any(a - ALLOW_SLACK_S <= start and end <= b + ALLOW_SLACK_S
               for a, b in (allow or [])):
            allowed.append(span)
        else:
            body.append(span)
    if body:
        return CheckResult("glitch_black", FAIL, f"{len(body)} run(s): "
                           f"{', '.join(body)}", "unexpected mid-video black")
    if allowed:
        return CheckResult("glitch_black", WARN,
                           f"{len(allowed)} run(s) inside declared takeovers: "
                           f"{', '.join(allowed)}",
                           "intentional dark takeover — confirm by eye")
    return CheckResult("glitch_black", PASS, "none in body",
                       f"head/tail <= {EDGE_MARGIN_S}s fades allowed")


def detect_freeze(final_path: str,
                  allow: "list[tuple[float, float]] | None" = None) -> CheckResult:
    """WARN on unplanned freezes; pass explicit designed static holds."""
    out = _ff_output(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", final_path,
         "-vf", f"freezedetect=n={FREEZE_NOISE}:d={FREEZE_MIN_DUR}", "-an",
         "-f", "null", "-"])
    starts = _FREEZE_START_RE.findall(out)
    durs = _FREEZE_DUR_RE.findall(out)
    spans = [(float(start), float(start) + float(duration))
             for start, duration in zip(starts, durs)]
    if not spans:
        return CheckResult("glitch_freeze", PASS, "no freeze",
                           f"threshold {FREEZE_MIN_DUR}s")
    planned = [span for span in spans if any(
        lower - ALLOW_SLACK_S <= span[0] and span[1] <= upper + ALLOW_SLACK_S
        for lower, upper in (allow or []))]
    unplanned = [span for span in spans if span not in planned]
    if not unplanned:
        shown = ", ".join(f"{start:.2f}-{end:.2f}s" for start, end in planned)
        return CheckResult("glitch_freeze", PASS,
                           f"{len(planned)} declared hold(s): {shown}",
                           "plan-authorized static own-screen hold")
    longest = max(end - start for start, end in unplanned)
    return CheckResult("glitch_freeze", WARN,
                       f"{len(unplanned)} freeze(s), longest {longest:.2f}s",
                       "screen-share/slide holds are legitimate — confirm by eye")


def _frame_luma(final_path: str) -> list[tuple[float, float]]:
    """Per-frame (pts_time, YAVG 0-255) via signalstats, in decode order."""
    out = _ff_output(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", final_path,
         "-vf", "signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-",
         "-an", "-f", "null", "-"])
    series: list[tuple[float, float]] = []
    pending_t: float | None = None
    for line in out.splitlines():
        pts = _PTS_RE.search(line)
        if pts:
            pending_t = float(pts.group(1))
            continue
        y = _YAVG_RE.search(line)
        if y and pending_t is not None:
            series.append((pending_t, float(y.group(1))))
            pending_t = None
    return series


def detect_flash(final_path: str) -> CheckResult:
    """WARN on single-frame luma spikes that revert (bad-splice flash frames)."""
    series = _frame_luma(final_path)
    flashes: list[str] = []
    for i in range(1, len(series) - 1):
        (_, prev), (t, cur), (_, nxt) = series[i - 1], series[i], series[i + 1]
        d_prev, d_next = cur - prev, cur - nxt
        reverts = abs(prev - nxt) < FLASH_LUMA_DELTA / 2.0
        spike = abs(d_prev) >= FLASH_LUMA_DELTA and abs(d_next) >= FLASH_LUMA_DELTA
        if spike and (d_prev > 0) == (d_next > 0) and reverts:
            flashes.append(f"{t:.2f}s")
    if flashes:
        shown = ", ".join(flashes[:5]) + (" …" if len(flashes) > 5 else "")
        return CheckResult("glitch_flash", WARN, f"{len(flashes)} flash(es): "
                           f"{shown}", f"single-frame luma jump >= {FLASH_LUMA_DELTA}")
    return CheckResult("glitch_flash", PASS, "no flash frames",
                       f"delta threshold {FLASH_LUMA_DELTA}")


def check_glitch_screens(final_path: str, duration: float,
                         allow_black: "list[tuple[float, float]] | None" = None,
                         allow_freeze: "list[tuple[float, float]] | None" = None,
                         ) -> list[CheckResult]:
    """All three screen-integrity checks for one render output."""
    return [detect_black(final_path, duration, allow_black),
            detect_freeze(final_path, allow_freeze), detect_flash(final_path)]
