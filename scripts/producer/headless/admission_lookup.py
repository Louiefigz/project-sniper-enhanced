"""Attempt-only lookup for one already durable admission."""

from __future__ import annotations

import os

from .admission_registry import (
    _ADMISSIONS,
    _ATTEMPTS,
    _LOCK_NAME,
    AdmissionError,
    AdmissionOutcome,
    AttemptNotAdmitted,
    AttemptStateConflict,
    _terminal,
    _uuid,
    _validated_records,
)
from .attempt_initialization import (
    AttemptInitializationError,
    ensure_attempt_initialized,
)
from .durable_files import (
    DurableFileError,
    locked_existing_private_dir,
    open_private_child_dir,
    private_child_dir,
)


def _locate_locked(
    root_fd: int, authority_root: str, attempt_id: str
) -> AdmissionOutcome:
    admissions_fd = open_private_child_dir(root_fd, _ADMISSIONS)
    try:
        records = _validated_records(root_fd, admissions_fd)
    finally:
        os.close(admissions_fd)
    matches = [row for row in records if row["attemptId"] == attempt_id]
    if not matches:
        raise AttemptNotAdmitted("attempt is not durably admitted")
    if len(matches) != 1:
        raise AdmissionError("attempt admission is ambiguous")
    record = matches[0]
    attempts_fd = private_child_dir(root_fd, _ATTEMPTS)
    try:
        try:
            ensure_attempt_initialized(root_fd, attempts_fd, record)
        except AttemptInitializationError as exc:
            raise AttemptStateConflict(str(exc)) from exc
    finally:
        os.close(attempts_fd)
    return AdmissionOutcome(False, record, _terminal(authority_root, record))


def locate_admission(authority_root: str, attempt_id: str) -> AdmissionOutcome:
    """Find a canonical attempt without accepting other caller identity."""
    _uuid("attempt ID", attempt_id)
    try:
        with locked_existing_private_dir(
            authority_root, _LOCK_NAME
        ) as root_fd:
            return _locate_locked(root_fd, authority_root, attempt_id)
    except DurableFileError as exc:
        if isinstance(exc.__cause__, FileNotFoundError):
            raise AttemptNotAdmitted(
                "attempt is not durably admitted"
            ) from exc
        raise AdmissionError("admission lookup state is unsafe") from exc
