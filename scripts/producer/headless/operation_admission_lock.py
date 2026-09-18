"""PID-bound leased inner writer witness for V3 admission transactions."""

from __future__ import annotations

import contextlib
import os
import secrets
import stat
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from .authority_record import AuthorityRecordError
from .cross_ledger_order_lock import (
    CrossLedgerOrderLockError,
    CrossLedgerOrderLockV1,
    validate_cross_ledger_order_lock_v1,
    validate_publish_bound_cross_ledger_order_lock_v1,
)
from .durable_files import DurableFileError
from .exclusive_lock_lease import (
    ExclusiveLockLeaseError,
    close_owned_fd_v1,
    descriptor_identity_v1,
    same_open_description_v1,
    valid_descriptor_identity_v1,
    validate_exclusive_lock_lease_v1,
)
from .fork_fd_cleanup import register_child_cleanup_v1
from .operation_admission_lock_resources import (
    OPERATION_ADMISSION_LOCK_NAME,
    OPERATION_ADMISSION_STORE_NAME,
    OperationAdmissionLockResourcesV3,
    guarded_operation_admission_lock_resources_v3,
)

_ACTIVE_WRITERS: dict[bytes, "_RegisteredWriterV3"] = {}
register_child_cleanup_v1(_ACTIVE_WRITERS.clear)


class OperationAdmissionWriterLockError(RuntimeError):
    """The inner V3 writer witness is absent, stale, or unsafe."""


@dataclass(frozen=True)
class OperationAdmissionWriterLockV3:
    """Opaque live inner-lock and store witness under the shared outer lock."""

    authority_root: str
    authority_id: str
    root_fd: int
    lock_fd: int
    store_fd: int
    root_identity: tuple[int, int]
    lock_identity: tuple[int, int]
    store_identity: tuple[int, int]
    creator_pid: int
    lease_token: bytes
    context_token: bytes
    outer_lock: CrossLedgerOrderLockV1


@dataclass(frozen=True)
class _RegisteredWriterV3:
    witness: OperationAdmissionWriterLockV3
    resources: OperationAdmissionLockResourcesV3
    publish_bound: bool


def _private_directory(info: os.stat_result) -> bool:
    return (
        stat.S_ISDIR(info.st_mode)
        and info.st_uid == os.geteuid()
        and stat.S_IMODE(info.st_mode) == 0o700
    )


def _registered(value: OperationAdmissionWriterLockV3) -> _RegisteredWriterV3:
    token = value.context_token
    valid_token = type(token) is bytes and len(token) == 32
    retained = _ACTIVE_WRITERS.get(token) if valid_token else None
    valid = (
        type(value.authority_root) is str
        and type(value.authority_id) is str
        and tuple(map(type, (value.root_fd, value.lock_fd, value.store_fd)))
        == (int, int, int)
        and type(value.lease_token) is bytes
        and type(value.creator_pid) is int
        and value.creator_pid == os.getpid()
        and retained is not None
        and retained.witness is value
    )
    if not valid or retained is None:
        raise OperationAdmissionWriterLockError("V3 writer is stale")
    return retained


def _validate_outer(value: _RegisteredWriterV3) -> None:
    validator = (
        validate_publish_bound_cross_ledger_order_lock_v1
        if value.publish_bound
        else validate_cross_ledger_order_lock_v1
    )
    validator(value.witness.outer_lock)


def _validate_public_fds(value: _RegisteredWriterV3) -> None:
    witness, resources = value.witness, value.resources
    observed = (
        witness.root_identity,
        witness.lock_identity,
        witness.store_identity,
        witness.lease_token,
    )
    identities_safe = all(map(valid_descriptor_identity_v1, observed[:3]))
    safe = identities_safe and type(observed[3]) is bytes
    if not safe or observed != (
        resources.root_identity,
        resources.lock_identity,
        resources.store_identity,
        resources.lease_token,
    ):
        raise OperationAdmissionWriterLockError("V3 writer lease changed")
    pairs = (
        (witness.root_fd, resources.root_guard_fd, resources.root_identity),
        (witness.lock_fd, resources.lock_guard_fd, resources.lock_identity),
        (witness.store_fd, resources.store_guard_fd, resources.store_identity),
    )
    if not all(same_open_description_v1(*pair) for pair in pairs):
        raise OperationAdmissionWriterLockError("V3 writer FDs changed")
    validate_exclusive_lock_lease_v1(
        resources.root_guard_fd,
        resources.lock_guard_fd,
        OPERATION_ADMISSION_LOCK_NAME,
        resources.lease_token,
    )


