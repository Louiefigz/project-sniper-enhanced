"""Exact verification for descriptor-materialized generation closures."""

from __future__ import annotations

import os
from dataclasses import dataclass

from . import generation_reader_fs as reader_fs
from .generation_reader_fs import (
    GenerationReadError,
    _MUTABLE_DIR,
    _MUTABLE_FILE,
    _Pinned,
    _Policy,
    _exact_entries,
    _fresh_pin,
    _open_at,
    _output_indexes,
    _recheck,
)
from .generation_schema import GenerationManifestRowV1
from .generation_snapshot_recheck import recheck_materialized_snapshot


@dataclass
class _OutputContext:
    policy: _Policy
    names: dict[tuple[str, ...], frozenset[str]]
    leaves: dict[tuple[str, ...], GenerationManifestRowV1]
    snapshots: dict[str, tuple[int, ...]]
    root: str
    outputs: dict[str, str]


def _verify_leaf(
    parent: _Pinned, name: str, parts: tuple[str, ...], context: _OutputContext
) -> None:
    row = context.leaves[parts]
    opened = _open_at(parent.fd, name, _MUTABLE_FILE, context.policy)
    try:
        expected = context.snapshots.get(row.path)
        if expected is None or opened.snapshot != expected:
            raise GenerationReadError(
                f"materialized inode changed: {row.path}"
            )
        if reader_fs._stream(opened.fd, None) != (
            row.size_bytes,
            row.sha256,
        ):
            raise GenerationReadError(
                f"materialized bytes changed: {row.path}"
            )
        _recheck(opened)
    finally:
        os.close(opened.fd)
    context.outputs[row.path] = os.path.join(context.root, row.path)


def _verify_child(
    parent: _Pinned, name: str, parts: tuple[str, ...], context: _OutputContext
) -> None:
    child_parts = parts + (name,)
    if child_parts in context.leaves:
        _verify_leaf(parent, name, child_parts, context)
        return
    child = _open_at(parent.fd, name, _MUTABLE_DIR, context.policy)
    try:
        _verify_dir(child, child_parts, context)
    finally:
        os.close(child.fd)


def _verify_dir(
    node: _Pinned, parts: tuple[str, ...], context: _OutputContext
) -> None:
    expected = context.names.get(parts, frozenset())
    if not _exact_entries(node.fd, expected):
        raise GenerationReadError("materialized manifest is not exact closure")
    for name in sorted(expected):
        _verify_child(node, name, parts, context)
    if not _exact_entries(node.fd, expected):
        raise GenerationReadError(
            "materialized closure changed during verification"
        )
    _recheck(node)


def verify_materialized(
    root: _Pinned,
    policy: _Policy,
    rows: tuple[GenerationManifestRowV1, ...],
    snapshots: dict[str, tuple[int, ...]],
) -> dict[str, str]:
    """Reopen and rehash the exact copied closure before exposing any path."""
    expected_paths = {row.path for row in rows}
    if set(snapshots) != expected_paths:
        raise GenerationReadError("materialized inode proof set is incomplete")
    names, leaves = _output_indexes(rows)
    pinned = _fresh_pin(root, policy)
    context = _OutputContext(policy, names, leaves, snapshots, root.name, {})
    _verify_dir(pinned, (), context)
    if set(context.outputs) != expected_paths:
        raise GenerationReadError("materialized output mapping is incomplete")
    recheck_materialized_snapshot(pinned, policy, rows, snapshots)
    return context.outputs
