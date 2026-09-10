"""Caller-held byte/stat identity around bounded selected-picture observation.

No hashing or admission happens here. The caller must have linked the supplied
SHA and inode snapshot during its original source/tool verification, and keep
its original ownership guard active throughout the observation callback.
"""
from __future__ import annotations

import math
import os
import re
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from cut_preview_io import real_directory
from opening_prefix_contract import MAX_INPUT_BYTES


class PresenterProbeDeadline(Protocol):
    """Borrow the original owner deadline; this seam never creates a new clock."""

    def remaining(self) -> float:
        """Return remaining original work seconds or raise on cancellation/expiry."""
        ...


@dataclass(frozen=True)
class HeldPresenterProbeFile:
    """Caller-held bytes and dev/ino/mode/uid/gid/nlink/size/mtime/ctime identity."""
    path: str
    sha256: str
    size_bytes: int
    stat_identity: tuple[int, ...]


@dataclass(frozen=True)
class PresenterObservationRuntime:
    """Exact tool, work directory, original deadline and caller ownership guard."""
    ffprobe: HeldPresenterProbeFile
    working_directory: str
    deadline: PresenterProbeDeadline
    guard: Callable[[], None]


def presenter_stat_identity(info: os.stat_result) -> tuple[int, ...]:
    """Expose one stable identity ordering for an already verifying caller."""
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def observation_remaining(runtime: PresenterObservationRuntime) -> float:
    """Check ownership and the actual caller clock without resetting its expiry."""
    if type(runtime) is not PresenterObservationRuntime or not callable(runtime.guard):
        raise ValueError("Presenter observation requires the original runtime owner")
    runtime.guard()
    return probe_deadline_remaining(runtime)


def probe_deadline_remaining(runtime: PresenterObservationRuntime) -> float:
    """Use only the original clock within metadata loops, not repeated source hashing."""
    seconds = runtime.deadline.remaining()
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("Presenter observation original deadline is unavailable or expired")
    return min(float(seconds), 3600.0)


def _validate_reference(value: HeldPresenterProbeFile, tool: bool) -> Path:
    """Validate supplied identity shape, never attach a current stat to a claimed SHA."""
    if type(value) is not HeldPresenterProbeFile or type(value.path) is not str:
        raise ValueError("Presenter probe needs a caller-held file reference")
    path = Path(value.path)
    if (not path.is_absolute() or value.path.startswith("//") or str(path) != value.path
            or ".." in path.parts or len(value.path) > 4096
            or any(ord(char) < 32 or ord(char) == 127 for char in value.path)):
        raise ValueError("Presenter probe reference path is not canonical")
    if type(value.sha256) is not str or re.fullmatch(r"[0-9a-f]{64}", value.sha256) is None:
        raise ValueError("Presenter probe reference SHA is malformed")
    maximum = 1024 ** 3 if tool else MAX_INPUT_BYTES
    if type(value.size_bytes) is not int or not 0 < value.size_bytes <= maximum:
        raise ValueError("Presenter probe exceeds its existing file-size class")
    identity = value.stat_identity
    if type(identity) is not tuple or len(identity) != 9 or any(type(v) is not int for v in identity):
        raise ValueError("Presenter probe requires the caller's exact stat identity")
    if identity[6] != value.size_bytes or identity[5] != 1 or not stat.S_ISREG(identity[2]):
        raise ValueError("Presenter probe is not a held single-link regular file")
    if tool and (identity[2] & 0o111 == 0 or identity[2] & 0o022):
        raise ValueError("Presenter ffprobe is not a protected executable")
    return path


class PresenterProbePin:
    """Hold a no-follow descriptor and compare every endpoint to incoming identity."""

    def __init__(self, value: HeldPresenterProbeFile, runtime: PresenterObservationRuntime, tool: bool = False) -> None:
        """Open only after the original guard, rejecting drift before any process."""
        observation_remaining(runtime)
        self.value, self.runtime, self.fd = value, runtime, -1
        self.path = _validate_reference(value, tool)
        real_directory(self.path.parent)
        self.fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            self.assert_current()
            if tool and not os.access(self.path, os.X_OK):
                raise ValueError("Presenter ffprobe is not executable by this owner")
        except BaseException:
            self.close()
            raise

    def assert_current(self) -> None:
        """Compare descriptor/path after the caller guard; do not invoke later callbacks."""
        real_directory(self.path.parent)
        if (presenter_stat_identity(os.fstat(self.fd)) != self.value.stat_identity
                or presenter_stat_identity(self.path.lstat()) != self.value.stat_identity):
            raise ValueError("Presenter probe held file identity changed")

    def close(self) -> None:
        """Close this local descriptor without changing caller files or authority."""
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def __enter__(self) -> PresenterProbePin:
        """Return the already-held descriptor for the bounded observation lifetime."""
        return self

    def __exit__(self, *_error: object) -> None:
        """Always close on successful, failed or interrupted observation."""
        self.close()