def _validate_directories(value: _RegisteredWriterV3) -> None:
    witness, resources = value.witness, value.resources
    named_store = os.stat(
        OPERATION_ADMISSION_STORE_NAME,
        dir_fd=resources.root_guard_fd,
        follow_symlinks=False,
    )
    roots_match = (
        witness.root_identity
        == descriptor_identity_v1(resources.root_guard_fd)
        == descriptor_identity_v1(witness.outer_lock.root_fd)
    )
    stores_match = witness.store_identity == (
        named_store.st_dev,
        named_store.st_ino,
    )
    private = all(
        _private_directory(info)
        for info in (
            os.fstat(resources.root_guard_fd),
            os.fstat(resources.store_guard_fd),
            named_store,
        )
    )
    if not roots_match or not stores_match or not private:
        raise OperationAdmissionWriterLockError("V3 writer paths changed")


def validate_operation_admission_writer_lock_v3(value: object) -> None:
    """Require exact public descriptors, lease, outer lock, root, and store."""
    if type(value) is not OperationAdmissionWriterLockV3:
        raise OperationAdmissionWriterLockError(
            "V3 writer lock witness is invalid"
        )
    retained = _registered(value)
    try:
        _validate_outer(retained)
        _validate_public_fds(retained)
        _validate_directories(retained)
    except OperationAdmissionWriterLockError:
        raise
    except (ExclusiveLockLeaseError, OSError, RuntimeError) as exc:
        raise OperationAdmissionWriterLockError(
            "V3 writer is invalid"
        ) from exc


def _register(
    authority: tuple[str, str],
    outer_lock: CrossLedgerOrderLockV1,
    resources: OperationAdmissionLockResourcesV3,
    publish_bound: bool,
) -> OperationAdmissionWriterLockV3:
    authority_root, authority_id = authority
    witness = OperationAdmissionWriterLockV3(
        authority_root,
        authority_id,
        resources.root_fd,
        resources.lock_fd,
        resources.store_fd,
        resources.root_identity,
        resources.lock_identity,
        resources.store_identity,
        os.getpid(),
        resources.lease_token,
        secrets.token_bytes(32),
        outer_lock,
    )
    _ACTIVE_WRITERS[witness.context_token] = _RegisteredWriterV3(
        witness, resources, publish_bound
    )
    return witness


def _outer_validator(
    outer_lock: CrossLedgerOrderLockV1, publish_bound: bool
) -> Callable[[], None]:
    validator = (
        validate_publish_bound_cross_ledger_order_lock_v1
        if publish_bound
        else validate_cross_ledger_order_lock_v1
    )

    def validate() -> None:
        validator(outer_lock)

    return validate


def _publish_bound_or_standalone(outer_lock: CrossLedgerOrderLockV1) -> bool:
    try:
        validate_publish_bound_cross_ledger_order_lock_v1(outer_lock)
    except CrossLedgerOrderLockError:
        validate_cross_ledger_order_lock_v1(outer_lock)
        return False
    return True


@contextlib.contextmanager
def _locked_operation_admission_writer_v3(
    authority_root: str,
    authority_id: str,
    outer_lock: CrossLedgerOrderLockV1,
    publish_bound: bool,
) -> Iterator[OperationAdmissionWriterLockV3]:
    validate_outer = _outer_validator(outer_lock, publish_bound)
    validate_outer()
    if (
        type(authority_root) is not str
        or authority_root != outer_lock.authority_root
    ):
        raise OperationAdmissionWriterLockError("V3 writer root changed")
    authority = (authority_root, authority_id)
    root_guard_fd = os.dup(outer_lock.root_fd)
    root_identity = descriptor_identity_v1(root_guard_fd)
    resources_started = False
    witness = None
    body_active = False
    try:
        validate_outer()
        resources_started = True
        with guarded_operation_admission_lock_resources_v3(
            root_guard_fd, authority_id, validate_outer
        ) as resources:
            witness = _register(
                authority, outer_lock, resources, publish_bound
            )
            validate_operation_admission_writer_lock_v3(witness)
            body_active = True
            yield witness
            body_active = False
            validate_operation_admission_writer_lock_v3(witness)
    except OperationAdmissionWriterLockError:
        raise
    except (
        AuthorityRecordError,
        CrossLedgerOrderLockError,
        DurableFileError,
        ExclusiveLockLeaseError,
        OSError,
    ) as exc:
        if body_active:
            raise
        raise OperationAdmissionWriterLockError("V3 authority failed") from exc
    finally:
        if witness is not None:
            _ACTIVE_WRITERS.pop(witness.context_token, None)
        if not resources_started:
            close_owned_fd_v1(root_guard_fd, root_identity)


@contextlib.contextmanager
def locked_operation_admission_writer_v3(
    authority_root: str,
    authority_id: str,
    outer_lock: CrossLedgerOrderLockV1,
) -> Iterator[OperationAdmissionWriterLockV3]:
    """Acquire the standalone inner writer beneath a normal outer lock."""
    publish_bound = _publish_bound_or_standalone(outer_lock)
    with _locked_operation_admission_writer_v3(
        authority_root, authority_id, outer_lock, publish_bound
    ) as witness:
        yield witness
