"""Durable pending-tree sealing and non-publishing generation installation."""

from __future__ import annotations

import ctypes
import errno
import os
import stat
from dataclasses import dataclass

from .durable_files import bounded_directory_entries
from .generation_reader import _Tree, _manifest_tree
from .generation_reader_fs import (
    GenerationReadError,
    _MUTABLE_DIR,
    _MUTABLE_FILE,
    _Pinned,
    _Policy,
    _SEALED_DIR,
    _SEALED_FILE,
    _new_output,
    _new_output_dir,
    _open_at,
    _read_stable,
    _snapshot,
    _write_chunk,
)
from .generation_schema import GenerationCommitV1
from .generation_sealer_cleanup import cleanup_pending, pending_name
from .generation_sealer_types import (
    MAX_COMMIT_BYTES,
    PENDING_INTENT_NAME,
    PENDING_INTENT_TEMP_NAME,
    GenerationSealError,
)
from .historical_generation_store import HistoricalSourceArtifactStoreV1


@dataclass(frozen=True)
class _SealContext:
    policy: _Policy
    root: _Pinned


def open_generation_parent(root: _Pinned, policy: _Policy) -> _Pinned:
    """Create or safely open the mutable generation namespace."""
    try:
        opened = _new_output_dir(root.fd, "generations", policy)
        os.fsync(root.fd)
        return opened
    except FileExistsError:
        return _open_at(root.fd, "generations", _MUTABLE_DIR, policy)


def verify_named_generation(
    generations: _Pinned, name: str, commit: GenerationCommitV1
) -> tuple[int, ...]:
    """Re-open and hash one exact sealed generation without publishing it."""
    opened = _open_at(generations.fd, name, _SEALED_DIR, _policy(generations))
    commit_file = None
    try:
        _preflight_sealed_tree(
            opened, _manifest_tree(commit), _policy(opened), True
        )
        commit_file = _open_at(
            opened.fd, "commit.json", _SEALED_FILE, _policy(opened)
        )
        raw = _read_stable(commit_file, MAX_COMMIT_BYTES)
        if raw != commit.document_json:
            raise GenerationSealError(
                "generation ID collision or equivocation"
            )
        store = HistoricalSourceArtifactStoreV1.audit(
            commit, opened, _policy(opened)
        )
        store.assert_stable()
        if _read_stable(commit_file, MAX_COMMIT_BYTES) != raw:
            raise GenerationSealError("sealed generation commit changed")
        return opened.snapshot
    finally:
        if commit_file is not None:
            os.close(commit_file.fd)
        os.close(opened.fd)


