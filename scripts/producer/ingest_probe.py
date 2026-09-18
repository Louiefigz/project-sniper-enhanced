#!/usr/bin/env python3
"""ingest_probe — shared ffprobe + hashing + IO helpers for PRODUCER ingest.

Kept separate from ``ingest.py`` / ``ingest_scan.py`` so each stays under the
300-line logic budget. One ``probe_media`` call reads duration, frame rate (with
a VFR flag), resolution, rotation and audio presence; ``content_hash`` powers the
duplicate-source dedup. The extension sets + ``status``/``warn`` emit helpers live
here as the common base every ingest module imports. See docs/producer/PRODUCER_PLAN.md
§2.1 (manifest schema) and §8 (ingest edge cases).
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Optional

from palmier.process_deadline import process_timeout

# ---------------------------------------------------------------------------
# Recognised media extensions (lowercase, with dot). Shared by every scanner.
# ---------------------------------------------------------------------------
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".mpg", ".mpeg"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".aiff"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".tif"}
# Discover these inputs so they receive an explicit rejection, never silent omission.
UNSUPPORTED_DOCUMENT_EXTS = {".svg", ".svgz"}
MEDIA_EXTS = VIDEO_EXTS | AUDIO_EXTS | IMAGE_EXTS | UNSUPPORTED_DOCUMENT_EXTS

HASH_HEAD_BYTES = 8 * 1024 * 1024   # first 8MB feeds the content hash
_VFR_TOLERANCE = 0.01               # fps delta below this reads as CFR jitter


def _document_prefix(prefix: bytes) -> bool:
    """Reject document-shaped text; a BOM alone may also be an MPEG header."""
    encodings = ((b"\xff\xfe\x00\x00", "utf-32-le"), (b"\x00\x00\xfe\xff", "utf-32-be"),
                 (b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be"))
    for marker, encoding in encodings:
        if prefix.startswith(marker):
            text = prefix[len(marker):].decode(encoding, errors="replace").lstrip()
            return not text or text.startswith("<")
    stripped = prefix.removeprefix(b"\xef\xbb\xbf").lstrip()
    return not stripped or stripped.startswith(b"<") or prefix.startswith(b"\x1f\x8b")


def reject_unsupported_ingest_media(path: str | Path, media_kind: str | None = None) -> None:
    """Reject vector documents without decoding, sanitizing or granting native admission.

    A bounded prefix also catches XML/SVG or gzip documents renamed as raster media
    and opaque ``.media`` snapshots. This is a rejection gate, not an SVG parser.
    """
    file = Path(path)
    unsupported = file.suffix.lower() in UNSUPPORTED_DOCUMENT_EXTS or media_kind == "svg"
    if not unsupported:
        descriptor = os.open(file, os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise RuntimeError(f"Supplied-media ingest needs a regular file: {file}")
            prefix = handle.read(1024)
        unsupported = _document_prefix(prefix)
    if unsupported:
        raise RuntimeError(
            f"SVG/SVGZ or XML/compressed document is unsupported by supplied-media ingest: {file}. "
            "Provide a PNG, JPEG or WebP derivative through its own sandbox admission; "
            "the original document was not sanitized or admitted for native use.")


def status(**fields) -> None:
    """Emit one JSON status line to stdout (matches the other workers)."""
    print(json.dumps(fields, default=str), flush=True)


def warn(msg: str) -> None:
    """Surface a non-fatal warning on stderr — never silently skip."""
    print(f"[ingest] WARN {msg}", file=sys.stderr, flush=True)


def run_command(cmd: list[str]) -> str:
    """Run a command, returning stripped stdout; raise on non-zero exit."""
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=process_timeout())
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"{cmd[0]} failed")
    return result.stdout.strip()


@dataclass
class MediaProbe:
    """Container-level facts about one media file (video / audio / image)."""

    duration: Optional[float]
    fps: Optional[float]
    vfr: bool
    width: Optional[int]
    height: Optional[int]
    rotation: int
    audio_present: bool
    audio_channels: Optional[int]
    audio_sample_rate: Optional[int]
    frame_rate: Optional[str] = None


def ffprobe_json(path: str) -> dict:
    """Return ffprobe's combined format+streams JSON for a file."""
    out = run_command([
        "ffprobe", "-v", "error",
        "-show_format", "-show_streams",
        "-of", "json", path,
    ])
    return json.loads(out)


