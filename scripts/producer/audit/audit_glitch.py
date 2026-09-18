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
  * FREEZE — ``freezedetect``: a measured frozen stretch (> 1.5s) ⇒ WARN.
    Livestream/screen-share content legitimately holds a static frame (a slide,
    a paused screen), so this is a heads-up for the human, not a hard failure.
    A closed span needs its ordered start/duration/end events; a start that
    never ends reached decode EOF and is reported beside any earlier spans.
  * FLASH — a single-frame luma spike (bright or dark) that its neighbours don't
    share ⇒ WARN. Usually a splice artefact; occasionally an intentional strobe,
    hence a heuristic-honest warning rather than a failure.

Unavailable or incomplete scans fail; they cannot report absence of a glitch.
Measurement + verdict live together here (like audit_checks); the thresholds are
this module's config. See docs/producer/PRODUCER_PLAN.md §5 (Audit B).
"""

from __future__ import annotations

import os
import math
import re
import sys
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audit.audit_checks import CheckResult, FAIL, PASS, WARN  # noqa: E402
from audit.audit_glitch_scan import GlitchScan, GlitchScanError, scan_glitch_filter, scan_luma_frames  # noqa: E402

BLACK_MIN_DUR = 0.2            # blackdetect minimum black run to report (s)
EDGE_MARGIN_S = 0.5            # black wholly inside this head/tail window is OK
FREEZE_MIN_DUR = 1.5          # freezedetect minimum frozen run to warn (s)
FREEZE_NOISE = "-60dB"        # freezedetect sensitivity
FLASH_LUMA_DELTA = 45.0       # per-frame YAVG jump (0-255) that reverts = flash

_NUMBER = r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?"
# Detector events are read ONLY from the filter's own av_log lines. Container
# metadata and the input path are echoed in the stream dump with indentation,
# so a crafted title/filename cannot inject or malform an event (review 2026-09-06).
# The anchor also means a color code in front of the prefix hides the event:
# scan_glitch_filter strips SGR codes first, and any escape byte that reaches
# these parsers is unparseable evidence, never "no event" (reviewer repro 2026-09-06).
_BLACK_LINE = "[blackdetect @ "
_FREEZE_LINE = "[freezedetect @ "
_BLACK_RE = re.compile(rf"^\[blackdetect @ [^\]]*\] black_start:({_NUMBER})\s+black_end:({_NUMBER})(?=\s|$)")
_FREEZE_EVENT_RE = re.compile(rf"^\[freezedetect @ [^\]]*\] lavfi\.freezedetect\.freeze_(start|duration|end):\s*({_NUMBER})\s*$")
# ffmpeg 8.0 prints freeze clocks with six decimal places (observed
# 1000.989974 / 2.5 / 1003.489974): three rounded values disagree by <=1.5e-6 s.
# 2 ms is far below one frame at any supported rate and never licenses a real
# contradiction.
FREEZE_LOG_ABS_TOL_S = 0.002


def _unmeasured(name: str, error: GlitchScanError) -> CheckResult:
    """An unavailable scan is a mechanical failure, not absence of a glitch."""
    return CheckResult(name, FAIL, "unmeasured", str(error)[:1000])


ALLOW_SLACK_S = 0.25           # black run inside an allowed window, +/- this


def _plain_lines(output: str) -> list[str]:
    """Detector log lines split on newline only (after CR normalization).

    ``str.splitlines`` also breaks on U+2028/U+2029/NEL/VT/FF, so a crafted title
    could START a line with an anchored prefix. Such a forgery can only add a
    failing span (never hide one), but the anchor should not be reachable at all.
    An escape byte would let a prefixed event dodge the anchor entirely.
    """
    if "\x1b" in output:
        raise GlitchScanError("detector log carries escape sequences; events cannot be anchored")
    return output.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _note_scan(result: CheckResult, scan: GlitchScan) -> CheckResult:
    """Stripped color codes are declared on the report row, never hidden."""
    if not scan.ansi_stripped:
        return result
    return replace(result, detail=f"{result.detail}; ansiStripped: true")


def _black_spans(output: str) -> list[tuple[float, float]]:
    """Malformed detector events cannot disappear into a no-black verdict."""
    spans: list[tuple[float, float]] = []
    for line in _plain_lines(output):
        if not line.startswith(_BLACK_LINE):
            continue
        match = _BLACK_RE.match(line)
        if match is None:
            raise GlitchScanError("black interval is malformed")
        start, end = float(match[1]), float(match[2])
        if not math.isfinite(start) or not math.isfinite(end) or end <= start:
            raise GlitchScanError("black interval is not finite and increasing")
        spans.append((start, end))
    return spans


def detect_black(final_path: str, duration: float,
                 allow: "list[tuple[float, float]] | None" = None) -> CheckResult:
    """FAIL on any black run (> BLACK_MIN_DUR) in the body; head/tail fades OK.

    ``allow`` windows (plan-declared own-screen takeovers — a dark quote world
    IS near-black by design) demote a fully-contained run to WARN: intentional,
    but still surfaced for the eye pass (v3 intro finding, 2026-07-06).
    """
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        return _unmeasured("glitch_black", GlitchScanError("positive video duration required"))
    try:
        scan = scan_glitch_filter(final_path, f"blackdetect=d={BLACK_MIN_DUR}:pic_th=0.98", duration)
        spans = _black_spans(scan.stderr)
    except GlitchScanError as error:
        return _unmeasured("glitch_black", error)
    return _note_scan(_black_verdict(spans, duration, allow), scan)


def _black_verdict(spans: list[tuple[float, float]], duration: float,
                   allow: "list[tuple[float, float]] | None") -> CheckResult:
    """Body runs FAIL, runs inside declared takeovers WARN, head/tail fades pass."""
    body: list[str] = []
    allowed: list[str] = []
    for start, end in spans:
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


def _freeze_events(output: str) -> list[tuple[str, float]]:
    """Every freeze line is an event; a malformed one cannot be skipped."""
    events: list[tuple[str, float]] = []
    for line in _plain_lines(output):
        if not line.startswith(_FREEZE_LINE):
            continue
        match = _FREEZE_EVENT_RE.match(line)
        if match is None or not math.isfinite(float(match[2])):
            raise GlitchScanError("freeze event is malformed or not finite")
        events.append((match[1], float(match[2])))
    return events


def _closed_freeze(triple: list[tuple[str, float]]) -> tuple[float, float]:
    """start/duration/end must agree within FFmpeg's rounded log precision."""
    if [kind for kind, _ in triple] != ["start", "duration", "end"]:
        raise GlitchScanError("freeze span is missing its duration or end")
    start, duration, end = (value for _, value in triple)
    if duration < FREEZE_MIN_DUR or end <= start or abs(end - (start + duration)) > FREEZE_LOG_ABS_TOL_S:
        raise GlitchScanError("freeze end contradicts its start and duration")
    return start, end