def existing_generation(
    generations: _Pinned, commit: GenerationCommitV1
) -> bool:
    """Return true only for an exact, fully reverified replay target."""
    try:
        verify_named_generation(generations, commit.generation_id, commit)
        return True
    except FileNotFoundError:
        try:
            os.stat(
                commit.generation_id,
                dir_fd=generations.fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return False
        raise GenerationSealError("generation ID collision is incomplete")


def recover_sealed_pending(
    generations: _Pinned, commit: GenerationCommitV1, policy: _Policy
) -> _Pinned | None:
    """Return one exact sealed crash residue without rereading staging."""
    name = pending_name(commit.generation_id)
    try:
        verify_named_generation(generations, name, commit)
    except (FileNotFoundError, GenerationReadError):
        return None
    return _open_at(generations.fd, name, _SEALED_DIR, policy)


def _policy(node: _Pinned) -> _Policy:
    info = os.fstat(node.fd)
    return _Policy(info.st_dev, os.geteuid())


def _preflight_sealed_child(
    node: _Pinned, entry: tuple[str, _Tree], policy: _Policy
) -> None:
    name, child = entry
    info = os.stat(name, dir_fd=node.fd, follow_symlinks=False)
    if child.row is not None:
        if not stat.S_ISREG(info.st_mode):
            raise GenerationSealError("sealed generation has unsafe node type")
        return
    if not stat.S_ISDIR(info.st_mode):
        raise GenerationSealError("sealed generation has unsafe node type")
    opened = _open_at(node.fd, name, _SEALED_DIR, policy)
    try:
        _preflight_sealed_tree(opened, child, policy, False)
    finally:
        os.close(opened.fd)


def _preflight_sealed_tree(
    node: _Pinned, tree: _Tree, policy: _Policy, root: bool
) -> None:
    if root:
        commit = os.stat("commit.json", dir_fd=node.fd, follow_symlinks=False)
        if not stat.S_ISREG(commit.st_mode):
            raise GenerationSealError("sealed commit has unsafe node type")
    for name in sorted(tree.children):
        _preflight_sealed_child(node, (name, tree.children[name]), policy)


def create_pending(
    generations: _Pinned, commit: GenerationCommitV1, policy: _Policy
) -> _Pinned:
    """Recover safe residue, then allocate one new pending directory inode."""
    cleanup_pending(generations, commit, policy)
    opened = _new_output_dir(
        generations.fd, pending_name(commit.generation_id), policy
    )
    os.fsync(generations.fd)
    return opened


def write_pending_intent(
    pending: _Pinned, commit: GenerationCommitV1, policy: _Policy
) -> None:
    """Persist the commit identity before copying any payload byte."""
    fd = _new_output(pending.fd, PENDING_INTENT_TEMP_NAME, policy)
    try:
        _write_chunk(fd, commit.document_json)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.fsync(pending.fd)
    _rename_noreplace(pending, PENDING_INTENT_TEMP_NAME, PENDING_INTENT_NAME)
    os.fsync(pending.fd)


def _promote_pending_intent(
    pending: _Pinned, commit: GenerationCommitV1, policy: _Policy
) -> None:
    opened = _open_at(pending.fd, PENDING_INTENT_NAME, _MUTABLE_FILE, policy)
    try:
        if _read_stable(opened, MAX_COMMIT_BYTES) != commit.document_json:
            raise GenerationSealError("pending generation identity changed")
        os.fchmod(opened.fd, 0o400)
        os.fsync(opened.fd)
    finally:
        os.close(opened.fd)
    _rename_noreplace(pending, PENDING_INTENT_NAME, "commit.json")
    os.fsync(pending.fd)


def _seal_leaf(node: _Pinned, name: str, context: _SealContext) -> None:
    opened = _open_at(node.fd, name, _MUTABLE_FILE, context.policy)
    try:
        os.fchmod(opened.fd, 0o400)
        os.fsync(opened.fd)
        info = os.fstat(opened.fd)
        entry = os.stat(name, dir_fd=node.fd, follow_symlinks=False)
        if _snapshot(info) != _snapshot(entry):
            raise GenerationSealError("generation leaf changed while sealing")
    finally:
        os.close(opened.fd)


def _seal_child(
    node: _Pinned, entry: tuple[str, _Tree], context: _SealContext
) -> None:
    name, child = entry
    if child.row is not None:
        _seal_leaf(node, name, context)
        return
    opened = _open_at(node.fd, name, _MUTABLE_DIR, context.policy)
    try:
        _seal_tree(opened, child, context)
        os.fchmod(opened.fd, 0o500)
        os.fsync(opened.fd)
    finally:
        os.close(opened.fd)


def _seal_tree(node: _Pinned, tree: _Tree, context: _SealContext) -> None:
    expected = set(tree.children)
    if node.fd == context.root.fd:
        expected.add("commit.json")
    names = bounded_directory_entries(node.fd, len(expected))
    if set(names) != expected:
        raise GenerationSealError("pending generation closure changed")
    for name in sorted(tree.children):
        _seal_child(node, (name, tree.children[name]), context)
    os.fsync(node.fd)


def seal_pending(
    pending: _Pinned, commit: GenerationCommitV1, policy: _Policy
) -> _Pinned:
    """Write the commit last, then make every payload node read-only."""
    _promote_pending_intent(pending, commit, policy)
    _seal_tree(pending, _manifest_tree(commit), _SealContext(policy, pending))
    os.fchmod(pending.fd, 0o500)
    os.fsync(pending.fd)
    info = os.fstat(pending.fd)
    return _Pinned(
        pending.fd, pending.parent_fd, pending.name, _snapshot(info)
    )


def install_pending(
    generations: _Pinned, pending: _Pinned, commit: GenerationCommitV1
) -> None:
    """Atomically install the sealed inode under its final generation ID."""
    before = _snapshot(os.fstat(pending.fd))
    _rename_noreplace(generations, pending.name, commit.generation_id)
    installed = os.stat(
        commit.generation_id, dir_fd=generations.fd, follow_symlinks=False
    )
    if _snapshot(installed)[:7] != before[:7]:
        raise GenerationSealError(
            "installed generation inode identity changed"
        )
    os.fsync(generations.fd)


def _rename_noreplace(generations: _Pinned, source: str, target: str) -> None:
    encoded = (os.fsencode(source), os.fsencode(target))
    libc = ctypes.CDLL(None, use_errno=True)
    variants = (("renameatx_np", 4), ("renameat2", 1))
    unsupported = {errno.EINVAL, errno.ENOSYS, errno.ENOTSUP}
    for symbol, flag in variants:
        function = getattr(libc, symbol, None)
        if function is None:
            continue
        function.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        function.restype = ctypes.c_int
        result = function(
            generations.fd,
            encoded[0],
            generations.fd,
            encoded[1],
            flag,
        )
        if result == 0:
            return
        error = ctypes.get_errno()
        if error in {errno.EEXIST, errno.ENOTEMPTY}:
            raise GenerationSealError("generation ID collision")
        if error in unsupported:
            continue
        raise OSError(error, os.strerror(error))
    raise GenerationSealError("atomic no-replace rename is unavailable")
