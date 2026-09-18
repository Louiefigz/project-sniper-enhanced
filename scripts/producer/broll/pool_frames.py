"""Safe representative-frame storage for admitted b-roll snapshots."""
from __future__ import annotations

import os
import re
import stat
import tempfile
from pathlib import Path

from ingest_probe import run_command, warn

FRAMES_DIR_NAME = ".frames"
FRAME_POSITIONS = (0.15, 0.50, 0.85)
MAX_ASSET_ID_LENGTH = 96
_SAFE_ASSET_ID = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,95})")


def validate_asset_id(value: object) -> str:
    """Return a filename-safe pool id or reject poisoned cache metadata."""
    if (type(value) is not str or len(value) > MAX_ASSET_ID_LENGTH
            or _SAFE_ASSET_ID.fullmatch(value) is None):
        raise RuntimeError("b-roll pool catalog has an unsafe asset id")
    return value


def _regular_file(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)


def _frame_directory(root: Path) -> Path:
    path = root / FRAMES_DIR_NAME
    path.mkdir(mode=0o700, exist_ok=True)
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise RuntimeError("b-roll frame directory is unavailable") from exc
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise RuntimeError("b-roll frame directory must not be a symlink")
    return path


def _publish_frame(snapshot: Path, output: Path, at_seconds: float) -> None:
    descriptor, staged = tempfile.mkstemp(
        prefix=f".{output.stem}.", suffix=".jpg", dir=output.parent)
    os.close(descriptor)
    try:
        run_command([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{at_seconds:.3f}", "-i", str(snapshot),
            "-frames:v", "1", "-q:v", "2", staged,
        ])
        if not _regular_file(Path(staged)) or Path(staged).stat().st_size == 0:
            raise RuntimeError("ffmpeg did not produce a regular b-roll frame")
        os.replace(staged, output)
        directory = os.open(output.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            os.unlink(staged)
        except FileNotFoundError:
            pass


def extract_frames(snapshot: Path, record: dict, root: Path) -> list[str]:
    """Publish safe review frames derived only from an admitted snapshot."""
    asset_id = validate_asset_id(record.get("id"))
    if record.get("kind") == "image":
        return [str(snapshot)]
    duration = record.get("duration")
    if (duration is not None
            and (type(duration) not in (int, float) or duration <= 0)):
        raise RuntimeError("b-roll pool catalog has an invalid duration")
    if not duration:
        warn(f"no duration for {snapshot}; extracting a single t=0 frame")
    times = [duration * point for point in FRAME_POSITIONS] \
        if duration else [0.0]
    frame_dir = _frame_directory(root)
    relative = []
    for index, at_seconds in enumerate(times, start=1):
        output = frame_dir / f"{asset_id}_{index}.jpg"
        _publish_frame(snapshot, output, at_seconds)
        relative.append(str(output.relative_to(root)))
    return relative


def frames_current(record: dict, root: Path) -> bool:
    """Check that cached frames have exactly the safe paths this id owns."""
    asset_id = validate_asset_id(record.get("id"))
    frames = record.get("frames")
    if type(frames) is not list or not frames:
        return False
    if record.get("kind") == "image":
        path = record.get("path")
        return type(path) is str and frames == [path] \
            and _regular_file(Path(path))
    expected_count = 3 if record.get("duration") else 1
    expected = [
        str(Path(FRAMES_DIR_NAME) / f"{asset_id}_{index}.jpg")
        for index in range(1, expected_count + 1)
    ]
    return frames == expected and all(
        _regular_file(root / relative) for relative in frames)
