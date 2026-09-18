"""Authority-level proof that an admitted attempt directory once existed."""
from __future__ import annotations

import hashlib
import json
import os

from .durable_files import (
    DurableFileError,
    open_private_dir,
    open_private_child_dir,
    private_child_dir,
    read_private_file,
    write_pending_replace,
)

INITIALIZATIONS = "attempt-initializations"


class AttemptInitializationError(RuntimeError):
    """An attempt directory cannot be safely created, healed, or reopened."""


def _canonical(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=True, separators=(",", ":"),
                       sort_keys=True) + "\n").encode("ascii")


def _admission_digest(record: dict) -> str:
    return hashlib.sha256(
        b"sniper-attempt-admission-v1\0" + _canonical(record)).hexdigest()


def _expected(record: dict, info: os.stat_result) -> dict:
    return {"admissionDigest": _admission_digest(record),
            "attemptDevice": info.st_dev, "attemptId": record["attemptId"],
            "attemptInode": info.st_ino, "schemaVersion": 1}


def _marker_name(attempt_id: str) -> str:
    return f"{attempt_id}.json"


def _entry_exists(dir_fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


def attempt_path_exists(attempts_fd: int, attempt_id: str) -> bool:
    """Return whether any directory entry already claims an attempt ID."""
    return _entry_exists(attempts_fd, attempt_id)


def initialization_exists(root_fd: int, attempt_id: str) -> bool:
    """Return whether any marker entry already claims an attempt ID."""
    markers_fd = private_child_dir(root_fd, INITIALIZATIONS)
    try:
        return _entry_exists(markers_fd, _marker_name(attempt_id))
    finally:
        os.close(markers_fd)


def _read_marker(markers_fd: int, record: dict) -> dict | None:
    name = _marker_name(record["attemptId"])
    if not _entry_exists(markers_fd, name):
        return None
    raw = read_private_file(markers_fd, name)
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AttemptInitializationError(
            "attempt initialization is invalid JSON") from exc
    keys = {"admissionDigest", "attemptDevice", "attemptId",
            "attemptInode", "schemaVersion"}
    valid = (isinstance(value, dict) and set(value) == keys
             and value.get("admissionDigest") == _admission_digest(record)
             and value.get("attemptId") == record["attemptId"]
             and type(value.get("attemptDevice")) is int
             and type(value.get("attemptInode")) is int
             and type(value.get("schemaVersion")) is int
             and value.get("schemaVersion") == 1 and raw == _canonical(value))
    if not valid:
        raise AttemptInitializationError(
            "attempt initialization does not match admission")
    return value


def _open_existing(attempts_fd: int, attempt_id: str) -> int:
    try:
        return open_private_child_dir(attempts_fd, attempt_id)
    except DurableFileError as exc:
        if isinstance(exc.__cause__, FileNotFoundError):
            raise AttemptInitializationError(
                "initialized attempt directory is missing") from exc
        raise AttemptInitializationError(str(exc)) from exc


def _create_or_recover_empty(attempts_fd: int, attempt_id: str) -> int:
    fd = private_child_dir(attempts_fd, attempt_id)
    if os.listdir(fd):
        os.close(fd)
        raise AttemptInitializationError(
            "unmarked attempt directory is not an empty admission gap")
    return fd


def _publish_marker(markers_fd: int, record: dict,
                    info: os.stat_result) -> None:
    attempt_id = record["attemptId"]
    names = (f".{attempt_id}.pending", _marker_name(attempt_id))
    write_pending_replace(
        markers_fd, names, _canonical(_expected(record, info)))


def _match_directory(marker: dict, attempt_fd: int) -> None:
    info = os.fstat(attempt_fd)
    actual = (info.st_dev, info.st_ino)
    expected = (marker["attemptDevice"], marker["attemptInode"])
    if actual != expected:
        raise AttemptInitializationError(
            "initialized attempt directory identity changed")


def _close_fds(fds: tuple[int | None, ...]) -> None:
    for fd in fds:
        if fd is not None:
            os.close(fd)


def ensure_attempt_initialized(root_fd: int, attempts_fd: int,
                               record: dict) -> None:
    """Heal only a pre-initialization gap; never recreate lost prior work."""
    markers_fd = private_child_dir(root_fd, INITIALIZATIONS)
    attempt_fd = None
    try:
        marker = _read_marker(markers_fd, record)
        if marker is not None:
            attempt_fd = _open_existing(attempts_fd, record["attemptId"])
            _match_directory(marker, attempt_fd)
            return
        attempt_fd = _create_or_recover_empty(
            attempts_fd, record["attemptId"])
        _publish_marker(markers_fd, record, os.fstat(attempt_fd))
    finally:
        if attempt_fd is not None:
            os.close(attempt_fd)
        os.close(markers_fd)


def validate_attempt_binding(authority_root: str, record: dict,
                             held_attempt_fd: int) -> None:
    """Require the marker, held inode, and current attempt pathname to agree."""
    root_fd = open_private_dir(authority_root)
    markers_fd = attempts_fd = current_fd = None
    try:
        markers_fd = open_private_child_dir(root_fd, INITIALIZATIONS)
        marker = _read_marker(markers_fd, record)
        if marker is None:
            raise AttemptInitializationError(
                "admitted attempt has no initialization marker")
        attempts_fd = open_private_child_dir(root_fd, "attempts")
        current_fd = _open_existing(attempts_fd, record["attemptId"])
        _match_directory(marker, held_attempt_fd)
        _match_directory(marker, current_fd)
    finally:
        _close_fds((current_fd, attempts_fd, markers_fd, root_fd))
