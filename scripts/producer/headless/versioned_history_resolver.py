"""Descriptor-pinned disk resolver for recursive selected versioned history."""

from __future__ import annotations

import fcntl
import os
from dataclasses import dataclass, field

from .generation_reader_fs import (
    GenerationReadError,
    _LOCK_FILE,
    _MUTABLE_DIR,
    _MUTABLE_FILE,
    _SEALED_DIR,
    _SEALED_FILE,
    _Pinned,
    _Policy,
    _open_at,
    _open_root,
    _read_stable,
    _recheck,
)
from .generation_schema import (
    CurrentPointerV1,
    GenerationCommitV1,
    GenerationSchemaError,
    parse_current_pointer,
    parse_generation_commit,
)
from .historical_generation_store import HistoricalSourceArtifactStoreV1
from .repair_intent import ParentRefV1
from .versioned_generation_profile_dispatch import select_versioned_generation_profile
from .versioned_history_binding import bind_versioned_selected_history
from .versioned_history_node import load_versioned_history_node
from .versioned_history_types import (
    GenesisHistoryAuthorityV1,
    VersionedHistoryBindingInputsV1,
    VersionedHistoryNodeV1,
    VersionedSelectedHistoryError,
    VersionedSelectedHistoryReportV1,
)

_CURRENT_LIMIT = 65_536
_COMMIT_LIMIT = 16 * 1024 * 1024


@dataclass(frozen=True)
class _ExpectedNode:
    authority_id: str
    publication_seq: int
    generation_id: str
    commit_digest: str
    plan_digest: str | None


@dataclass
class _OpenNode:
    generation: _Pinned
    commit_file: _Pinned
    commit_raw: bytes
    store: HistoricalSourceArtifactStoreV1
    node: VersionedHistoryNodeV1


@dataclass
class _WalkContext:
    current: CurrentPointerV1
    current_raw: bytes
    current_file: _Pinned
    generations: _Pinned
    policy: _Policy
    opened: list[_OpenNode] = field(default_factory=list)
    seen_generations: set[str] = field(default_factory=set)
    seen_commits: set[str] = field(default_factory=set)


def _expected(value: CurrentPointerV1 | ParentRefV1) -> _ExpectedNode:
    plan_digest = value.plan_digest if type(value) is ParentRefV1 else None
    return _ExpectedNode(
        value.authority_id,
        value.publication_seq,
        value.generation_id,
        value.commit_digest,
        plan_digest,
    )


def _bind_commit(expected: _ExpectedNode, commit: GenerationCommitV1) -> None:
    actual = (commit.authority_id, commit.generation_id, commit.commit_digest)
    required = (expected.authority_id, expected.generation_id, expected.commit_digest)
    if actual != required:
        raise VersionedSelectedHistoryError(
            "selected child-signed identity differs from opened generation"
        )


def _open_node(context: _WalkContext, expected: _ExpectedNode) -> _OpenNode:
    if (
        expected.generation_id in context.seen_generations
        or expected.commit_digest in context.seen_commits
    ):
        raise VersionedSelectedHistoryError("selected versioned history has a cycle")
    generation = _open_at(
        context.generations.fd,
        expected.generation_id,
        _SEALED_DIR,
        context.policy,
    )
    commit_file = None
    try:
        commit_file = _open_at(
            generation.fd, "commit.json", _SEALED_FILE, context.policy
        )
        raw = _read_stable(commit_file, _COMMIT_LIMIT)
        commit = parse_generation_commit(raw)
        _bind_commit(expected, commit)
        select_versioned_generation_profile(commit)
        store = HistoricalSourceArtifactStoreV1.audit(
            commit, generation, context.policy
        )
        node = load_versioned_history_node(commit, store, expected.publication_seq)
        if (
            expected.plan_digest is not None
            and node.ref.plan_digest != expected.plan_digest
        ):
            raise VersionedSelectedHistoryError("selected parent plan digest is stale")
        return _OpenNode(generation, commit_file, raw, store, node)
    except Exception:
        if commit_file is not None:
            os.close(commit_file.fd)
        os.close(generation.fd)
        raise


