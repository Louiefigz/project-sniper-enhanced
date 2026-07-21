"""Pinned, fail-closed reader for one published immutable generation."""

from __future__ import annotations

import contextlib
import fcntl
import os
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from .generation_profile import (
    GenerationProfileError,
    verify_r0_generation_profile,
)
from .generation_manifest_tree import _Tree, manifest_tree as _manifest_tree
from .generation_reader_fs import (
    GenerationReadError,
    _LOCK_FILE,
    _MUTABLE_DIR,
    _MUTABLE_FILE,
    _SEALED_DIR,
    _SEALED_FILE,
    _Pinned,
    _Policy,
    _exact_entries,
    _new_output,
    _new_output_dir,
    _open_at,
    _open_root,
    _read_stable,
    _recheck,
    _recheck_safe,
    _snapshot,
    _stream,
)
from .generation_materialized_verification import verify_materialized
from .generation_snapshot_recheck import recheck_sealed_generation_snapshot
from .generation_schema import (
    CurrentPointerV1,
    GenerationCommitV1,
    GenerationManifestRowV1,
    GenerationSchemaError,
    parse_current_pointer,
    parse_generation_commit,
)

_CURRENT_LIMIT = 65_536
_COMMIT_LIMIT = 16 * 1024 * 1024


@dataclass(frozen=True)
class ResolvedGenerationV1:
    """One pinned commit and private copies of its complete manifest."""

    current: CurrentPointerV1
    commit: GenerationCommitV1
    materialized: Mapping[str, str]
    materialized_snapshots: Mapping[str, tuple[int, ...]]