def _freeze_spans(output: str) -> tuple[list[tuple[float, float]], float | None]:
    """Ordered closed spans plus an optional start-only tail that reached decode EOF."""
    events = _freeze_events(output)
    spans: list[tuple[float, float]] = []
    floor = -math.inf
    index = 0
    while index < len(events):
        kind, start = events[index]
        if kind != "start" or start < floor:
            raise GlitchScanError("freeze events are out of order or do not begin with a start")
        if index == len(events) - 1:
            return spans, start
        spans.append(_closed_freeze(events[index:index + 3]))
        floor = spans[-1][1]
        index += 3
    return spans, None


def _freeze_partition(spans: list[tuple[float, float]],
                      allow: "list[tuple[float, float]] | None") -> tuple[list, list]:
    """Declared static holds (with slack) are planned; every other closed span is not."""
    planned = [span for span in spans if any(
        lower - ALLOW_SLACK_S <= span[0] and span[1] <= upper + ALLOW_SLACK_S
        for lower, upper in (allow or []))]
    return planned, [span for span in spans if span not in planned]


def _declared_to_end(tail: float, allow: "list[tuple[float, float]] | None",
                     duration: float | None) -> bool:
    """A start-only tail is authorable only when a declared hold covers it to the program end."""
    if duration is None or not isinstance(duration, (int, float)) or isinstance(duration, bool) \
            or not math.isfinite(duration) or duration <= 0:
        return False
    return any(lower - ALLOW_SLACK_S <= tail and duration <= upper + ALLOW_SLACK_S
               for lower, upper in (allow or []))


