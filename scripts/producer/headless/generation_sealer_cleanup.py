"""Fail-closed cleanup for one generation-specific pending namespace."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass

from .durable_files import bounded_directory_entries
from .generation_reader import _Tree, _manifest_tree
from .generation_reader_fs import _Pinned, _Policy, _read_stable, _snapshot
from .generation_schema import (
    GenerationCommitV1,
    GenerationSchemaError,
    parse_generation_commit,
)
from .generation_sealer_types import (
    MAX_COMMIT_BYTES,
    PENDING_INTENT_NAME,
    PENDING_INTENT_TEMP_NAME,
    GenerationSealError,
)

_IDENTITY_NAMES = frozenset({PENDING_INTENT_NAME, "commit.json"})
_METADATA_NAMES = _IDENTITY_NAMES | {PENDING_INTENT_TEMP_NAME}


@dataclass(frozen=True)
class _CleanupContext:
    policy: _Policy
    root: _Pinned


def _precheck_type(parent: _Pinned, name: str, directory: bool) -> None:
    info = os.stat(name, dir_fd=parent.fd, follow_symlinks=False)
    valid = (
        stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    )
    if not valid:
        raise GenerationSealError("pending generation has unsafe node type")


def pending_name(generation_id: str) -> str:
    """Return the only crash-residue name this generation may own."""
    return f".seal.{generation_id}.pending"


def _cleanup_open(
    parent: _Pinned, name: str, directory: bool, context: _CleanupContext
) -> _Pinned:
    _precheck_type(parent, name, directory)
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW
    if directory:
        flags |= os.O_DIRECTORY
    flags |= getattr(os, "O_CLOEXEC", 0)
    fd = os.open(name, flags, dir_fd=parent.fd)
    try:
        info = os.fstat(fd)
        entry = os.stat(name, dir_fd=parent.fd, follow_symlinks=False)
        node_type = (
            stat.S_ISDIR(info.st_mode)
            if directory
            else stat.S_ISREG(info.st_mode)
        )
        allowed_modes = {0o500, 0o700} if directory else {0o400, 0o600}
        safe = (
            node_type
            and (directory or info.st_nlink == 1)
            and info.st_dev == context.policy.device
            and info.st_uid == context.policy.owner
            and stat.S_IMODE(info.st_mode) in allowed_modes
            and _snapshot(info) == _snapshot(entry)
        )
        if not safe:
            raise GenerationSealError(
                "pending generation contains unsafe state"
            )
        return _Pinned(fd, parent.fd, name, _snapshot(info))
    except Exception:
        os.close(fd)
        raise


def _unlink_opened(parent: _Pinned, opened: _Pinned) -> None:
    entry = os.stat(opened.name, dir_fd=parent.fd, follow_symlinks=False)
    if _snapshot(entry) != opened.snapshot:
        raise GenerationSealError("pending generation changed during cleanup")
    os.unlink(opened.name, dir_fd=parent.fd)


def _validate_pending_identity(
    node: _Pinned,
    tree: _Tree,
    commit: GenerationCommitV1,
    context: _CleanupContext,
) -> None:
    limit = len(tree.children) + len(_METADATA_NAMES)
    names = set(bounded_directory_entries(node.fd, limit))
    identities = names & _IDENTITY_NAMES
    temporary = PENDING_INTENT_TEMP_NAME in names
    if len(identities) > 1 or identities and temporary:
        raise GenerationSealError("pending generation identity is ambiguous")
    if temporary:
        if names != {PENDING_INTENT_TEMP_NAME}:
            raise GenerationSealError("pending intent residue is ambiguous")
        _validate_temporary_identity(node, commit, context)
        return
    if not identities:
        if names:
            raise GenerationSealError("pending generation identity is absent")
        return
    name = next(iter(identities))
    opened = _cleanup_open(node, name, False, context)
    try:
        raw = _read_stable(opened, MAX_COMMIT_BYTES)
        if raw != commit.document_json:
            raise GenerationSealError(
                "pending generation ID collision or equivocation"
            )
    finally:
        os.close(opened.fd)


def _validate_temporary_identity(
    node: _Pinned,
    commit: GenerationCommitV1,
    context: _CleanupContext,
) -> None:
    """Reject a complete flushed intent owned by a different commit."""
    opened = _cleanup_open(node, PENDING_INTENT_TEMP_NAME, False, context)
    try:
        raw = _read_stable(opened, MAX_COMMIT_BYTES)
    finally:
        os.close(opened.fd)
    if raw == commit.document_json:
        return
    try:
        parse_generation_commit(raw)
    except GenerationSchemaError:
        return
    raise GenerationSealError(
        "pending generation ID collision or equivocation"
    )


def _cleanup_child(
    node: _Pinned, entry: tuple[str, _Tree], context: _CleanupContext
) -> None:
    name, child = entry
    opened = _cleanup_open(node, name, child.row is None, context)
    try:
        if child.row is not None:
            _unlink_opened(node, opened)
            return
        os.fchmod(opened.fd, 0o700)
        _cleanup_tree(opened, child, context)
        _assert_directory_entry(node, opened)
    finally:
        os.close(opened.fd)
    os.rmdir(name, dir_fd=node.fd)


def _assert_directory_entry(parent: _Pinned, opened: _Pinned) -> None:
    info = os.fstat(opened.fd)
    entry = os.stat(opened.name, dir_fd=parent.fd, follow_symlinks=False)
    identity = (info.st_dev, info.st_ino, info.st_uid)
    observed = (entry.st_dev, entry.st_ino, entry.st_uid)
    if identity != observed or not stat.S_ISDIR(entry.st_mode):
        raise GenerationSealError("pending directory changed during cleanup")


def _cleanup_tree(
    node: _Pinned, tree: _Tree, context: _CleanupContext
) -> None:
    allowed = set(tree.children)
    if node.fd == context.root.fd:
        allowed.update(_METADATA_NAMES)
    names = bounded_directory_entries(node.fd, len(allowed))
    if not set(names).issubset(allowed):
        raise GenerationSealError("pending generation contains unknown state")
    payload_names = tuple(
        name for name in names if name not in _METADATA_NAMES
    )
    for name in payload_names:
        _cleanup_child(node, (name, tree.children[name]), context)
    for name in _METADATA_NAMES & set(names):
        commit_file = _cleanup_open(node, name, False, context)
        try:
            _unlink_opened(node, commit_file)
        finally:
            os.close(commit_file.fd)
    os.fsync(node.fd)


def _preflight_child(
    node: _Pinned, entry: tuple[str, _Tree], context: _CleanupContext
) -> None:
    name, child = entry
    opened = _cleanup_open(node, name, child.row is None, context)
    try:
        if child.row is None:
            _preflight_tree(opened, child, context)
    finally:
        os.close(opened.fd)


def _preflight_tree(
    node: _Pinned, tree: _Tree, context: _CleanupContext
) -> None:
    allowed = set(tree.children)
    if node.fd == context.root.fd:
        allowed.update(_METADATA_NAMES)
    names = bounded_directory_entries(node.fd, len(allowed))
    if not set(names).issubset(allowed):
        raise GenerationSealError("pending generation contains unknown state")
    for name in names:
        if name in _METADATA_NAMES:
            opened = _cleanup_open(node, name, False, context)
            os.close(opened.fd)
            continue
        _preflight_child(node, (name, tree.children[name]), context)


def cleanup_pending(
    generations: _Pinned, commit: GenerationCommitV1, policy: _Policy
) -> None:
    """Remove the safe subset at this commit's deterministic pending name."""
    name = pending_name(commit.generation_id)
    context = _CleanupContext(policy, generations)
    try:
        opened = _cleanup_open(generations, name, True, context)
    except FileNotFoundError:
        return
    try:
        tree = _manifest_tree(commit)
        context = _CleanupContext(policy, opened)
        _validate_pending_identity(opened, tree, commit, context)
        _preflight_tree(opened, tree, context)
        os.fchmod(opened.fd, 0o700)
        _cleanup_tree(opened, tree, context)
        _assert_directory_entry(generations, opened)
    finally:
        os.close(opened.fd)
    os.rmdir(name, dir_fd=generations.fd)
    os.fsync(generations.fd)
