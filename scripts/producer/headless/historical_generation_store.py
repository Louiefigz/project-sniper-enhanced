"""Exact source and private-copy stores used by historical resolution."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from .artifact_contract import ArtifactRefV1
from .generation_artifact_store import (
    GenerationArtifactStoreError,
    _assert_snapshot,
    _materialization_root,
    _read_bound,
    _row_for_ref,
)
from .generation_reader import _Tree, _manifest_tree
from .generation_reader_fs import (
    GenerationReadError,
    _Pinned,
    _Policy,
    _SEALED_DIR,
    _SEALED_FILE,
    _exact_entries,
    _open_at,
    _read_stable,
    _recheck,
    _stream,
)
from .generation_schema import GenerationCommitV1, GenerationManifestRowV1


@dataclass(frozen=True)
class HistoricalSourceProofV1:
    """Filesystem identities captured while auditing one sealed generation."""

    generation_id: str
    generation_snapshot: tuple[int, ...]
    directory_snapshots: Mapping[tuple[str, ...], tuple[int, ...]]
    leaf_snapshots: Mapping[str, tuple[int, ...]]


@dataclass
class _AuditContext:
    policy: _Policy
    root_fd: int
    directories: dict[tuple[str, ...], tuple[int, ...]] = field(default_factory=dict)
    leaves: dict[str, tuple[int, ...]] = field(default_factory=dict)


def _expected_names(tree: _Tree, root: bool) -> set[str]:
    expected = set(tree.children)
    if root:
        expected.add("commit.json")
    return expected


def _audit_leaf(
    parent: _Pinned, row: GenerationManifestRowV1, context: _AuditContext
) -> None:
    name = row.path.rsplit("/", 1)[-1]
    opened = _open_at(parent.fd, name, _SEALED_FILE, context.policy)
    try:
        observed = _stream(opened.fd, None)
        if observed != (row.size_bytes, row.sha256):
            raise GenerationReadError(f"historical artifact mismatch: {row.path}")
        _recheck(opened)
        context.leaves[row.path] = opened.snapshot
    finally:
        os.close(opened.fd)


def _audit_tree(
    node: _Pinned, tree: _Tree, parts: tuple[str, ...], context: _AuditContext
) -> None:
    expected = _expected_names(tree, node.fd == context.root_fd)
    if not _exact_entries(node.fd, expected):
        raise GenerationReadError("historical generation closure is not exact")
    context.directories[parts] = node.snapshot
    for name in sorted(tree.children):
        child = tree.children[name]
        if child.row is not None:
            _audit_leaf(node, child.row, context)
            continue
        opened = _open_at(node.fd, name, _SEALED_DIR, context.policy)
        try:
            _audit_tree(opened, child, parts + (name,), context)
        finally:
            os.close(opened.fd)
    if not _exact_entries(node.fd, expected):
        raise GenerationReadError("historical generation changed during audit")
    _recheck(node)


def _assert_tree(
    node: _Pinned,
    tree: _Tree,
    parts: tuple[str, ...],
    store: "HistoricalSourceArtifactStoreV1",
) -> None:
    expected = _expected_names(tree, node.fd == store.root.fd)
    snapshot = store.proof.directory_snapshots.get(parts)
    if node.snapshot != snapshot or not _exact_entries(node.fd, expected):
        raise GenerationReadError("historical directory identity changed")
    for name in sorted(tree.children):
        child = tree.children[name]
        if child.row is not None:
            leaf = _open_at(node.fd, name, _SEALED_FILE, store.policy)
            try:
                if leaf.snapshot != store.proof.leaf_snapshots.get(child.row.path):
                    raise GenerationReadError("historical artifact identity changed")
                _recheck(leaf)
            finally:
                os.close(leaf.fd)
            continue
        opened = _open_at(node.fd, name, _SEALED_DIR, store.policy)
        try:
            _assert_tree(opened, child, parts + (name,), store)
        finally:
            os.close(opened.fd)
    if not _exact_entries(node.fd, expected):
        raise GenerationReadError("historical closure changed after validation")
    _recheck(node)


def _open_relative(
    root: _Pinned, relative: str, policy: _Policy
) -> tuple[_Pinned, tuple[_Pinned, ...]]:
    parents, current = [], root
    try:
        for name in relative.split("/")[:-1]:
            current = _open_at(current.fd, name, _SEALED_DIR, policy)
            parents.append(current)
        leaf = _open_at(current.fd, relative.rsplit("/", 1)[-1], _SEALED_FILE, policy)
        return leaf, tuple(parents)
    except Exception:
        for parent in reversed(parents):
            os.close(parent.fd)
        raise


def _close_relative(leaf: _Pinned, parents: tuple[_Pinned, ...]) -> None:
    os.close(leaf.fd)
    for parent in reversed(parents):
        os.close(parent.fd)


@dataclass(frozen=True)
class HistoricalSourceArtifactStoreV1:
    """Descriptor-safe view over one fully hashed sealed source generation."""

    commit: GenerationCommitV1
    root: _Pinned
    policy: _Policy
    rows: Mapping[str, GenerationManifestRowV1]
    proof: HistoricalSourceProofV1

    @classmethod
    def audit(
        cls, commit: GenerationCommitV1, root: _Pinned, policy: _Policy
    ) -> "HistoricalSourceArtifactStoreV1":
        context = _AuditContext(policy, root.fd)
        _audit_tree(root, _manifest_tree(commit), (), context)
        expected = {row.path for row in commit.files}
        if set(context.leaves) != expected:
            raise GenerationReadError("historical artifact proof is incomplete")
        proof = HistoricalSourceProofV1(
            commit.generation_id,
            root.snapshot,
            MappingProxyType(dict(context.directories)),
            MappingProxyType(dict(context.leaves)),
        )
        rows = MappingProxyType({row.path: row for row in commit.files})
        return cls(commit, root, policy, rows, proof)

    def resolve(self, ref: ArtifactRefV1) -> str:
        row = _row_for_ref(self.rows, ref)
        leaf, parents = _open_relative(self.root, row.path, self.policy)
        try:
            if leaf.snapshot != self.proof.leaf_snapshots[row.path]:
                raise GenerationReadError("historical artifact identity changed")
            _recheck(leaf)
        finally:
            _close_relative(leaf, parents)
        return os.path.join(self.root.name, row.path)

    def read(self, ref: ArtifactRefV1, limit_bytes: int) -> bytes:
        row = _row_for_ref(self.rows, ref)
        if type(limit_bytes) is not int or not 0 < limit_bytes <= 64 * 1024 * 1024:
            raise GenerationReadError("historical artifact read limit is invalid")
        if row.size_bytes > limit_bytes:
            raise GenerationReadError("historical artifact exceeds semantic limit")
        leaf, parents = _open_relative(self.root, row.path, self.policy)
        try:
            if leaf.snapshot != self.proof.leaf_snapshots[row.path]:
                raise GenerationReadError("historical artifact identity changed")
            raw = _read_stable(leaf, limit_bytes)
            if (len(raw), hashlib.sha256(raw).hexdigest()) != (
                row.size_bytes,
                row.sha256,
            ):
                raise GenerationReadError("historical artifact bytes changed")
            return raw
        finally:
            _close_relative(leaf, parents)

    def assert_stable(self) -> None:
        """Reopen the exact closure and reject any post-audit substitution."""
        _assert_tree(self.root, _manifest_tree(self.commit), (), self)


@dataclass(frozen=True)
class HistoricalMaterializedArtifactStoreV1:
    """Exact byte-bound view over the requested private historical copy."""

    commit: GenerationCommitV1
    root: str
    rows: Mapping[str, GenerationManifestRowV1]
    paths: Mapping[str, str]
    snapshots: Mapping[str, tuple[int, ...]]

    @classmethod
    def from_copy(
        cls,
        commit: GenerationCommitV1,
        paths: Mapping[str, str],
        snapshots: Mapping[str, tuple[int, ...]],
    ) -> "HistoricalMaterializedArtifactStoreV1":
        rows = {row.path: row for row in commit.files}
        if set(snapshots) != set(rows):
            raise GenerationArtifactStoreError("historical copy proof is incomplete")
        root = _materialization_root(rows, dict(paths))
        return cls(
            commit,
            root,
            MappingProxyType(rows),
            MappingProxyType(dict(paths)),
            MappingProxyType(dict(snapshots)),
        )

    def resolve(self, ref: ArtifactRefV1) -> str:
        row = _row_for_ref(self.rows, ref)
        path = self.paths[row.path]
        if path != os.path.join(self.root, row.path):
            raise GenerationArtifactStoreError("historical copy path changed")
        _assert_snapshot(path, row, self.snapshots[row.path])
        return path

    def read(self, ref: ArtifactRefV1, limit_bytes: int) -> bytes:
        row = _row_for_ref(self.rows, ref)
        if type(limit_bytes) is not int or not 0 < limit_bytes <= 64 * 1024 * 1024:
            raise GenerationArtifactStoreError("historical read limit is invalid")
        if row.size_bytes > limit_bytes:
            raise GenerationArtifactStoreError("historical artifact is oversized")
        return _read_bound(self.resolve(ref), row, self.snapshots[row.path])
