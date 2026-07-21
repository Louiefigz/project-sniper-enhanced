"""Never-unlinked outer publisher mutex and PID-bound live witness.

Future composition must acquire lock tiers in ``PUBLISH_MUTEX_LOCK_ORDER_V1``
order. This module does not acquire any inner ledger lock.
"""

from __future__ import annotations

import contextlib
import os
import secrets
import stat
from collections.abc import Iterator
from dataclasses import dataclass

from .active_fence_lock_resources import (
    ActiveFenceLockResourcesV1,
    PUBLISH_MUTEX_NAME,
    guarded_active_fence_lock_resources_v1,
)
from .durable_files import DurableFileError, assert_private_lock_identity
from .exclusive_lock_lease import (
    ExclusiveLockLeaseError,
    descriptor_identity_v1,
    same_open_description_v1,
    valid_descriptor_identity_v1,
    validate_exclusive_lock_lease_v1,
)
from .fork_fd_cleanup import register_child_cleanup_v1

PUBLISH_MUTEX_LOCK_ORDER_V1 = (
    frozenset({PUBLISH_MUTEX_NAME}),
    frozenset({".cross-ledger-order-v1.lock"}),
    frozenset({".unit-enrollment-v1.lock", ".operation-admission-v3.lock"}),
)


class ActiveFenceLockError(RuntimeError):
    """The outer publisher mutex is absent, replaced, or not held."""


@dataclass(frozen=True)
class ActiveFenceLockV1:
    """Opaque borrowed capability valid only inside its creating context.

    Its raw descriptors must not be closed, replaced, or concurrently mutated
    by caller code. Validation detects a completed replacement; POSIX cannot
    make a descriptor-number check and later close atomic against same-process
    descriptor-table sabotage.
    """

    authority_root: str
    root_fd: int
    lock_fd: int
    root_identity: tuple[int, int]
    lock_identity: tuple[int, int]
    creator_pid: int
    lease_token: bytes
    context_token: bytes


@dataclass(frozen=True)
class _ActiveFenceRegistrationV1:
    context_token: bytes
    witness: ActiveFenceLockV1
    root_guard_fd: int
    lock_guard_fd: int
    lease_token: bytes


_ACTIVE_WITNESSES: dict[bytes, _ActiveFenceRegistrationV1] = {}
_REGISTRY_PID = os.getpid()


def _clear_inherited_registry_v1() -> None:
    """Discard every parent registration in a fork child."""
    global _REGISTRY_PID
    _ACTIVE_WITNESSES.clear()
    _REGISTRY_PID = os.getpid()


register_child_cleanup_v1(_clear_inherited_registry_v1)


def _reset_inherited_registry_v1() -> None:
    """Lazily recover if this platform lacks an at-fork callback."""
    current_pid = os.getpid()
    if current_pid != _REGISTRY_PID:
        _clear_inherited_registry_v1()


def _private_root(value: ActiveFenceLockV1) -> tuple[int, int]:
    named = os.stat(value.authority_root, follow_symlinks=False)
    held = os.fstat(value.root_fd)
    private = all(
        stat.S_ISDIR(info.st_mode)
        and info.st_uid == os.geteuid()
        and stat.S_IMODE(info.st_mode) == 0o700
        for info in (named, held)
    )
    if not private:
        raise ActiveFenceLockError("active-fence root is no longer private")
    return named.st_dev, named.st_ino


def _valid_witness_primitives(value: ActiveFenceLockV1) -> bool:
    return (
        type(value.authority_root) is str
        and type(value.root_fd) is int
        and value.root_fd >= 0
        and type(value.lock_fd) is int
        and value.lock_fd >= 0
        and valid_descriptor_identity_v1(value.root_identity)
        and valid_descriptor_identity_v1(value.lock_identity)
        and type(value.lease_token) is bytes
        and len(value.lease_token) == 32
    )


def _registered_witness(
    value: ActiveFenceLockV1,
) -> _ActiveFenceRegistrationV1:
    _reset_inherited_registry_v1()
    context_token = value.context_token
    valid_token = type(context_token) is bytes and len(context_token) == 32
    if not valid_token:
        raise ActiveFenceLockError("active-fence lock witness is not live")
    registered = _ACTIVE_WITNESSES.get(context_token)
    live = (
        type(value.creator_pid) is int
        and value.creator_pid == os.getpid()
        and type(registered) is _ActiveFenceRegistrationV1
        and registered.witness is value
    )
    if not live:
        raise ActiveFenceLockError("active-fence lock witness is not live")
    return registered


