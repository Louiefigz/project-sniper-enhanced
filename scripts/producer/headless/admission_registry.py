"""Durable idempotency and denominator registry for headless attempts."""

from __future__ import annotations

import os
from dataclasses import dataclass

from .admission_record import (
    AdmissionError,
    AdmissionRequest,
    AttemptConflict,
    AttemptNotAdmitted as AttemptNotAdmitted,
    AttemptStateConflict,
    IdempotencyConflict,
    _canonical,
    _decode,
    _record,
    _record_name,
    _uuid as _uuid,
)

from .attempt_initialization import (
    AttemptInitializationError,
    attempt_path_exists,
    ensure_attempt_initialized,
    initialization_exists,
)
from .authority_record import (
    AuthorityRecordError,
    ensure_authority_record,
    read_authority_record,
)
from .durable_files import (
    bounded_directory_entries,
    locked_private_dir,
    private_child_dir,
    read_private_file,
    write_pending_replace,
)
from .terminal_manifest import read_terminal_manifest

__all__ = (
    "AdmissionError",
    "AdmissionOutcome",
    "AdmissionRequest",
    "AttemptConflict",
    "AttemptNotAdmitted",
    "AttemptStateConflict",
    "IdempotencyConflict",
    "admit",
    "list_admissions",
    "locate_admission",
    "_uuid",
)

_LOCK_NAME = ".admission.lock"
_ADMISSIONS = "admissions"
_ATTEMPTS = "attempts"
_PENDING = ".admission.pending"


@dataclass(frozen=True)
class AdmissionOutcome:
    """New or replayed admission and any already sealed terminal result."""

    created: bool
    record: dict
    terminal_manifest: dict | None


def _all_records(dir_fd: int) -> list[dict]:
    names = bounded_directory_entries(dir_fd, 50_000)
    unknown = [
        name
        for name in names
        if name != _PENDING and not name.endswith(".json")
    ]
    if unknown:
        raise AdmissionError("admission directory has unknown entries")
    records = []
    for name in names:
        if not name.endswith(".json"):
            continue
        record = _decode(read_private_file(dir_fd, name))
        if name != _record_name(record["idempotencyKey"]):
            raise AdmissionError("admission record filename is invalid")
        records.append(record)
    return records


def _terminal(authority_root: str, record: dict) -> dict | None:
    path = os.path.join(authority_root, _ATTEMPTS, record["attemptId"])
    terminal = read_terminal_manifest(path)
    if terminal is None:
        return None
    matches = (
        terminal["attemptId"] == record["attemptId"]
        and terminal["authorityId"] == record["authorityId"]
        and terminal["buildId"] == record["buildId"]
        and terminal["expectedParent"] == record["expectedParent"]
        and terminal["policyId"] == record["policyId"]
        and terminal["releaseId"] == record["releaseId"]
        and terminal["unitId"] == record["unitId"]
        and terminal["requestDigest"] == record["requestIdentityDigest"]
    )
    if not matches:
        raise AdmissionError("terminal manifest does not match admission")
    return terminal


def _initialize(root_fd: int, attempts_fd: int, record: dict) -> None:
    try:
        ensure_attempt_initialized(root_fd, attempts_fd, record)
    except AttemptInitializationError as exc:
        raise AttemptStateConflict(str(exc)) from exc


def _replay(
    request: AdmissionRequest, record: dict, root_fd: int, attempts_fd: int
) -> AdmissionOutcome:
    same = (
        record["authorityId"] == request.authority_id
        and record["unitId"] == request.unit_id
        and record["requestIdentityDigest"] == request.request_identity_digest
        and record["idempotencyKey"] == request.idempotency_key
        and record["releaseId"] == request.release_id
        and record["buildId"] == request.build_id
        and record["policyId"] == request.policy_id
        and record["expectedParent"] == request.expected_parent
    )
    if not same:
        raise IdempotencyConflict(
            "idempotency key is bound to another request"
        )
    _initialize(root_fd, attempts_fd, record)
    return AdmissionOutcome(
        False, record, _terminal(request.authority_root, record)
    )


def _admit_locked(
    root_fd: int, request: AdmissionRequest, proposed: dict
) -> AdmissionOutcome:
    admissions_fd = private_child_dir(root_fd, _ADMISSIONS)
    attempts_fd = private_child_dir(root_fd, _ATTEMPTS)
    try:
        records = _all_records(admissions_fd)
        existing = next(
            (
                row
                for row in records
                if row["idempotencyKey"] == request.idempotency_key
            ),
            None,
        )
        if existing is not None:
            return _replay(request, existing, root_fd, attempts_fd)
        if any(row["attemptId"] == request.attempt_id for row in records):
            raise AttemptConflict("attempt ID is already admitted")
        occupied = attempt_path_exists(
            attempts_fd, request.attempt_id
        ) or initialization_exists(root_fd, request.attempt_id)
        if occupied:
            raise AttemptConflict("unclaimed attempt directory already exists")
        name = _record_name(request.idempotency_key)
        write_pending_replace(
            admissions_fd, (_PENDING, name), _canonical(proposed)
        )
        _initialize(root_fd, attempts_fd, proposed)
        return AdmissionOutcome(True, proposed, None)
    finally:
        os.close(attempts_fd)
        os.close(admissions_fd)


def admit(request: AdmissionRequest) -> AdmissionOutcome:
    """Durably create or replay one idempotent attempt admission."""
    proposed = _record(request)
    with locked_private_dir(request.authority_root, _LOCK_NAME) as root_fd:
        try:
            ensure_authority_record(root_fd, request.authority_id)
        except AuthorityRecordError as exc:
            raise AdmissionError(str(exc)) from exc
        return _admit_locked(root_fd, request, proposed)


def _validated_records(root_fd: int, admissions_fd: int) -> list[dict]:
    records = _all_records(admissions_fd)
    try:
        authority = read_authority_record(root_fd)
    except AuthorityRecordError as exc:
        raise AdmissionError(str(exc)) from exc
    if authority is None and records:
        raise AdmissionError("admission set has no authority binding")
    if authority is not None and any(
        row["authorityId"] != authority["authorityId"] for row in records
    ):
        raise AdmissionError("admission set crosses authority identities")
    return records


def list_admissions(authority_root: str) -> list[dict]:
    """Return the immutable denominator, failing on any malformed record."""
    with locked_private_dir(authority_root, _LOCK_NAME) as root_fd:
        admissions_fd = private_child_dir(root_fd, _ADMISSIONS)
        try:
            return _validated_records(root_fd, admissions_fd)
        finally:
            os.close(admissions_fd)


def locate_admission(authority_root: str, attempt_id: str) -> AdmissionOutcome:
    """Resolve exactly one attempt-bound admission under its authority lock."""
    from .admission_lookup import locate_admission as locate

    return locate(authority_root, attempt_id)
