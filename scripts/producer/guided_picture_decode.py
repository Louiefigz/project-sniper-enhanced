"""One bounded, strict complete picture decode with exact terminal frame count.

This reuses the audit progress parser, not its approximate duration tolerance or
detector policy. The caller still owns metadata, exact packet clock, byte-stability
and source/approval checks. No decoded output or new approval is persisted here.
"""
from __future__ import annotations

import os
from pathlib import Path

from audit.audit_glitch_scan import _completed_progress
from headless.process_runner import ProcessRequest, run_text
from palmier.process_deadline import process_timeout

MAX_DECODE_LOG_BYTES = 1024 * 1024


def require_decoded_frames(stdout: str, expected: int) -> None:
    """Require complete bounded progress and exact count, never container duration.

    Raises:
        RuntimeError: The stdout or terminal decoded frame count is unproved.
    """
    if type(expected) is not int or expected <= 0:
        raise RuntimeError("picture decode requires a positive exact frame count")
    if not isinstance(stdout, str) or len(stdout.encode("utf-8")) > MAX_DECODE_LOG_BYTES:
        raise RuntimeError("picture decode progress exceeds its text byte bound")
    count, _seconds = _completed_progress(stdout)
    if count != expected:
        raise RuntimeError("picture complete decoded frame count differs from exact authority")


def decode_picture_frames(path: Path, ffmpeg: str, frames: int) -> None:
    """Decode selected picture once to EOF under the caller's remaining deadline.

    Progress has a sole stdout writer. Passthrough prevents a null muxer's output
    sync from duplicating/dropping frames; packet-level rational PTS remains a
    separate caller check. The existing owned runner bounds both pipes and reaps
    its process group on success, error, overflow and deadline expiry.
    """
    if type(frames) is not int or frames <= 0:
        raise RuntimeError("picture decode requires a positive exact frame count")
    command = (ffmpeg, "-nostdin", "-hide_banner", "-nostats", "-v", "error",
        "-xerror", "-err_detect", "explode", "-i", str(path), "-map", "0:v:0",
        "-an", "-fps_mode", "passthrough", "-progress", "pipe:1", "-f", "null", "-")
    result = run_text(ProcessRequest(command, "", str(path.parent), dict(os.environ),
        process_timeout(), max_output_bytes=MAX_DECODE_LOG_BYTES))
    if result.returncode:
        raise RuntimeError("picture complete decode failed: " + result.stderr[-1200:])
    process_timeout()  # A successful child cannot publish after the enclosing deadline.
    require_decoded_frames(result.stdout, frames)
    process_timeout()
