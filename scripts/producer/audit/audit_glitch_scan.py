"""Strict separate glitch scans; partial decode logs are not clean-video proof.

Every scan decodes ``0:v:0`` to EOF under ``-xerror``/``-err_detect explode`` and
reports completion through ``-progress pipe:1``. That progress writer is the ONLY
stdout writer. A per-frame ``metadata=print`` sink never shares the pipe: two
independently buffered avio writers on one fd tear lines at 32 KiB flush
boundaries (reproduced 2026-09-06: 46 torn lines in a 10,796-frame scan). The
sink is parsed as a stream, so its size never becomes a hidden runtime ceiling;
the explicit ceiling is ``MAX_LUMA_FRAMES``. The progress stream is parsed as
key=value blocks closed by ``progress=continue|end``; ``frame`` and
``out_time_us`` are read from the terminal ``progress=end`` block ALONE (it must
be last, complete and integer-valued), and that ``out_time_us`` binds the decoded
length to the audited duration, so a short video stream inside a longer container
cannot assert absence for the remainder.

ffmpeg runs with ``AV_LOG_FORCE_NOCOLOR=1`` because the detectors are read from
prefix-anchored av_log lines: a colored log hid every event behind an SGR code
and produced a false clean verdict (reviewer repro 2026-09-06). Color codes that
still reach the parser are stripped and declared as ``ansi_stripped``; any other
escape sequence is unparseable evidence and fails the scan.

The scan deadline scales with media length (measured 2026-09-06: signalstats
costs ~5.4 ms/frame at 1080p and ~21.6 ms/frame at 2160p on this host, i.e.
0.16–0.52 s per media second) and still respects any active run deadline
through ``process_timeout``; the shared ``run_ff`` semantics are untouched.
"""
from __future__ import annotations

import math
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Iterable, Optional

from headless.process_runner import process_timeout

MAX_LOG_BYTES = 16 * 1024 * 1024
MAX_LUMA_FRAMES = 400_000            # ~3.7 h at 30 fps; series memory ~50 MB
SCAN_BASE_S = 120.0                  # process start, probe, container open
SCAN_PER_MEDIA_SECOND = 1.0          # ~2x the measured 2160p signalstats cost
SCAN_UNKNOWN_DURATION_BUDGET_S = 900.0
SCAN_LENGTH_TOL_S = 0.5              # decoded length vs audited duration
_INT = re.compile(r"-?[0-9]+")
_NUMBER = r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?"
_LUMA_FRAME = re.compile(rf"^frame:\s*(\d+)\s+pts:\s*(-?\d+)\s+pts_time:({_NUMBER})\s*$")
_YAVG = re.compile(rf"^lavfi\.signalstats\.YAVG=({_NUMBER})\s*$")
_PROGRESS_STATES = ("continue", "end")
# ffmpeg's colorizer emits only SGR (ESC [ params m). The wider CSI grammar ends
# on any letter, so a stray "ESC [" before "[blackdetect" would swallow the
# prefix's first byte and demote a real event to an ignored line.
_SGR = re.compile(r"\x1b\[[0-?]*[ -/]*m")
_OPTION_SPECIALS = "\\':"
_GRAPH_SPECIALS = "\\'[],;"


class GlitchScanError(RuntimeError):
    """A detector cannot qualify incomplete or malformed scan evidence."""


@dataclass(frozen=True)
class GlitchScan:
    """Successful selected-video scan with independently observed EOF progress."""

    stderr: str
    stdout: str
    frames: int
    scanned_seconds: float = 0.0
    metadata: str = ""
    ansi_stripped: bool = False


def scan_budget_s(duration_s: Optional[float]) -> float:
    """Media-length-scaled deadline; an unknown length gets an explicit fixed class."""
    if duration_s is None or not math.isfinite(duration_s) or duration_s <= 0:
        return SCAN_UNKNOWN_DURATION_BUDGET_S
    return SCAN_BASE_S + SCAN_PER_MEDIA_SECOND * float(duration_s)


def scan_environment() -> dict[str, str]:
    """A copy of the process environment in which ffmpeg can never color its log."""
    env = dict(os.environ)
    env.pop("AV_LOG_FORCE_COLOR", None)
    env["AV_LOG_FORCE_NOCOLOR"] = "1"
    return env


