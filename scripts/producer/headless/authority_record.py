"""Immutable authority identity bound to one canonical authority directory."""

from __future__ import annotations

import fcntl
import json
import os
import re

from .durable_files import (
    assert_private_lock_identity,
    bounded_directory_entries,
    DurableFileError,
    open_private_file,
    read_private_file,
    write_pending_replace,
)

AUTHORITY_NAME = "authority.json"
_PENDING_NAME = ".authority.pending"
_LOCK_NAME = ".authority.lock"
_CALLER_LOCKS = frozenset(
    {
        _LOCK_NAME,
        ".admission.lock",
        ".cross-ledger-order-v1.lock",
        ".operation-admission-v3.lock",
        ".publish.mutex",
        ".render-artifact.lock",
        ".unit-enrollment-v1.lock",
    }
)
_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
_KEYS = {"authorityId", "schemaVersion"}


class AuthorityRecordError(RuntimeError):
    """The authority root is unbound, malformed, or bound to another ID."""


def _encode(value: dict) -> bytes:
    return (
        json.dumps(
            value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        )
        + "\n"
    ).encode("ascii")


def _decode(raw: bytes) -> dict:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthorityRecordError("authority record is invalid JSON") from exc
    valid = (
        isinstance(value, dict)
        and set(value) == _KEYS
        and type(value.get("schemaVersion")) is int
        and value.get("schemaVersion") == 1
        and type(value.get("authorityId")) is str
        and bool(_IDENTITY.fullmatch(value["authorityId"]))
        and _encode(value) == raw
    )
    if not valid:
        raise AuthorityRecordError("authority record schema is invalid")
    return value


def read_authority_record(root_fd: int) -> dict | None:
    """Read optional identity through a locked root descriptor."""
    try:
        raw = read_private_file(root_fd, AUTHORITY_NAME)
    except DurableFileError as exc:
        if isinstance(exc.__cause__, FileNotFoundError):
            return None
        raise AuthorityRecordError(str(exc)) from exc
    return _decode(raw)


def _validate_lock_entries(root_fd: int, names: set[str]) -> None:
    for name in names & _CALLER_LOCKS:
        try:
            descriptor = open_private_file(root_fd, name, os.O_RDWR)
        except DurableFileError as exc:
            raise AuthorityRecordError(
                "authority root lock state is unsafe"
            ) from exc
        os.close(descriptor)


def _recheck_fresh_binding_closure(root_fd: int) -> None:
    allowed = _CALLER_LOCKS | {AUTHORITY_NAME}
    names = set(bounded_directory_entries(root_fd, len(allowed)))
    if AUTHORITY_NAME not in names or names - allowed:
        raise AuthorityRecordError(
            "authority root changed during fresh binding"
        )
    _validate_lock_entries(root_fd, names)


def _ensure_locked(root_fd: int, expected: dict) -> dict:
    existing = read_authority_record(root_fd)
    if existing is not None:
        if existing != expected:
            raise AuthorityRecordError("authority root is bound to another ID")
        return existing
    names = set(bounded_directory_entries(root_fd, len(_CALLER_LOCKS)))
    if names - _CALLER_LOCKS:
        raise AuthorityRecordError("authority root has orphan state")
    _validate_lock_entries(root_fd, names)
    write_pending_replace(
        root_fd, (_PENDING_NAME, AUTHORITY_NAME), _encode(expected)
    )
    observed = read_authority_record(root_fd)
    if observed != expected:
        raise AuthorityRecordError(
            "authority root binding changed concurrently"
        )
    _recheck_fresh_binding_closure(root_fd)
    return observed


def ensure_authority_record(root_fd: int, authority_id: str) -> dict:
    """Serialize fresh binding and reject orphan authority state."""
    if type(authority_id) is not str or not _IDENTITY.fullmatch(authority_id):
        raise AuthorityRecordError("authority ID is invalid")
    expected = {"authorityId": authority_id, "schemaVersion": 1}
    try:
        lock_fd = open_private_file(
            root_fd, _LOCK_NAME, os.O_CREAT | os.O_RDWR
        )
    except DurableFileError as exc:
        raise AuthorityRecordError("authority lock is invalid") from exc
    try:
        os.fsync(root_fd)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        assert_private_lock_identity(root_fd, _LOCK_NAME, lock_fd)
        result = _ensure_locked(root_fd, expected)
        assert_private_lock_identity(root_fd, _LOCK_NAME, lock_fd)
        return result
    except AuthorityRecordError:
        raise
    except (DurableFileError, OSError) as exc:
        raise AuthorityRecordError(
            "authority binding cannot be persisted"
        ) from exc
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