def validate_active_fence_lock_v1(value: object) -> None:
    """Require the registered same-process witness and named locked inode."""
    if type(value) is not ActiveFenceLockV1:
        raise ActiveFenceLockError("active-fence lock witness is invalid")
    if not _valid_witness_primitives(value):
        raise ActiveFenceLockError("active-fence lock witness is invalid")
    registered = _registered_witness(value)
    try:
        root_identity = descriptor_identity_v1(value.root_fd)
        lock_identity = descriptor_identity_v1(value.lock_fd)
        named_root = _private_root(value)
        assert_private_lock_identity(
            value.root_fd, PUBLISH_MUTEX_NAME, value.lock_fd
        )
        guarded = same_open_description_v1(
            value.root_fd, registered.root_guard_fd, value.root_identity
        ) and same_open_description_v1(
            value.lock_fd, registered.lock_guard_fd, value.lock_identity
        )
        validate_exclusive_lock_lease_v1(
            registered.root_guard_fd,
            registered.lock_guard_fd,
            PUBLISH_MUTEX_NAME,
            value.lease_token,
        )
    except ActiveFenceLockError:
        raise
    except (DurableFileError, ExclusiveLockLeaseError, OSError) as exc:
        raise ActiveFenceLockError(
            "active-fence lock identity cannot be reobserved"
        ) from exc
    valid = (
        root_identity == value.root_identity == named_root
        and lock_identity == value.lock_identity
        and value.lease_token == registered.lease_token
        and guarded
    )
    if not valid:
        raise ActiveFenceLockError(
            "active-fence lock was replaced or released"
        )


def _register_witness(
    authority_root: str, resources: ActiveFenceLockResourcesV1
) -> tuple[ActiveFenceLockV1, _ActiveFenceRegistrationV1]:
    _reset_inherited_registry_v1()
    context_token = secrets.token_bytes(32)
    if type(context_token) is not bytes or len(context_token) != 32:
        raise ActiveFenceLockError(
            "active-fence context token generation failed"
        )
    if context_token in _ACTIVE_WITNESSES:
        raise ActiveFenceLockError(
            "active-fence context token was already registered"
        )
    witness = ActiveFenceLockV1(
        authority_root,
        resources.root_fd,
        resources.lock_fd,
        resources.root_identity,
        resources.lock_identity,
        os.getpid(),
        resources.lease_token,
        context_token,
    )
    registration = _ActiveFenceRegistrationV1(
        context_token,
        witness,
        resources.root_guard_fd,
        resources.lock_guard_fd,
        resources.lease_token,
    )
    _ACTIVE_WITNESSES[context_token] = registration
    return witness, registration


def _release_witness(value: _ActiveFenceRegistrationV1 | None) -> None:
    if value is None:
        return
    _reset_inherited_registry_v1()
    if _ACTIVE_WITNESSES.get(value.context_token) is value:
        del _ACTIVE_WITNESSES[value.context_token]


@contextlib.contextmanager
def _locked_publish_mutex_v1(
    authority_root: str, create: bool
) -> Iterator[ActiveFenceLockV1]:
    witness = None
    registration = None
    entered = False
    resources_context = guarded_active_fence_lock_resources_v1(
        authority_root, create
    )
    try:
        resources = resources_context.__enter__()
        entered = True
        witness, registration = _register_witness(authority_root, resources)
        validate_active_fence_lock_v1(witness)
    except ActiveFenceLockError:
        if entered:
            _release_witness(registration)
            resources_context.__exit__(None, None, None)
        raise
    except (DurableFileError, ExclusiveLockLeaseError, OSError) as exc:
        if entered:
            _release_witness(registration)
            resources_context.__exit__(None, None, None)
        raise ActiveFenceLockError(
            "publisher mutex cannot be acquired"
        ) from exc
    try:
        yield witness
        validate_active_fence_lock_v1(witness)
    finally:
        _release_witness(registration)
        resources_context.__exit__(None, None, None)


@contextlib.contextmanager
def locked_publish_mutex_v1(
    authority_root: str,
) -> Iterator[ActiveFenceLockV1]:
    """Create/acquire the outer mutex; its inode is never unlinked."""
    with _locked_publish_mutex_v1(authority_root, True) as witness:
        yield witness


@contextlib.contextmanager
def locked_existing_publish_mutex_v1(
    authority_root: str,
) -> Iterator[ActiveFenceLockV1]:
    """Acquire the already-created outer mutex without read-side creation."""
    with _locked_publish_mutex_v1(authority_root, False) as witness:
        yield witness
