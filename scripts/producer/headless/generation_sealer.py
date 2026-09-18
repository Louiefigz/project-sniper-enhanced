"""Trusted fresh-inode sealer for immutable, unpublished generations."""

from __future__ import annotations

import fcntl
import os

from .authority_record import AuthorityRecordError, ensure_authority_record
from .durable_files import (
    DurableFileError,
    assert_private_lock_identity,
    open_private_file,
)
from .generation_reader import _manifest_tree
from .generation_reader_fs import (
    GenerationReadError,
    _MUTABLE_DIR,
    _Pinned,
    _Policy,
    _open_root,
    _recheck_safe,
)
from .generation_schema import (
    GenerationCommitV1,
    GenerationSchemaError,
    parse_generation_commit,
)
from .generation_sealer_final import (
    cleanup_pending,
    create_pending,
    existing_generation,
    install_pending,
    open_generation_parent,
    recover_sealed_pending,
    seal_pending,
    verify_named_generation,
    write_pending_intent,
)
from .generation_sealer_source import copy_staging_payload
from .generation_sealer_types import (
    MAX_COMMIT_BYTES,
    GenerationSealError,
    GenerationSealRequestV1,
    GenerationSealResultV1,
    validate_json_resource_shape,
    validate_resource_policy,
)

_LOCK_NAME = ".generation-seal.lock"


def _checkpoint(_label: str) -> None:
    """Test seam for crash-window coverage; production performs no action."""


def _validate_request(value: object) -> GenerationCommitV1:
    if type(value) is not GenerationSealRequestV1:
        raise GenerationSealError("generation seal request is invalid")
    if type(value.commit_json) is not bytes or not value.commit_json:
        raise GenerationSealError("generation commit bytes are invalid")
    if len(value.commit_json) > MAX_COMMIT_BYTES:
        raise GenerationSealError("generation commit exceeds sealer limits")
    validate_json_resource_shape(value.commit_json)
    _validate_path(value.authority_root, "authority")
    _validate_path(value.staging_root, "staging")
    _reject_overlapping_roots(value.authority_root, value.staging_root)
    try:
        commit = parse_generation_commit(value.commit_json)
    except GenerationSchemaError as exc:
        raise GenerationSealError("generation commit is invalid") from exc
    validate_resource_policy(commit)
    try:
        _manifest_tree(commit)
    except GenerationReadError as exc:
        raise GenerationSealError("generation manifest paths collide") from exc
    return commit


def _validate_path(path: object, label: str) -> None:
    valid = (
        type(path) is str
        and os.path.isabs(path)
        and os.path.realpath(path) == path
    )
    if not valid:
        raise GenerationSealError(
            f"{label} root must be an absolute canonical path"
        )


def _reject_overlapping_roots(authority: str, staging: str) -> None:
    try:
        common = os.path.commonpath((authority, staging))
    except ValueError as exc:
        raise GenerationSealError(
            "authority and staging roots are incompatible"
        ) from exc
    if common in {authority, staging}:
        raise GenerationSealError(
            "authority and staging roots must be disjoint"
        )


def _result(
    commit: GenerationCommitV1,
    replayed: bool,
) -> GenerationSealResultV1:
    return GenerationSealResultV1(
        commit.generation_id, commit.commit_digest, replayed
    )


def _seal_locked(
    root: _Pinned,
    policy: _Policy,
    request: GenerationSealRequestV1,
    commit: GenerationCommitV1,
) -> GenerationSealResultV1:
    generations = open_generation_parent(root, policy)
    pending = None
    owned = False
    try:
        if existing_generation(generations, commit):
            _recheck_safe(generations, _MUTABLE_DIR, policy)
            return _result(commit, True)
        pending = recover_sealed_pending(generations, commit, policy)
        owned = pending is not None
        if pending is None:
            pending = create_pending(generations, commit, policy)
            owned = True
            write_pending_intent(pending, commit, policy)
            copy_staging_payload(request.staging_root, pending, policy, commit)
            _checkpoint("payload-copied")
            pending = seal_pending(pending, commit, policy)
            _checkpoint("pending-sealed")
        else:
            _checkpoint("pending-recovered")
        verify_named_generation(generations, pending.name, commit)
        _checkpoint("before-install")
        install_pending(generations, pending, commit)
        owned = False
        _checkpoint("after-install")
        verify_named_generation(generations, commit.generation_id, commit)
        _recheck_safe(generations, _MUTABLE_DIR, policy)
        return _result(commit, False)
    except Exception:
        if owned:
            cleanup_pending(generations, commit, policy)
        raise
    finally:
        if pending is not None:
            os.close(pending.fd)
        os.close(generations.fd)


def seal_generation(
    request: GenerationSealRequestV1,
) -> GenerationSealResultV1:
    """Install payload bytes without touching ``CURRENT`` or a fence."""
    commit = _validate_request(request)
    root = lock_fd = None
    try:
        root, policy = _open_root(request.authority_root)
        ensure_authority_record(root.fd, commit.authority_id)
        lock_fd = open_private_file(
            root.fd, _LOCK_NAME, os.O_CREAT | os.O_RDWR
        )
        os.fsync(root.fd)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        assert_private_lock_identity(root.fd, _LOCK_NAME, lock_fd)
        _recheck_safe(root, _MUTABLE_DIR, policy)
        result = _seal_locked(root, policy, request, commit)
        assert_private_lock_identity(root.fd, _LOCK_NAME, lock_fd)
        _recheck_safe(root, _MUTABLE_DIR, policy)
        return result
    except GenerationSealError:
        raise
    except (
        AuthorityRecordError,
        DurableFileError,
        GenerationReadError,
        OSError,
        RuntimeError,
    ) as exc:
        raise GenerationSealError(
            "generation could not be safely sealed"
        ) from exc
    finally:
        if lock_fd is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        if root is not None:
            os.close(root.fd)
