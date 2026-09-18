"""One outer lock shared by every V3 admission and order transaction."""

from __future__ import annotations

import contextlib
import os
import stat
from collections.abc import Iterator
from dataclasses import dataclass

from .active_fence_lock import (
    ActiveFenceLockError,
    ActiveFenceLockV1,
    validate_active_fence_lock_v1,
)
from .cross_ledger_order_lock_resources import (
    CROSS_LEDGER_ORDER_LOCK_NAME,
    CrossLedgerOrderLockResourcesV1,
    guarded_cross_ledger_order_lock_resources_v1,
)
from .durable_files import DurableFileError, open_private_dir
from .exclusive_lock_lease import (
    ExclusiveLockLeaseError,
    descriptor_identity_v1,
    same_open_description_v1,
    validate_exclusive_lock_lease_v1,
)
from .fork_fd_cleanup import register_child_cleanup_v1

_ACTIVE_WITNESSES: dict[bytes, "_RegisteredCrossWitnessV1"] = {}
register_child_cleanup_v1(_ACTIVE_WITNESSES.clear)


class CrossLedgerOrderLockError(RuntimeError):
    """The shared outer lock is absent, replaced, or otherwise unsafe."""


@dataclass(frozen=True)
class CrossLedgerOrderLockV1:
    """Opaque held-lock witness; valid only inside its context manager."""

    authority_root: str
    root_fd: int
    lock_fd: int
    root_identity: tuple[int, int]
    lock_identity: tuple[int, int]
    creator_pid: int
    lease_token: bytes
    context_token: bytes


@dataclass(frozen=True)
class _RegisteredCrossWitnessV1:
    witness: CrossLedgerOrderLockV1
    root_guard_fd: int
    lock_guard_fd: int
    lease_token: bytes
    publish_parent: ActiveFenceLockV1 | None


def _registered(value: CrossLedgerOrderLockV1) -> _RegisteredCrossWitnessV1:
    token = value.context_token
    if type(token) is not bytes or len(token) != 32:
        raise CrossLedgerOrderLockError("cross lock witness is stale")
    retained = _ACTIVE_WITNESSES.get(token)
    live = (
        type(value.authority_root) is str
        and tuple(map(type, (value.root_fd, value.lock_fd))) == (int, int)
        and type(value.lease_token) is bytes
        and type(value.creator_pid) is int
        and value.creator_pid == os.getpid()
        and retained is not None
        and retained.witness is value
    )
    if not live or retained is None:
        raise CrossLedgerOrderLockError("cross lock witness is stale")
    return retained


def _private_root(value: CrossLedgerOrderLockV1) -> tuple[int, int]:
    named = os.stat(value.authority_root, follow_symlinks=False)
    held = os.fstat(value.root_fd)
    if not all(
        stat.S_ISDIR(info.st_mode)
        and info.st_uid == os.geteuid()
        and stat.S_IMODE(info.st_mode) == 0o700
        for info in (named, held)
    ):
        raise CrossLedgerOrderLockError("cross lock root is not private")
    return named.st_dev, named.st_ino


def _validate_descriptors(
    value: CrossLedgerOrderLockV1, retained: _RegisteredCrossWitnessV1
) -> None:
    root_owned = same_open_description_v1(
        value.root_fd, retained.root_guard_fd, value.root_identity
    )
    lock_owned = same_open_description_v1(
        value.lock_fd, retained.lock_guard_fd, value.lock_identity
    )
    if not root_owned or not lock_owned:
        raise CrossLedgerOrderLockError("cross lock descriptors changed")
    if value.lease_token != retained.lease_token:
        raise CrossLedgerOrderLockError("cross-ledger lease token changed")
    validate_exclusive_lock_lease_v1(
        retained.root_guard_fd,
        retained.lock_guard_fd,
        CROSS_LEDGER_ORDER_LOCK_NAME,
        retained.lease_token,
    )


def validate_cross_ledger_order_lock_v1(value: object) -> None:
    """Require an exact live handle whose root and lock names are retained."""
    if type(value) is not CrossLedgerOrderLockV1:
        raise CrossLedgerOrderLockError("cross-ledger lock witness is invalid")
    retained = _registered(value)
    try:
        _validate_descriptors(value, retained)
        named_root = _private_root(value)
        root_identity = descriptor_identity_v1(value.root_fd)
        lock_identity = descriptor_identity_v1(value.lock_fd)
        if retained.publish_parent is not None:
            _validate_publish_parent(value, retained.publish_parent)
    except CrossLedgerOrderLockError:
        raise
    except (ActiveFenceLockError, ExclusiveLockLeaseError, OSError) as exc:
        raise CrossLedgerOrderLockError(
            "cross lock cannot be observed"
        ) from exc
    valid = (
        root_identity == value.root_identity == named_root
        and lock_identity == value.lock_identity
    )
    if not valid:
        raise CrossLedgerOrderLockError("cross-ledger lock was replaced")


def _validate_publish_parent(
    value: CrossLedgerOrderLockV1, parent: ActiveFenceLockV1
) -> None:
    validate_active_fence_lock_v1(parent)
    same_root = (
        value.authority_root == parent.authority_root
        and value.root_identity == parent.root_identity
        and descriptor_identity_v1(value.root_fd)
        == descriptor_identity_v1(parent.root_fd)
    )
    if not same_root:
        raise CrossLedgerOrderLockError("cross lock changed publish root")


