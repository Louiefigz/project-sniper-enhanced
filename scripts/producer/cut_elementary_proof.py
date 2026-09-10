"""Prove that a cut concat contains the ordered encoded video of every part."""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ElementaryStream:
    """One normalized H.264 elementary-stream observation."""

    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class SequenceProof:
    """Per-part observations plus ordered-parts/concat byte equality."""

    parts: list[ElementaryStream]
    ordered_parts: ElementaryStream
    concat: ElementaryStream


def _command(path: str) -> list[str]:
    """Build the lossless MP4-H.264 to canonical Annex-B projection."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("cut elementary proof cannot resolve ffmpeg")
    return [
        ffmpeg, "-v", "error", "-xerror", "-i", path, "-map", "0:v:0",
        "-c:v", "copy", "-bsf:v", "h264_mp4toannexb", "-f", "h264", "-",
    ]


def _observe(path: str, ordered: Any | None) -> ElementaryStream:
    """Stream one normalized video through local and optional ordered hashes."""
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(
            _command(path), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=errors)
        assert process.stdout is not None
        digest, size = hashlib.sha256(), 0
        while chunk := process.stdout.read(1024 * 1024):
            digest.update(chunk)
            if ordered is not None:
                ordered.update(chunk)
            size += len(chunk)
        code = process.wait()
        process.stdout.close()
        errors.seek(0)
        stderr = errors.read()
    if code or size <= 0:
        detail = stderr.decode("utf-8", errors="replace")[-300:]
        raise RuntimeError(f"cut elementary proof failed: {detail}")
    return ElementaryStream(digest.hexdigest(), size)


def prove_video_sequence(parts: list[str], concat: str) -> SequenceProof:
    """Require concat Annex-B bytes to equal ordered part Annex-B bytes."""
    if not parts:
        raise ValueError("cut elementary proof has no parts")
    ordered_hash = hashlib.sha256()
    rows = [_observe(path, ordered_hash) for path in parts]
    ordered = ElementaryStream(
        ordered_hash.hexdigest(), sum(row.size_bytes for row in rows))
    concat_stream = _observe(concat, None)
    if ordered != concat_stream:
        raise RuntimeError(
            "cut concat video does not equal the ordered encoded parts")
    return SequenceProof(rows, ordered, concat_stream)
