"""Public selected-CURRENT historical generation resolver."""

from __future__ import annotations

import contextlib
import fcntl
import os
from collections.abc import Iterator
from dataclasses import dataclass

from .generation_reader_fs import (
    GenerationReadError,
    _LOCK_FILE,
    _MUTABLE_DIR,
    _MUTABLE_FILE,
    _Pinned,
    _Policy,
    _open_at,
    _open_root,
    _read_stable,
    _recheck,
    _recheck_safe,
)
from .generation_schema import (
    CurrentPointerV1,
    GenerationSchemaError,
    parse_current_pointer,
)
from .historical_generation_types import HistoricalGenerationMaterializationV1
from .historical_generation_walk import (
    HistoricalGenerationWalkError,
    HistoricalWalkSession,
    walk_selected_ancestry,
)
from .repair_intent import ParentRefV1, RepairIntentError, validate_parent_ref

_CURRENT_LIMIT = 65_536


class HistoricalGenerationResolutionError(RuntimeError):
    """The selected CURRENT ancestry or requested historical target is invalid."""


@dataclass(frozen=True)
class _LockSession:
    root: _Pinned
    destination: _Pinned
    policy: _Policy
    lock: _Pinned
    requested: ParentRefV1


def _validate_request(current: CurrentPointerV1, requested: ParentRefV1) -> None:
    validate_parent_ref(requested)
    valid = (
        requested.authority_id == current.authority_id
        and requested.publication_seq <= current.publication_seq
    )
    if not valid:
        raise HistoricalGenerationResolutionError(
            "requested parent is outside the selected authority ancestry"
        )


def _under_lock(session: _LockSession) -> HistoricalGenerationMaterializationV1:
    fcntl.flock(session.lock.fd, fcntl.LOCK_SH)
    current_file = generations = None
    try:
        _recheck(session.lock)
        current_file = _open_at(
            session.root.fd, "CURRENT", _MUTABLE_FILE, session.policy
        )
        current = parse_current_pointer(_read_stable(current_file, _CURRENT_LIMIT))
        _validate_request(current, session.requested)
        generations = _open_at(
            session.root.fd, "generations", _MUTABLE_DIR, session.policy
        )
        walk = HistoricalWalkSession(
            current,
            session.requested,
            session.destination,
            session.policy,
            generations,
            current_file,
        )
        result = walk_selected_ancestry(walk)
        _recheck(session.lock)
        _recheck(session.root)
        _recheck_safe(session.destination, _MUTABLE_DIR, session.policy)
        return result
    finally:
        for node in (generations, current_file):
            if node is not None:
                os.close(node.fd)
        fcntl.flock(session.lock.fd, fcntl.LOCK_UN)


def _resolve(
    authority_root: str, destination_root: str, requested: ParentRefV1
) -> HistoricalGenerationMaterializationV1:
    root, policy = _open_root(authority_root)
    destination = lock = None
    try:
        destination, destination_policy = _open_root(destination_root)
        if destination_policy != policy or os.listdir(destination.fd):
            raise HistoricalGenerationResolutionError(
                "historical materialization root must be empty and same-device"
            )
        lock = _open_at(root.fd, ".publish.mutex", _LOCK_FILE, policy)
        return _under_lock(_LockSession(root, destination, policy, lock, requested))
    finally:
        for node in (lock, destination, root):
            if node is not None:
                os.close(node.fd)


@contextlib.contextmanager
def resolve_historical_generation(
    authority_root: str,
    destination_root: str,
    requested: ParentRefV1,
) -> Iterator[HistoricalGenerationMaterializationV1]:
    """Materialize an exact ancestor after proving selected ancestry to genesis."""
    try:
        result = _resolve(authority_root, destination_root, requested)
    except HistoricalGenerationResolutionError:
        raise
    except (
        GenerationReadError,
        GenerationSchemaError,
        HistoricalGenerationWalkError,
        RepairIntentError,
    ) as exc:
        raise HistoricalGenerationResolutionError(
            "cannot resolve selected historical ancestry"
        ) from exc
    except (OSError, RuntimeError) as exc:
        raise HistoricalGenerationResolutionError(
            "historical generation validation failed closed"
        ) from exc
    yield result