def validate_publish_bound_cross_ledger_order_lock_v1(value: object) -> None:
    """Require a live cross witness descended from its exact publish lock."""
    validate_cross_ledger_order_lock_v1(value)
    retained = _registered(value)
    if retained.publish_parent is None:
        raise CrossLedgerOrderLockError("cross lock has no publisher")
    _validate_publish_parent(value, retained.publish_parent)


def _register_witness(
    authority_root: str,
    resources: CrossLedgerOrderLockResourcesV1,
    parent: ActiveFenceLockV1 | None,
) -> CrossLedgerOrderLockV1:
    witness = CrossLedgerOrderLockV1(
        authority_root,
        resources.root_fd,
        resources.lock_fd,
        resources.root_identity,
        resources.lock_identity,
        os.getpid(),
        resources.lease_token,
        os.urandom(32),
    )
    _ACTIVE_WITNESSES[witness.context_token] = _RegisteredCrossWitnessV1(
        witness,
        resources.root_guard_fd,
        resources.lock_guard_fd,
        resources.lease_token,
        parent,
    )
    return witness


def _release_witness(value: CrossLedgerOrderLockV1 | None) -> None:
    if value is None:
        return
    retained = _ACTIVE_WITNESSES.get(value.context_token)
    if retained is not None and retained.witness is value:
        del _ACTIVE_WITNESSES[value.context_token]


@contextlib.contextmanager
def _locked_cross_ledger_order_fd_v1(
    authority_root: str,
    root_guard_fd: int,
    create: bool,
    parent: ActiveFenceLockV1 | None,
) -> Iterator[CrossLedgerOrderLockV1]:
    witness = None
    body_active = False
    try:
        with guarded_cross_ledger_order_lock_resources_v1(
            root_guard_fd, create, parent
        ) as resources:
            witness = _register_witness(authority_root, resources, parent)
            validate_cross_ledger_order_lock_v1(witness)
            body_active = True
            yield witness
            body_active = False
            validate_cross_ledger_order_lock_v1(witness)
    except CrossLedgerOrderLockError:
        raise
    except (DurableFileError, ExclusiveLockLeaseError, OSError) as exc:
        if body_active:
            raise
        raise CrossLedgerOrderLockError(
            "cross lock acquisition failed"
        ) from exc
    finally:
        _release_witness(witness)


@contextlib.contextmanager
def _locked_cross_ledger_order_root_v1(
    authority_root: str, create: bool
) -> Iterator[CrossLedgerOrderLockV1]:
    try:
        root_fd = open_private_dir(authority_root)
    except (DurableFileError, OSError) as exc:
        raise CrossLedgerOrderLockError(
            "cross-ledger root cannot be opened"
        ) from exc
    with _locked_cross_ledger_order_fd_v1(
        authority_root, root_fd, create, None
    ) as witness:
        yield witness


def validate_publish_cross_ledger_lock_pair_v1(
    publish_lock: object, cross_lock: object
) -> None:
    """Prove the cross witness descends from this exact publisher witness."""
    validate_active_fence_lock_v1(publish_lock)
    validate_publish_bound_cross_ledger_order_lock_v1(cross_lock)
    retained = _registered(cross_lock)
    if retained.publish_parent is not publish_lock:
        raise CrossLedgerOrderLockError("cross lock publisher changed")


@contextlib.contextmanager
def locked_cross_ledger_order_under_publish_mutex_v1(
    publish_lock: object,
) -> Iterator[CrossLedgerOrderLockV1]:
    """Acquire cross-ledger order from the live outer publisher witness."""
    body_active = False
    try:
        validate_active_fence_lock_v1(publish_lock)
        if type(publish_lock) is not ActiveFenceLockV1:
            raise CrossLedgerOrderLockError("publisher lock is invalid")
        root_fd = os.dup(publish_lock.root_fd)
        with _locked_cross_ledger_order_fd_v1(
            publish_lock.authority_root, root_fd, True, publish_lock
        ) as cross_lock:
            validate_publish_cross_ledger_lock_pair_v1(
                publish_lock, cross_lock
            )
            body_active = True
            yield cross_lock
            body_active = False
            validate_publish_cross_ledger_lock_pair_v1(
                publish_lock, cross_lock
            )
    except CrossLedgerOrderLockError:
        raise
    except (ActiveFenceLockError, DurableFileError, OSError) as exc:
        if body_active:
            raise
        raise CrossLedgerOrderLockError("publisher lock is not live") from exc


@contextlib.contextmanager
def locked_cross_ledger_order_root_v1(
    authority_root: str,
) -> Iterator[CrossLedgerOrderLockV1]:
    """Acquire/create the outer lock before any operation-admission lock."""
    with _locked_cross_ledger_order_root_v1(authority_root, True) as witness:
        yield witness


@contextlib.contextmanager
def locked_existing_cross_ledger_order_root_v1(
    authority_root: str,
) -> Iterator[CrossLedgerOrderLockV1]:
    """Acquire an existing outer lock without creating read-side state."""
    with _locked_cross_ledger_order_root_v1(authority_root, False) as witness:
        yield witness