def _freeze_verdict(spans: list[tuple[float, float]], tail: float | None,
                    allow: "list[tuple[float, float]] | None", duration: float | None) -> CheckResult:
    """An EOF tail never hides earlier closed spans; only a declared hold to the end exempts it."""
    planned, unplanned = _freeze_partition(spans, allow)
    earlier = (f"; {len(unplanned)} earlier unplanned freeze(s), longest "
               f"{max(end - start for start, end in unplanned):.2f}s" if unplanned else "")
    earlier += f"; {len(planned)} declared hold(s)" if planned else ""
    if tail is not None and not _declared_to_end(tail, allow, duration):
        return CheckResult("glitch_freeze", WARN, f"freeze from {tail:.2f}s reaches decode EOF{earlier}",
                           "terminal end was not measured; no declared hold covers it to the program end — confirm by eye")
    if tail is not None and unplanned:
        longest = max(end - start for start, end in unplanned)
        return CheckResult("glitch_freeze", WARN, f"{len(unplanned)} freeze(s), longest {longest:.2f}s; "
                           f"declared hold from {tail:.2f}s to the program end", "screen-share/slide holds are legitimate — confirm by eye")
    if tail is not None:
        return CheckResult("glitch_freeze", PASS, f"declared hold from {tail:.2f}s reaches the program end{earlier}",
                           "plan-authorized static hold covering decode EOF")
    if not spans:
        return CheckResult("glitch_freeze", PASS, "no freeze", f"threshold {FREEZE_MIN_DUR}s")
    if not unplanned:
        shown = ", ".join(f"{start:.2f}-{end:.2f}s" for start, end in planned)
        return CheckResult("glitch_freeze", PASS, f"{len(planned)} declared hold(s): {shown}",
                           "plan-authorized static own-screen hold")
    longest = max(end - start for start, end in unplanned)
    return CheckResult("glitch_freeze", WARN,
                       f"{len(unplanned)} freeze(s), longest {longest:.2f}s ({len(planned)} declared)",
                       "screen-share/slide holds are legitimate — confirm by eye")


def detect_freeze(final_path: str, allow: "list[tuple[float, float]] | None" = None,
                  duration: float | None = None) -> CheckResult:
    """WARN on unplanned or EOF-reaching freezes; pass explicit designed static holds."""
    try:
        scan = scan_glitch_filter(final_path, f"freezedetect=n={FREEZE_NOISE}:d={FREEZE_MIN_DUR}", duration)
        spans, tail = _freeze_spans(scan.stderr)
    except GlitchScanError as error:
        return _unmeasured("glitch_freeze", error)
    return _note_scan(_freeze_verdict(spans, tail, allow, duration), scan)


def _frame_luma(final_path: str, duration: float | None) -> list[tuple[float, float]]:
    """Per-frame (pts_time, YAVG 0-255) via signalstats, in decode order."""
    return scan_luma_frames(final_path, duration)


def detect_flash(final_path: str, duration: float | None = None) -> CheckResult:
    """WARN on single-frame luma spikes that revert (bad-splice flash frames)."""
    try:
        series = _frame_luma(final_path, duration)
    except GlitchScanError as error:
        return _unmeasured("glitch_flash", error)
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
    # Flash reads luma from the private metadata sink, never from detector log
    # lines, so there is no stripped-code note to carry on this row.
    return CheckResult("glitch_flash", PASS, "no flash frames",
                       f"delta threshold {FLASH_LUMA_DELTA}")


def check_glitch_screens(final_path: str, duration: float,
                         allow_black: "list[tuple[float, float]] | None" = None,
                         allow_freeze: "list[tuple[float, float]] | None" = None,
                         ) -> list[CheckResult]:
    """All three screen-integrity checks for one render output."""
    return [detect_black(final_path, duration, allow_black),
            detect_freeze(final_path, allow_freeze, duration), detect_flash(final_path, duration)]