@dataclass
class _WalkContext:
    policy: _Policy
    root_source_fd: int
    snapshots: dict[str, tuple[int, ...]] = field(default_factory=dict)
    source_snapshots: dict[str, tuple[int, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class _ReaderConfig:
    policy: _Policy
    validate_profile: Callable[[CurrentPointerV1, GenerationCommitV1], object]


def _copy_opened(
    source: _Pinned,
    output_fd: int,
    row: GenerationManifestRowV1,
    destination_dir: int,
) -> tuple[int, ...]:
    if source.snapshot[5] != row.size_bytes:
        raise GenerationReadError(f"manifest size mismatch: {row.path}")
    if _stream(source.fd, output_fd) != (row.size_bytes, row.sha256):
        raise GenerationReadError(f"manifest bytes mismatch: {row.path}")
    os.fsync(output_fd)
    _recheck(source)
    if _stream(source.fd, None) != (row.size_bytes, row.sha256):
        raise GenerationReadError(f"manifest bytes changed: {row.path}")
    if _stream(output_fd, None) != (row.size_bytes, row.sha256):
        raise GenerationReadError(f"materialized bytes mismatch: {row.path}")
    _recheck(source)
    output = _Pinned(
        output_fd,
        destination_dir,
        row.path.rsplit("/", 1)[-1],
        _snapshot(os.fstat(output_fd)),
    )
    _recheck(output)
    return output.snapshot


def _copy_row(
    source_dir: int,
    destination_dir: int,
    row: GenerationManifestRowV1,
    context: _WalkContext,
) -> None:
    name = row.path.rsplit("/", 1)[-1]
    source = _open_at(source_dir, name, _SEALED_FILE, context.policy)
    try:
        output_fd = _new_output(destination_dir, name, context.policy)
        try:
            snapshot = _copy_opened(source, output_fd, row, destination_dir)
        finally:
            os.close(output_fd)
    finally:
        os.close(source.fd)
    context.snapshots[row.path] = snapshot
    context.source_snapshots[row.path] = source.snapshot


def _open_output_child(
    source: _Pinned, destination: _Pinned, name: str, context: _WalkContext
) -> tuple[_Pinned, _Pinned]:
    source_child = _open_at(source.fd, name, _SEALED_DIR, context.policy)
    try:
        destination_child = _new_output_dir(
            destination.fd, name, context.policy
        )
    except Exception:
        os.close(source_child.fd)
        raise
    return source_child, destination_child


def _walk(
    source: _Pinned, destination: _Pinned, tree: _Tree, context: _WalkContext
) -> None:
    source_expected = set(tree.children)
    if source.fd == context.root_source_fd:
        source_expected.add("commit.json")
    if not _exact_entries(source.fd, source_expected):
        raise GenerationReadError("generation manifest is not exact closure")
    for name in sorted(tree.children):
        child = tree.children[name]
        if child.row is not None:
            _copy_row(source.fd, destination.fd, child.row, context)
            continue
        source_child, destination_child = _open_output_child(
            source, destination, name, context
        )
        try:
            _walk(source_child, destination_child, child, context)
            _recheck(source_child)
            _recheck_safe(destination_child, _MUTABLE_DIR, context.policy)
        finally:
            os.close(source_child.fd)
            os.close(destination_child.fd)
    if not _exact_entries(source.fd, source_expected):
        raise GenerationReadError("generation closure changed while reading")
    if not _exact_entries(destination.fd, set(tree.children)):
        raise GenerationReadError("materialized closure is not exact")
    _recheck(source)


def _validate_binding(
    current: CurrentPointerV1, commit: GenerationCommitV1
) -> None:
    observed = (
        commit.authority_id,
        commit.generation_id,
        commit.commit_digest,
    )
    expected = (
        current.authority_id,
        current.generation_id,
        current.commit_digest,
    )
    if observed != expected:
        raise GenerationReadError(
            "CURRENT does not bind the opened generation"
        )


def _close_nodes(nodes: tuple[_Pinned | None, ...]) -> None:
    for node in nodes:
        if node is not None:
            os.close(node.fd)


def _resolve_locked(
    root: _Pinned, destination: _Pinned, config: _ReaderConfig
) -> tuple[CurrentPointerV1, GenerationCommitV1, dict[str, tuple[int, ...]]]:
    policy = config.policy
    current_file = _open_at(root.fd, "CURRENT", _MUTABLE_FILE, policy)
    generations = generation = commit_file = None
    try:
        current_raw = _read_stable(current_file, _CURRENT_LIMIT)
        current = parse_current_pointer(current_raw)
        generations = _open_at(root.fd, "generations", _MUTABLE_DIR, policy)
        generation = _open_at(
            generations.fd, current.generation_id, _SEALED_DIR, policy
        )
        commit_file = _open_at(
            generation.fd, "commit.json", _SEALED_FILE, policy
        )
        commit_raw = _read_stable(commit_file, _COMMIT_LIMIT)
        commit = parse_generation_commit(commit_raw)
        _validate_binding(current, commit)
        config.validate_profile(current, commit)
        context = _WalkContext(policy, generation.fd)
        _walk(generation, destination, _manifest_tree(commit), context)
        recheck_sealed_generation_snapshot(
            generation, policy, commit.files, context.source_snapshots
        )
        if _read_stable(commit_file, _COMMIT_LIMIT) != commit_raw:
            raise GenerationReadError(
                "generation commit changed while reading"
            )
        if _read_stable(current_file, _CURRENT_LIMIT) != current_raw:
            raise GenerationReadError("CURRENT changed while reading")
        _recheck(generation)
        _recheck(generations)
        return current, commit, context.snapshots
    finally:
        _close_nodes((commit_file, generation, generations, current_file))


def _under_flock(
    root: _Pinned, destination: _Pinned, config: _ReaderConfig, lock: _Pinned
) -> ResolvedGenerationV1:
    fcntl.flock(lock.fd, fcntl.LOCK_SH)
    try:
        _recheck(lock)
        current, commit, snapshots = _resolve_locked(root, destination, config)
        _recheck(lock)
        _recheck(root)
        _recheck_safe(destination, _MUTABLE_DIR, config.policy)
        outputs = verify_materialized(
            destination, config.policy, commit.files, snapshots
        )
        return ResolvedGenerationV1(
            current,
            commit,
            MappingProxyType(dict(sorted(outputs.items()))),
            MappingProxyType(dict(sorted(snapshots.items()))),
        )
    finally:
        fcntl.flock(lock.fd, fcntl.LOCK_UN)


def _resolve(
    authority_root: str,
    destination_root: str,
    validate_profile: Callable[[CurrentPointerV1, GenerationCommitV1], object],
) -> ResolvedGenerationV1:
    root, policy = _open_root(authority_root)
    destination = lock = None
    try:
        destination, destination_policy = _open_root(destination_root)
        destination_empty = _exact_entries(destination.fd, set())
        if destination_policy != policy or not destination_empty:
            raise GenerationReadError(
                "materialization must be empty and on the authority device"
            )
        lock = _open_at(root.fd, ".publish.mutex", _LOCK_FILE, policy)
        return _under_flock(
            root, destination, _ReaderConfig(policy, validate_profile), lock
        )
    finally:
        _close_nodes((lock, destination, root))


@contextlib.contextmanager
def read_current_generation(
    authority_root: str, destination_root: str
) -> Iterator[ResolvedGenerationV1]:
    """Copy one exact published generation under its flock, then release it."""
    try:
        resolved = _resolve(
            authority_root, destination_root, _verify_legacy_r0
        )
    except GenerationReadError:
        raise
    except (OSError, GenerationProfileError, GenerationSchemaError) as exc:
        raise GenerationReadError(
            "cannot resolve the published generation"
        ) from exc
    yield resolved


def _verify_legacy_r0(
    _current: CurrentPointerV1, commit: GenerationCommitV1
) -> object:
    return verify_r0_generation_profile(commit)