def _next(node: VersionedHistoryNodeV1) -> ParentRefV1 | None:
    parent = node.commit.expected_parent
    if parent is None:
        valid = (
            node.ref.publication_seq == 1
            and type(node.authority) is GenesisHistoryAuthorityV1
        )
        if not valid:
            raise VersionedSelectedHistoryError(
                "selected versioned history has the wrong genesis tail"
            )
        return None
    if parent.generation_id == node.ref.generation_id:
        raise VersionedSelectedHistoryError("selected versioned history has a cycle")
    valid = (
        node.ref.publication_seq > 1
        and parent.authority_id == node.ref.authority_id
        and parent.publication_seq == node.ref.publication_seq - 1
    )
    if not valid:
        raise VersionedSelectedHistoryError(
            "selected versioned history has a sequence gap"
        )
    return parent


def _walk(context: _WalkContext) -> None:
    expected = _expected(context.current)
    while True:
        opened = _open_node(context, expected)
        context.opened.append(opened)
        context.seen_generations.add(opened.node.ref.generation_id)
        context.seen_commits.add(opened.node.ref.commit_digest)
        parent = _next(opened.node)
        if parent is None:
            return
        expected = _expected(parent)


def _revalidate(context: _WalkContext) -> None:
    for opened in context.opened:
        if _read_stable(opened.commit_file, _COMMIT_LIMIT) != opened.commit_raw:
            raise VersionedSelectedHistoryError("selected history commit changed")
        opened.store.assert_stable()
        _recheck(opened.generation)
    raw = _read_stable(context.current_file, _CURRENT_LIMIT)
    if raw != context.current_raw or parse_current_pointer(raw) != context.current:
        raise VersionedSelectedHistoryError("CURRENT changed during history proof")
    _recheck(context.generations)


def _close(opened: list[_OpenNode]) -> None:
    for node in reversed(opened):
        os.close(node.commit_file.fd)
        os.close(node.generation.fd)


def _resolve_locked(root: _Pinned, policy: _Policy) -> VersionedSelectedHistoryReportV1:
    current_file = generations = None
    opened: list[_OpenNode] = []
    try:
        current_file = _open_at(root.fd, "CURRENT", _MUTABLE_FILE, policy)
        current_raw = _read_stable(current_file, _CURRENT_LIMIT)
        current = parse_current_pointer(current_raw)
        generations = _open_at(root.fd, "generations", _MUTABLE_DIR, policy)
        context = _WalkContext(
            current, current_raw, current_file, generations, policy, opened
        )
        _walk(context)
        report = bind_versioned_selected_history(
            VersionedHistoryBindingInputsV1(
                current, tuple(item.node for item in context.opened)
            )
        )
        _revalidate(context)
        return report
    finally:
        _close(opened)
        for value in (generations, current_file):
            if value is not None:
                os.close(value.fd)


def _under_lock(
    root: _Pinned, policy: _Policy, lock: _Pinned
) -> VersionedSelectedHistoryReportV1:
    fcntl.flock(lock.fd, fcntl.LOCK_SH)
    try:
        _recheck(lock)
        report = _resolve_locked(root, policy)
        _recheck(lock)
        _recheck(root)
        return report
    finally:
        fcntl.flock(lock.fd, fcntl.LOCK_UN)


def resolve_versioned_selected_history(
    authority_root: str,
) -> VersionedSelectedHistoryReportV1:
    """Authenticate the full selected chain and return no paths or capabilities."""
    root = lock = None
    try:
        root, policy = _open_root(authority_root)
        lock = _open_at(root.fd, ".publish.mutex", _LOCK_FILE, policy)
        return _under_lock(root, policy, lock)
    except VersionedSelectedHistoryError:
        raise
    except (GenerationReadError, GenerationSchemaError, OSError, RuntimeError) as exc:
        raise VersionedSelectedHistoryError(
            "cannot resolve recursive selected versioned history"
        ) from exc
    finally:
        for value in (lock, root):
            if value is not None:
                os.close(value.fd)