def run_scan_process(command: list[str], budget_s: float) -> subprocess.CompletedProcess:
    """One ffmpeg scan under its scaled budget, still capped by any active run deadline."""
    return subprocess.run(command, capture_output=True, text=True, timeout=process_timeout(budget_s),
                          env=scan_environment())


def strip_ansi(text: str) -> tuple[str, bool]:
    """Remove SGR color codes; report whether any were present.

    Returns:
        The plain text and ``True`` when codes were stripped.

    Raises:
        GlitchScanError: an escape byte survives stripping (not a color code).
    """
    if "\x1b" not in text:
        return text, False
    plain = _SGR.sub("", text)
    if "\x1b" in plain:
        raise GlitchScanError("scan log carries escape sequences beyond color codes")
    return plain, True


def _progress_blocks(stdout: str) -> list[dict[str, str]]:
    """Split the ``-progress`` stream into key=value blocks, each closed by a progress state.

    The progress writer is the only stdout writer, so a non key=value line, a
    repeated key inside a block, an unknown state or keys after the last state
    are torn or foreign evidence, never something to skip.
    """
    blocks: list[dict[str, str]] = []
    block: dict[str, str] = {}
    for line in stdout.splitlines():
        key, separator, value = line.partition("=")
        if not separator or not key or key in block:
            raise GlitchScanError("malformed decode progress line")
        block[key] = value
        if key != "progress":
            continue
        if value not in _PROGRESS_STATES:
            raise GlitchScanError("unknown decode progress state")
        blocks.append(block)
        block = {}
    if block:
        raise GlitchScanError("decode progress keys outside a closed block")
    return blocks


def _block_int(block: dict[str, str], key: str) -> int:
    """A progress block's required integer key; absent or non-integer values are not measurements."""
    value = block.get(key)
    if value is None or _INT.fullmatch(value.strip()) is None:
        raise GlitchScanError(f"decode progress block lacks an integer {key}")
    return int(value)


def _completed_progress(stdout: str) -> tuple[int, float]:
    """Frame count and out_time come ONLY from the terminal ``progress=end`` block.

    That block must be last, every block must carry a non-decreasing integer
    ``frame``, and the terminal block must carry a positive integer ``out_time_us``.
    """
    blocks = _progress_blocks(stdout)
    states = [block["progress"] for block in blocks]
    if not states or states[-1] != "end" or any(state != "continue" for state in states[:-1]):
        raise GlitchScanError("no terminal decode progress block")
    frames = [_block_int(block, "frame") for block in blocks]
    if any(later < earlier for earlier, later in zip(frames, frames[1:])):
        raise GlitchScanError("conflicting decode progress")
    out_time = _block_int(blocks[-1], "out_time_us") / 1_000_000
    if frames[-1] <= 0 or out_time <= 0:
        raise GlitchScanError("no positive complete video decode")
    return frames[-1], out_time


def _scan_command(final_path: str, filters: str) -> list[str]:
    """Selected first video stream, no seek/trim/rate change, progress on stdout only."""
    return ["ffmpeg", "-hide_banner", "-nostats", "-xerror", "-err_detect", "explode",
            "-i", final_path, "-map", "0:v:0", "-vf", filters, "-an",
            "-fps_mode", "passthrough", "-progress", "pipe:1", "-f", "null", "-"]


def _run_scan(command: list[str], duration_s: Optional[float]) -> subprocess.CompletedProcess:
    """Nonzero exit, non-text logs, oversized logs or a dead process yield no measurements."""
    try:
        process = run_scan_process(command, scan_budget_s(duration_s))
    except (OSError, UnicodeError, subprocess.TimeoutExpired) as error:
        raise GlitchScanError(f"scan process unavailable: {type(error).__name__}") from error
    if process.returncode != 0:
        raise GlitchScanError(f"ffmpeg exited {process.returncode}; partial measurements rejected")
    if not isinstance(process.stdout, str) or not isinstance(process.stderr, str):
        raise GlitchScanError("scan logs are not text")
    if len(process.stdout.encode("utf8")) + len(process.stderr.encode("utf8")) > MAX_LOG_BYTES:
        raise GlitchScanError("scan log exceeds its evidence budget")
    return process


def _bind_length(scanned: float, duration_s: Optional[float]) -> None:
    """The decoded stream must span the audited timeline, not a shorter prefix."""
    if duration_s is None:
        return
    if not math.isfinite(duration_s) or abs(scanned - float(duration_s)) > SCAN_LENGTH_TOL_S:
        raise GlitchScanError(f"decoded video length {scanned:.3f}s differs from audited duration")


