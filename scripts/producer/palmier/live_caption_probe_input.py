"""Normalized source and input authority for the live caption paging probe."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

from ingest_probe import probe_media
from palmier.live_acceptance_project_safety import validate_protected_path
from palmier.live_acceptance_runtime import Deadline
from palmier.mcp_client import PalmierError

_CANVASES = {
    ("1080p", "16:9"): (1920, 1080),
    ("1080p", "9:16"): (1080, 1920),
    ("720p", "16:9"): (1280, 720),
    ("720p", "9:16"): (720, 1280),
}


@dataclass(frozen=True)
class ProbeConfig:
    """Immutable inputs for the destructive-but-disposable live probe."""

    source: str
    evidence: str
    prefix: str
    fps: int = 24
    aspect: str = "16:9"
    quality: str = "1080p"
    max_seconds: float = 180.0
    timeout_s: float = 600.0
    cleanup_timeout_s: float = 120.0
    protected_project_path: str | None = None


def source_authority(path: str, deadline: Deadline) -> dict:
    """Hash a regular source while continuously checking the run deadline."""
    if not os.path.isfile(path) or os.path.islink(path):
        raise PalmierError("caption pagination source is not a regular file")
    before = os.stat(path)
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            deadline.check()
            digest.update(chunk)
    after = os.stat(path)
    signature = lambda value: (
        value.st_dev, value.st_ino, value.st_size,
        value.st_mtime_ns, value.st_ctime_ns,
    )
    if signature(before) != signature(after):
        raise PalmierError(
            "caption pagination source changed while it was hashed")
    return {
        "path": os.path.abspath(path), "sha256": digest.hexdigest(),
        "size": after.st_size, "mtimeNs": after.st_mtime_ns,
    }


def validate_probe_config(
        config: ProbeConfig, deadline: Deadline) -> tuple[dict, int]:
    """Require safe paths plus a normalized source matching the project."""
    if os.path.lexists(config.evidence):
        raise PalmierError("caption pagination evidence already exists")
    parent = os.path.dirname(os.path.abspath(config.evidence))
    if not os.path.isdir(parent) or os.path.islink(parent):
        raise PalmierError("caption pagination evidence directory is unsafe")
    if not config.prefix.strip() or "/" in config.prefix \
            or len(config.prefix) > 72:
        raise PalmierError("caption pagination disposable prefix is unsafe")
    if config.fps <= 0 or config.max_seconds <= 0 \
            or config.timeout_s <= 0 or config.cleanup_timeout_s <= 0:
        raise PalmierError("caption pagination budgets must be positive")
    validate_protected_path(config.protected_project_path)
    canvas = _CANVASES.get((config.quality, config.aspect))
    if canvas is None:
        raise PalmierError("caption pagination canvas is unsupported")
    authority = source_authority(config.source, deadline)
    probe = probe_media(config.source)
    if probe.audio_present is not True or probe.duration is None:
        raise PalmierError("caption pagination source has no timed audio")
    source_facts = (
        probe.frame_rate, probe.width, probe.height, probe.rotation, probe.vfr)
    expected = (f"{config.fps}/1", *canvas, 0, False)
    if source_facts != expected:
        raise PalmierError(
            "caption pagination requires normalized source/project "
            f"rate and canvas {expected}; observed {source_facts}")
    frames = int(min(float(probe.duration), config.max_seconds) * config.fps)
    if frames < config.fps * 60:
        raise PalmierError(
            "caption pagination source window is too short for a capped cohort")
    return authority, frames
