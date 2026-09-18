"""Byte-bound access to one materialized immutable generation snapshot."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .artifact_contract import (
    ArtifactContractError,
    ArtifactRefV1,
    validate_artifact_ref,
)
from .generation_reader import ResolvedGenerationV1
from .generation_schema import (
    GenerationManifestRowV1,
    parse_current_pointer,
    parse_generation_commit,
)
from .wire_identity import same_wire_value

_CLOSE_ON_EXEC = getattr(os, "O_CLOEXEC", 0)
_NO_FOLLOW = getattr(os, "O_NOFOLLOW", 0)


class GenerationArtifactStoreError(RuntimeError):
    """A materialized artifact was forged, replaced, or addressed ambiguously."""


@dataclass(frozen=True)
class GenerationArtifactStoreV1:
    """Exact manifest refs and paths scoped to one private materialization root."""

    generation: ResolvedGenerationV1
    root: str
    _rows: Mapping[str, GenerationManifestRowV1]
    _paths: Mapping[str, str]
    _snapshots: Mapping[str, tuple[int, ...]]

    @classmethod
    def from_resolved(
        cls, generation: ResolvedGenerationV1
    ) -> "GenerationArtifactStoreV1":
        """Revalidate wire identities and derive one exact snapshot root."""
        _validate_generation(generation)
        rows = {row.path: row for row in generation.commit.files}
        paths = dict(generation.materialized)
        root = _materialization_root(rows, paths)
        return cls(
            generation,
            root,
            MappingProxyType(rows),
            MappingProxyType(paths),
            MappingProxyType(dict(generation.materialized_snapshots)),
        )

    def ref_for_row(self, row: GenerationManifestRowV1) -> ArtifactRefV1:
        """Convert one exact row from this store into a typed artifact ref."""
        selected = self._rows.get(row.path)
        if selected != row:
            raise GenerationArtifactStoreError("manifest row is not in this snapshot")
        return ArtifactRefV1(row.path, row.sha256, row.size_bytes)

    def resolve(self, ref: ArtifactRefV1) -> str:
        """Resolve only an exact manifest ref; consumers must reopen safely."""
        row = _row_for_ref(self._rows, ref)
        path = self._paths[row.path]
        expected = os.path.join(self.root, row.path)
        if path != expected or os.path.realpath(path) != path:
            raise GenerationArtifactStoreError("materialized artifact path changed")
        _assert_snapshot(path, row, self._snapshots[row.path])
        return path

    def read(self, ref: ArtifactRefV1, limit_bytes: int) -> bytes:
        """Read and rehash one stable, owned, single-link manifest artifact."""
        if type(limit_bytes) is not int or not 0 < limit_bytes <= 64 * 1024 * 1024:
            raise GenerationArtifactStoreError("artifact read limit is invalid")
        row = _row_for_ref(self._rows, ref)
        if row.size_bytes > limit_bytes:
            raise GenerationArtifactStoreError("artifact exceeds its semantic limit")
        return _read_bound(self.resolve(ref), row, self._snapshots[row.path])


def _validate_generation(value: object) -> None:
    if type(value) is not ResolvedGenerationV1:
        raise GenerationArtifactStoreError("resolved generation instance is invalid")
    try:
        current = parse_current_pointer(value.current.document_json)
        commit = parse_generation_commit(value.commit.document_json)
    except RuntimeError as exc:
        raise GenerationArtifactStoreError("resolved wire bytes are invalid") from exc
    expected = (current.authority_id, current.generation_id, current.commit_digest)
    observed = (commit.authority_id, commit.generation_id, commit.commit_digest)
    valid = (
        same_wire_value(value.current, current)
        and same_wire_value(value.commit, commit)
        and expected == observed
    )
    expected_paths = {row.path for row in commit.files}
    proofs = value.materialized_snapshots
    snapshots_valid = set(proofs) == expected_paths and all(
        type(snapshot) is tuple
        and len(snapshot) == 8
        and all(type(item) is int for item in snapshot)
        for snapshot in proofs.values()
    )
    if not valid or set(value.materialized) != expected_paths or not snapshots_valid:
        raise GenerationArtifactStoreError("resolved generation identity is invalid")


def _root_from(path: str, relative: str) -> str:
    root = path
    for _part in relative.split("/"):
        root = os.path.dirname(root)
    return root


def _safe_root(path: str) -> bool:
    try:
        info = os.stat(path, follow_symlinks=False)
    except OSError:
        return False
    return (
        os.path.isabs(path)
        and os.path.realpath(path) == path
        and stat.S_ISDIR(info.st_mode)
        and stat.S_IMODE(info.st_mode) == 0o700
        and info.st_uid == os.geteuid()
    )


def _materialization_root(rows: dict, paths: dict) -> str:
    if not rows or set(rows) != set(paths):
        raise GenerationArtifactStoreError("materialized path set is incomplete")
    roots = {_root_from(paths[name], name) for name in rows}
    if len(roots) != 1:
        raise GenerationArtifactStoreError("materialized paths cross snapshot roots")
    root = roots.pop()
    exact = all(paths[name] == os.path.join(root, name) for name in rows)
    if not exact or not _safe_root(root):
        raise GenerationArtifactStoreError("materialization root is unsafe")
    return root


def _row_for_ref(
    rows: Mapping[str, GenerationManifestRowV1], ref: ArtifactRefV1
) -> GenerationManifestRowV1:
    try:
        validate_artifact_ref(ref)
    except ArtifactContractError as exc:
        raise GenerationArtifactStoreError(str(exc)) from exc
    row = rows.get(ref.relative_path)
    expected = (ref.relative_path, ref.sha256, ref.size_bytes)
    actual = None if row is None else (row.path, row.sha256, row.size_bytes)
    if actual != expected:
        raise GenerationArtifactStoreError("artifact ref does not match the manifest")
    return row


def _snapshot(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_uid,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _safe_file(info: os.stat_result, row: GenerationManifestRowV1) -> bool:
    return (
        stat.S_ISREG(info.st_mode)
        and stat.S_IMODE(info.st_mode) == 0o600
        and info.st_nlink == 1
        and info.st_uid == os.geteuid()
        and info.st_size == row.size_bytes
    )


def _assert_snapshot(
    path: str, row: GenerationManifestRowV1, expected: tuple[int, ...]
) -> None:
    try:
        info = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise GenerationArtifactStoreError("artifact path changed") from exc
    if not _safe_file(info, row) or _snapshot(info) != expected:
        raise GenerationArtifactStoreError(
            "artifact inode changed after materialization"
        )


def _read_fd(fd: int, size: int) -> tuple[bytes, str]:
    chunks, digest, total = [], hashlib.sha256(), 0
    while total < size:
        chunk = os.read(fd, min(1024 * 1024, size - total))
        if not chunk:
            break
        chunks.append(chunk)
        digest.update(chunk)
        total += len(chunk)
    extra = os.read(fd, 1)
    if total != size or extra:
        raise GenerationArtifactStoreError("artifact length changed while reading")
    return b"".join(chunks), digest.hexdigest()


def _read_bound(
    path: str, row: GenerationManifestRowV1, expected: tuple[int, ...]
) -> bytes:
    flags = os.O_RDONLY | os.O_NONBLOCK | _NO_FOLLOW | _CLOSE_ON_EXEC
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise GenerationArtifactStoreError(
            "artifact could not be opened safely"
        ) from exc
    try:
        before = os.fstat(fd)
        path_before = os.stat(path, follow_symlinks=False)
        before_valid = _snapshot(before) == _snapshot(path_before) == expected
        if not _safe_file(before, row) or not before_valid:
            raise GenerationArtifactStoreError("artifact inode is unsafe")
        raw, digest = _read_fd(fd, row.size_bytes)
        after = os.fstat(fd)
        path_after = os.stat(path, follow_symlinks=False)
        stable = _snapshot(before) == _snapshot(after) == _snapshot(path_after)
        if not stable or digest != row.sha256:
            raise GenerationArtifactStoreError("artifact changed or mismatched")
        return raw
    except OSError as exc:
        raise GenerationArtifactStoreError("artifact changed while reading") from exc
    finally:
        os.close(fd)
