"""Descriptor-only final closure sweep for materialized generation snapshots."""

from __future__ import annotations

import os
from dataclasses import dataclass

from .generation_reader_fs import (
    GenerationReadError,
    _MUTABLE_DIR,
    _MUTABLE_FILE,
    _SEALED_DIR,
    _SEALED_FILE,
    _OpenSpec,
    _Pinned,
    _Policy,
    _exact_entries,
    _open_at,
    _output_indexes,
    _recheck,
)
from .generation_schema import GenerationManifestRowV1


@dataclass(frozen=True)
class _SnapshotContext:
    policy: _Policy
    names: dict[tuple[str, ...], frozenset[str]]
    leaves: dict[tuple[str, ...], GenerationManifestRowV1]
    snapshots: dict[str, tuple[int, ...]]
    spec: "_SnapshotSpec"


@dataclass(frozen=True)
class _SnapshotSpec:
    directory: _OpenSpec
    file: _OpenSpec
    root_files: frozenset[str]


@dataclass(frozen=True)
class _SnapshotRequest:
    rows: tuple[GenerationManifestRowV1, ...]
    snapshots: dict[str, tuple[int, ...]]
    spec: _SnapshotSpec


def _recheck_leaf(
    parent: _Pinned,
    name: str,
    parts: tuple[str, ...],
    context: _SnapshotContext,
) -> None:
    row = context.leaves[parts]
    opened = _open_at(parent.fd, name, context.spec.file, context.policy)
    try:
        if opened.snapshot != context.snapshots.get(row.path):
            raise GenerationReadError(f"materialized inode changed: {row.path}")
        _recheck(opened)
    finally:
        os.close(opened.fd)


def _recheck_child(
    parent: _Pinned,
    name: str,
    parts: tuple[str, ...],
    context: _SnapshotContext,
) -> None:
    child_parts = parts + (name,)
    if not parts and name in context.spec.root_files:
        return
    if child_parts in context.leaves:
        _recheck_leaf(parent, name, child_parts, context)
        return
    child = _open_at(parent.fd, name, context.spec.directory, context.policy)
    try:
        _recheck_dir(child, child_parts, context)
    finally:
        os.close(child.fd)


def _recheck_dir(
    node: _Pinned, parts: tuple[str, ...], context: _SnapshotContext
) -> None:
    expected = context.names.get(parts, frozenset())
    if not _exact_entries(node.fd, expected):
        raise GenerationReadError("materialized manifest changed after streaming")
    for name in sorted(expected):
        _recheck_child(node, name, parts, context)
    if not _exact_entries(node.fd, expected):
        raise GenerationReadError("materialized closure changed during final sweep")
    _recheck(node)


def recheck_materialized_snapshot(
    root: _Pinned,
    policy: _Policy,
    rows: tuple[GenerationManifestRowV1, ...],
    snapshots: dict[str, tuple[int, ...]],
) -> None:
    """Recheck exact entries and original leaf snapshots without rehashing bytes."""
    request = _SnapshotRequest(rows, snapshots, _MATERIALIZED_SPEC)
    _recheck_snapshot(root, policy, request)


def recheck_sealed_generation_snapshot(
    root: _Pinned,
    policy: _Policy,
    rows: tuple[GenerationManifestRowV1, ...],
    snapshots: dict[str, tuple[int, ...]],
) -> None:
    """Recheck the copied source manifest after all source streams finish."""
    request = _SnapshotRequest(rows, snapshots, _SEALED_SPEC)
    _recheck_snapshot(root, policy, request)


def _recheck_snapshot(
    root: _Pinned,
    policy: _Policy,
    request: _SnapshotRequest,
) -> None:
    names, leaves = _output_indexes(request.rows)
    names = dict(names)
    names[()] = names.get((), frozenset()) | request.spec.root_files
    context = _SnapshotContext(policy, names, leaves, request.snapshots, request.spec)
    _recheck_dir(root, (), context)


_MATERIALIZED_SPEC = _SnapshotSpec(_MUTABLE_DIR, _MUTABLE_FILE, frozenset())
_SEALED_SPEC = _SnapshotSpec(_SEALED_DIR, _SEALED_FILE, frozenset({"commit.json"}))