def scan_glitch_filter(final_path: str, filters: str,
                       duration_s: Optional[float] = None) -> GlitchScan:
    """Decode v:0 to EOF without resampling; errors produce no selectable evidence."""
    process = _run_scan(_scan_command(final_path, filters), duration_s)
    frames, scanned = _completed_progress(process.stdout)
    _bind_length(scanned, duration_s)
    stderr, ansi_stripped = strip_ansi(process.stderr)
    return GlitchScan(stderr, process.stdout, frames, scanned, ansi_stripped=ansi_stripped)


def filter_escape(value: str) -> str:
    """Two-level FFmpeg filtergraph escaping: option level (\\ ' :), then graph level."""
    option = "".join(f"\\{char}" if char in _OPTION_SPECIALS else char for char in value)
    return "".join(f"\\{char}" if char in _GRAPH_SPECIALS else char for char in option)


def _luma_header(line: str, pending: Optional[tuple[int, float]], ordinal: int) -> tuple[int, float]:
    """Frame headers carry the contiguous ordinal, exact pts ticks and printed pts_time."""
    frame = _LUMA_FRAME.fullmatch(line)
    if frame is None or pending is not None or int(frame[1]) != ordinal:
        raise GlitchScanError("luma frame coverage is malformed or incomplete")
    if ordinal >= MAX_LUMA_FRAMES:
        raise GlitchScanError(f"luma scan exceeds the {MAX_LUMA_FRAMES}-frame supported class")
    return int(frame[2]), float(frame[3])


def _luma_sample(line: str, pending: Optional[tuple[int, float]],
                 last: Optional[tuple[int, float]]) -> tuple[int, float, float]:
    """One finite 8-bit YAVG per header; pts ticks strictly increase, pts_time never falls."""
    luma = _YAVG.fullmatch(line)
    if luma is None or pending is None:
        raise GlitchScanError("luma value is unpaired or malformed")
    pts, pts_time = pending
    value = float(luma[1])
    if not math.isfinite(pts_time) or not math.isfinite(value) or not 0 <= value <= 255:
        raise GlitchScanError("luma values are outside the detector's 8-bit class")
    if last is not None and (pts <= last[0] or pts_time < last[1]):
        raise GlitchScanError("luma frame timestamps are not strictly ordered")
    return pts, pts_time, value


def _parse_luma(lines: Iterable[str], frames: int) -> list[tuple[float, float]]:
    """Streaming parse: exactly one bounded YAVG per decoded frame, in original order."""
    series: list[tuple[float, float]] = []
    pending = None
    last = None
    for raw in lines:
        line = raw.rstrip("\r\n")
        if line.startswith("frame:"):
            pending = _luma_header(line, pending, len(series))
            continue
        if not line.startswith("lavfi.signalstats.YAVG="):
            continue
        pts, pts_time, value = _luma_sample(line, pending, last)
        series.append((pts_time, value))
        last, pending = (pts, pts_time), None
    if pending is not None or not series or len(series) != frames:
        raise GlitchScanError("luma coverage does not match the complete decoded video")
    return series


def scan_luma(observed: GlitchScan) -> list[tuple[float, float]]:
    """Parse a held metadata text (tests and small captures)."""
    return _parse_luma(observed.metadata.splitlines(), observed.frames)


def _stream_sink(sink: str, frames: int) -> list[tuple[float, float]]:
    """Read the private sink as a stream; an absent or non-text sink is not empty evidence."""
    try:
        with open(sink, "r", encoding="utf8", errors="strict") as handle:
            return _parse_luma(handle, frames)
    except (OSError, UnicodeError) as error:
        raise GlitchScanError(f"luma sink unreadable: {type(error).__name__}") from error


def scan_luma_frames(final_path: str, duration_s: Optional[float] = None) -> list[tuple[float, float]]:
    """signalstats YAVG per frame through a private sink that never shares the progress pipe."""
    with tempfile.TemporaryDirectory(prefix="sniper-glitch-luma-") as folder:
        sink = os.path.join(folder, "luma.txt")
        filters = f"signalstats,metadata=print:key=lavfi.signalstats.YAVG:file={filter_escape(sink)}"
        process = _run_scan(_scan_command(final_path, filters), duration_s)
        frames, scanned = _completed_progress(process.stdout)
        _bind_length(scanned, duration_s)
        return _stream_sink(sink, frames)
