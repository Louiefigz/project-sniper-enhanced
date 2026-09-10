"""One owned full PNG-page decode with isolated hash/alpha/progress channels.

The caller retains source, font, cache and approval authority. This changes only
decoded proof production, never page composition or retained receipt semantics.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from captions.caption_page_proof import MAX_LOG_BYTES, MAX_PROGRESS_BYTES, page_alpha, page_frame_md5, page_progress
from headless.process_runner import ProcessRequest, run_text
from palmier.process_deadline import process_timeout


def _run(command: list[str], directory: str,
         descriptors: tuple[int, ...] = ()) -> subprocess.CompletedProcess[str]:
    """Use existing owned capture, inherited deadline and exact group reaping."""
    result = run_text(ProcessRequest(tuple(command), "", directory, dict(os.environ),
        process_timeout(), max_output_bytes=MAX_LOG_BYTES, pass_fds=descriptors))
    process_timeout()
    if result.returncode:
        raise RuntimeError("caption page decoded proof failed: " + result.stderr[-1200:])
    return result


def _probe(path: str, tools: dict, expected: dict) -> None:
    """Read metadata only; nb_read_frames is supplied by actual EOF decode later."""
    command = [tools["ffprobe"]["path"], "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,pix_fmt,width,height,r_frame_rate", "-of", "json", path]
    result = _run(command, str(Path(path).parent))
    try:
        streams = json.loads(result.stdout).get("streams") or []
    except (AttributeError, json.JSONDecodeError) as error:
        raise RuntimeError("caption page probe returned invalid JSON") from error
    measured = {key: value for key, value in expected.items() if key != "nb_read_frames"}
    if result.stderr or len(streams) != 1 or streams[0] != measured:
        raise RuntimeError("caption page stream facts are stale")
    process_timeout()


def page_decode_command(path: str, ffmpeg: str, progress_fd: int) -> list[str]:
    """Decode once; whole RGBA hash stdout and all-frame alpha stderr stay separate."""
    graph = ("[0:v:0]split=2[page-rgba][page-alpha];"
        "[page-alpha]alphaextract,signalstats,"
        "metadata=print:key=lavfi.signalstats.YMAX:file='pipe\\:2'[page-measured]")
    return [ffmpeg, "-nostdin", "-hide_banner", "-nostats", "-v", "error",
        "-xerror", "-err_detect", "explode", "-i", path,
        "-filter_complex", graph, "-stats_period", "30", "-progress", f"pipe:{progress_fd}",
        "-map", "[page-rgba]", "-an", "-pix_fmt", "rgba", "-fps_mode", "passthrough",
        "-f", "framemd5", "pipe:1", "-map", "[page-measured]", "-an",
        "-fps_mode", "passthrough", "-f", "null", "-"]


def _remove_progress(descriptor: int, path: str) -> None:
    """Close our descriptor even when a changed or missing name rejects cleanup."""
    try:
        held, current = os.fstat(descriptor), os.lstat(path)
        if (held.st_dev, held.st_ino) != (current.st_dev, current.st_ino):
            raise RuntimeError("caption page progress name changed before cleanup")
        os.unlink(path)
    except FileNotFoundError:
        pass
    finally:
        os.close(descriptor)


@contextmanager
def _progress_file() -> Iterator[tuple[int, str]]:
    """Use new private scratch, never write into the retained caption inventory."""
    with tempfile.TemporaryDirectory(prefix="sniper-caption-page-proof-") as directory:
        descriptor, path = tempfile.mkstemp(prefix="progress-", dir=directory)
        try:
            yield descriptor, path
        finally:
            _remove_progress(descriptor, path)


def _progress_bytes(descriptor: int, path: str) -> str:
    """Read the held FD with a post-return cap; reject aliases or raced bytes."""
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 \
            or not 0 < before.st_size <= MAX_PROGRESS_BYTES:
        raise RuntimeError("caption page progress is not one bounded regular file")
    os.lseek(descriptor, 0, os.SEEK_SET)
    raw = os.read(descriptor, before.st_size + 1)
    after, named = os.fstat(descriptor), os.lstat(path)
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_nlink")
    if len(raw) != before.st_size or any(getattr(before, key) != getattr(after, key)
            or getattr(before, key) != getattr(named, key) for key in fields):
        raise RuntimeError("caption page progress changed during exact read")
    return raw.decode("utf8", errors="strict")


def decode_caption_page(path: str, tools: dict, expected: dict) -> dict:
    """Return the unchanged proof shape only after all three channels prove EOF."""
    frames = int(expected["nb_read_frames"])
    if frames < 1 or str(frames) != expected["nb_read_frames"]:
        raise RuntimeError("caption page requires a positive exact frame count")
    _probe(path, tools, expected)
    with _progress_file() as (descriptor, progress_path):
        result = _run(page_decode_command(path, tools["ffmpeg"]["path"], descriptor),
                      str(Path(path).parent), (descriptor,))
        progress = _progress_bytes(descriptor, progress_path)
        process_timeout()
        page_progress(progress, frames)
        digest = page_frame_md5(result.stdout, expected)
        alpha = page_alpha(result.stderr, expected)
        process_timeout()
    process_timeout()
    return {"stream": dict(expected), "decodedFrameMd5Sha256": digest, **alpha}