def _parse_fraction(value: Optional[str]) -> Optional[float]:
    """Parse an ffprobe rational ('30000/1001') to float; guard 0/0 and N/A."""
    if not value or value in ("0/0", "N/A"):
        return None
    try:
        frac = Fraction(value)
    except (ValueError, ZeroDivisionError):
        return None
    return float(frac) if frac else None


def _canonical_fraction(value: Optional[str]) -> Optional[str]:
    """Canonical positive ffprobe rational, preserving its exact rate."""
    if not value or value in ("0/0", "N/A"):
        return None
    try:
        fraction = Fraction(value)
    except (ValueError, ZeroDivisionError):
        return None
    if fraction <= 0:
        return None
    return f"{fraction.numerator}/{fraction.denominator}"


def _first_stream(streams: list[dict], codec_type: str) -> Optional[dict]:
    """First stream of the given codec_type ('video' / 'audio'), or None."""
    return next((s for s in streams if s.get("codec_type") == codec_type), None)


def _rotation_from_side_data(stream: dict) -> Optional[int]:
    """First parseable display-matrix side-data rotation (mod 360), or None."""
    for side in stream.get("side_data_list", []):
        if "rotation" not in side:
            continue
        try:
            return int(float(side["rotation"])) % 360
        except (ValueError, TypeError):
            continue
    return None


def _rotation(stream: dict) -> int:
    """Rotation degrees from tags.rotate or a display-matrix side-data entry."""
    tag = stream.get("tags", {}).get("rotate")
    if tag not in (None, ""):
        try:
            return int(float(tag)) % 360
        except ValueError:
            pass
    side_rotation = _rotation_from_side_data(stream)
    return side_rotation if side_rotation is not None else 0


def _fps_and_vfr(stream: dict) -> tuple[Optional[float], bool]:
    """Reported fps + VFR flag (r_frame_rate vs avg_frame_rate mismatch)."""
    r_fps = _parse_fraction(stream.get("r_frame_rate"))
    avg_fps = _parse_fraction(stream.get("avg_frame_rate"))
    if r_fps is None and avg_fps is None:
        return None, False
    if r_fps is None or avg_fps is None:
        return round(avg_fps or r_fps, 3), False
    vfr = abs(r_fps - avg_fps) > _VFR_TOLERANCE
    # Report the true average rate — it is what timeline math must use on VFR.
    return round(avg_fps, 3), vfr


def probe_media(path: str) -> MediaProbe:
    """Probe one media file into a ``MediaProbe`` (single ffprobe call)."""
    reject_unsupported_ingest_media(path)
    data = ffprobe_json(path)
    streams = data.get("streams", [])
    v = _first_stream(streams, "video")
    a = _first_stream(streams, "audio")
    dur_raw = data.get("format", {}).get("duration")
    duration = float(dur_raw) if dur_raw not in (None, "N/A") else None
    fps, vfr = _fps_and_vfr(v) if v else (None, False)
    return MediaProbe(
        duration=round(duration, 3) if duration is not None else None,
        fps=fps,
        vfr=vfr,
        width=int(v["width"]) if v and v.get("width") else None,
        height=int(v["height"]) if v and v.get("height") else None,
        rotation=_rotation(v) if v else 0,
        audio_present=a is not None,
        audio_channels=int(a["channels"]) if a and a.get("channels") else None,
        audio_sample_rate=int(a["sample_rate"]) if a and a.get("sample_rate") else None,
        frame_rate=_canonical_fraction(v.get("r_frame_rate")) if v else None,
    )


def content_hash(path: str) -> str:
    """SHA-1 of file size + first 8MB — a cheap dedup key for large media."""
    with open(path, "rb") as f:
        head = f.read(HASH_HEAD_BYTES)
    h = hashlib.sha1()
    h.update(str(os.path.getsize(path)).encode())
    h.update(head)
    return h.hexdigest()
