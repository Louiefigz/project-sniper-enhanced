"""Descriptor-relative staging copy for trusted generation sealing."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass, field

from .generation_reader import _Tree, _manifest_tree
from .generation_reader_fs import (
    GenerationReadError,
    _MUTABLE_DIR,
    _MUTABLE_FILE,
    _Pinned,
    _Policy,
    _exact_entries,
    _fresh_pin,
    _new_output,
    _new_output_dir,
    _open_at,
    _open_root,
    _recheck,
    _recheck_safe,
    _snapshot,
    _write_chunk,
)
from .generation_schema import GenerationCommitV1, GenerationManifestRowV1
from .generation_sealer_types import PENDING_INTENT_NAME


@dataclass
class _CopyContext:
    source_policy: _Policy
    output_policy: _Policy
    output_root_fd: int
    source_snapshots: dict[str, tuple[int, ...]] = field(default_factory=dict)
    output_snapshots: dict[str, tuple[int, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class _VerifyContext:
    policy: _Policy
    snapshots: dict[str, tuple[int, ...]]
    root_fd: int
    root_extra: str | None = None


def _precheck_type(parent_fd: int, name: str, directory: bool) -> None:
    info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    expected = (
        stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    )
    if not expected:
        raise GenerationReadError(f"staging node has unsafe type: {name}")


def _bounded_stream(
    source_fd: int, output_fd: int | None, expected_size: int
) -> tuple[int, str]:
    os.lseek(source_fd, 0, os.SEEK_SET)
    digest, total = hashlib.sha256(), 0
    while total < expected_size:
        chunk = os.read(source_fd, min(1024 * 1024, expected_size - total))
        if not chunk:
            break
        digest.update(chunk)
        total += len(chunk)
        if output_fd is not None:
            _write_chunk(output_fd, chunk)
    if os.read(source_fd, 1):
        total += 1
    return total, digest.hexdigest()


def _copy_leaf(
    source: _Pinned,
    output: _Pinned,
    row: GenerationManifestRowV1,
    context: _CopyContext,
) -> None:
    name = row.path.rsplit("/", 1)[-1]
    _precheck_type(source.fd, name, False)
    opened = _open_at(source.fd, name, _MUTABLE_FILE, context.source_policy)
    output_fd = None
    try:
        if opened.snapshot[5] != row.size_bytes:
            raise GenerationReadError(f"staging size mismatch: {row.path}")
        output_fd = _new_output(output.fd, name, context.output_policy)
        observed = _bounded_stream(opened.fd, output_fd, row.size_bytes)
        if observed != (row.size_bytes, row.sha256):
            raise GenerationReadError(f"staging bytes mismatch: {row.path}")
        os.fsync(output_fd)
        _recheck(opened)
        output_info = os.fstat(output_fd)
        context.source_snapshots[row.path] = opened.snapshot
        context.output_snapshots[row.path] = _snapshot(output_info)
    finally:
        if output_fd is not None:
            os.close(output_fd)
        os.close(opened.fd)
    os.fsync(output.fd)


def _copy_child(
    source: _Pinned,
    output: _Pinned,
    entry: tuple[str, _Tree],
    context: _CopyContext,
) -> None:
    name, child = entry
    if child.row is not None:
        _copy_leaf(source, output, child.row, context)
        return
    _precheck_type(source.fd, name, True)
    source_child = _open_at(
        source.fd, name, _MUTABLE_DIR, context.source_policy
    )
    output_child = None
    try:
        output_child = _new_output_dir(output.fd, name, context.output_policy)
        os.fsync(output.fd)
        _copy_tree(source_child, output_child, child, context)
    finally:
        if output_child is not None:
            os.close(output_child.fd)
        os.close(source_child.fd)


def _copy_tree(
    source: _Pinned, output: _Pinned, tree: _Tree, context: _CopyContext
) -> None:
    expected = set(tree.children)
    if not _exact_entries(source.fd, expected):
        raise GenerationReadError(
            "staging tree is not the exact manifest closure"
        )
    for name in sorted(expected):
        _copy_child(source, output, (name, tree.children[name]), context)
    if not _exact_entries(source.fd, expected):
        raise GenerationReadError("staging tree changed while copying")
    output_expected = set(expected)
    if output.fd == context.output_root_fd:
        output_expected.add(PENDING_INTENT_NAME)
    if not _exact_entries(output.fd, output_expected):
        raise GenerationReadError(
            "pending tree is not the exact manifest closure"
        )
    _recheck(source)
    _recheck_safe(output, _MUTABLE_DIR, context.output_policy)
    os.fsync(output.fd)


def _verify_leaf(
    node: _Pinned,
    row: GenerationManifestRowV1,
    context: _VerifyContext,
) -> None:
    name = row.path.rsplit("/", 1)[-1]
    _precheck_type(node.fd, name, False)
    opened = _open_at(node.fd, name, _MUTABLE_FILE, context.policy)
    try:
        if opened.snapshot != context.snapshots.get(row.path):
            raise GenerationReadError(
                f"generation source inode changed: {row.path}"
            )
        observed = _bounded_stream(opened.fd, None, row.size_bytes)
        if observed != (row.size_bytes, row.sha256):
            raise GenerationReadError(
                f"generation source bytes changed: {row.path}"
            )
        _recheck(opened)
    finally:
        os.close(opened.fd)


def _verify_child(
    node: _Pinned,
    entry: tuple[str, _Tree],
    context: _VerifyContext,
) -> None:
    name, child = entry
    if child.row is not None:
        _verify_leaf(node, child.row, context)
        return
    _precheck_type(node.fd, name, True)
    opened = _open_at(node.fd, name, _MUTABLE_DIR, context.policy)
    try:
        _verify_tree(opened, child, context)
    finally:
        os.close(opened.fd)


def _verify_tree(
    node: _Pinned,
    tree: _Tree,
    context: _VerifyContext,
) -> None:
    children = set(tree.children)
    expected = set(children)
    if node.fd == context.root_fd and context.root_extra is not None:
        expected.add(context.root_extra)
    if not _exact_entries(node.fd, expected):
        raise GenerationReadError("generation tree changed after copy")
    for name in sorted(children):
        _verify_child(node, (name, tree.children[name]), context)
    if not _exact_entries(node.fd, expected):
        raise GenerationReadError("generation tree changed during final sweep")
    _recheck(node)


def copy_staging_payload(
    staging_root: str,
    pending: _Pinned,
    output_policy: _Policy,
    commit: GenerationCommitV1,
) -> None:
    """Copy, re-open, and rehash one exact mutable staging closure."""
    source, source_policy = _open_root(staging_root)
    tree = _manifest_tree(commit)
    context = _CopyContext(source_policy, output_policy, pending.fd)
    try:
        _copy_tree(source, pending, tree, context)
        _verify_tree(
            source,
            tree,
            _VerifyContext(source_policy, context.source_snapshots, source.fd),
        )
        output = _fresh_pin(pending, output_policy)
        _verify_tree(
            output,
            tree,
            _VerifyContext(
                output_policy,
                context.output_snapshots,
                output.fd,
                PENDING_INTENT_NAME,
            ),
        )
        expected = {row.path for row in commit.files}
        if set(context.source_snapshots) != expected:
            raise GenerationReadError("staging copy proof is incomplete")
        _recheck(source)
        _recheck_safe(pending, _MUTABLE_DIR, output_policy)
    finally:
        os.close(source.fd)
