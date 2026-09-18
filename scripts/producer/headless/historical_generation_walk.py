"""Authenticated selected-ancestry walk and target materialization."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from types import MappingProxyType

from .generation_reader import _WalkContext, _manifest_tree, _walk
from .generation_reader_fs import (
    _Pinned,
    _Policy,
    _SEALED_DIR,
    _SEALED_FILE,
    _open_at,
    _read_stable,
    _recheck,
)
from .generation_materialized_verification import verify_materialized
from .generation_schema import (
    CurrentPointerV1,
    GenerationCommitV1,
    parse_current_pointer,
    parse_generation_commit,
)
from .historical_generation_store import HistoricalSourceArtifactStoreV1
from .historical_generation_types import (
    SELECTED_CURRENT_ANCESTRY_SCOPE,
    HistoricalGenerationMaterializationV1,
    HistoricalGenerationRecordV1,
)
from .historical_generation_validation import validate_historical_generation
from .repair_intent import ParentRefV1, validate_parent_ref

_CURRENT_LIMIT = 65_536
_COMMIT_LIMIT = 16 * 1024 * 1024


class HistoricalGenerationWalkError(RuntimeError):
    """The selected ancestry is cyclic, discontinuous, or mismatched."""


@dataclass(frozen=True)
class HistoricalWalkSession:
    current: CurrentPointerV1
    requested: ParentRefV1
    destination: _Pinned
    policy: _Policy
    generations: _Pinned
    current_file: _Pinned


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
    record: HistoricalGenerationRecordV1


@dataclass
class _Context:
    session: HistoricalWalkSession
    lineage: list[HistoricalGenerationRecordV1] = field(default_factory=list)
    nodes: list[_OpenNode] = field(default_factory=list)
    seen_ids: set[str] = field(default_factory=set)
    seen_digests: set[str] = field(default_factory=set)
    target: HistoricalGenerationRecordV1 | None = None
    target_snapshots: dict[str, tuple[int, ...]] | None = None
    target_paths: dict[str, str] | None = None


def _expected(value: CurrentPointerV1 | ParentRefV1) -> _ExpectedNode:
    plan = value.plan_digest if type(value) is ParentRefV1 else None
    return _ExpectedNode(
        value.authority_id,
        value.publication_seq,
        value.generation_id,
        value.commit_digest,
        plan,
    )


def _bind_commit(expected: _ExpectedNode, commit: GenerationCommitV1) -> None:
    actual = (commit.authority_id, commit.generation_id, commit.commit_digest)
    required = (
        expected.authority_id,
        expected.generation_id,
        expected.commit_digest,
    )
    if actual != required:
        raise HistoricalGenerationWalkError(
            "child-signed parent identity does not match opened generation"
        )


def _open_node(context: _Context, expected: _ExpectedNode) -> _OpenNode:
    if (
        expected.generation_id in context.seen_ids
        or expected.commit_digest in context.seen_digests
    ):
        raise HistoricalGenerationWalkError(
            "selected ancestry contains a cycle"
        )
    session = context.session
    generation = _open_at(
        session.generations.fd,
        expected.generation_id,
        _SEALED_DIR,
        session.policy,
    )
    commit_file = None
    try:
        commit_file = _open_at(
            generation.fd, "commit.json", _SEALED_FILE, session.policy
        )
        raw = _read_stable(commit_file, _COMMIT_LIMIT)
        commit = parse_generation_commit(raw)
        _bind_commit(expected, commit)
        store = HistoricalSourceArtifactStoreV1.audit(
            commit, generation, session.policy
        )
        descriptor, plan_digest = validate_historical_generation(commit, store)
        ref = ParentRefV1(
            commit.authority_id,
            expected.publication_seq,
            commit.generation_id,
            commit.commit_digest,
            plan_digest,
        )
        validate_parent_ref(ref)
        if (
            expected.plan_digest is not None
            and ref.plan_digest != expected.plan_digest
        ):
            raise HistoricalGenerationWalkError(
                "child-signed historical plan digest does not match parent"
            )
        record = HistoricalGenerationRecordV1(ref, commit, descriptor)
        return _OpenNode(generation, commit_file, raw, store, record)
    except Exception:
        if commit_file is not None:
            os.close(commit_file.fd)
        os.close(generation.fd)
        raise


def _parent(node: _OpenNode) -> ParentRefV1 | None:
    current, parent = node.record.ref, node.record.commit.expected_parent
    if current.publication_seq == 1:
        if parent is not None:
            raise HistoricalGenerationWalkError(
                "selected ancestry does not terminate at genesis"
            )
        return None
    valid = (
        parent is not None
        and parent.authority_id == current.authority_id
        and parent.publication_seq == current.publication_seq - 1
        and parent.generation_id != current.generation_id
    )
    if not valid:
        raise HistoricalGenerationWalkError(
            "selected ancestry has a sequence gap or invalid parent edge"
        )
    return parent


def _materialize(context: _Context, node: _OpenNode) -> None:
    session = context.session
    if context.target is not None or os.listdir(session.destination.fd):
        raise HistoricalGenerationWalkError("historical target is ambiguous")
    walk = _WalkContext(session.policy, node.generation.fd)
    _walk(
        node.generation,
        session.destination,
        _manifest_tree(node.record.commit),
        walk,
    )
    paths = verify_materialized(
        session.destination,
        session.policy,
        node.record.commit.files,
        walk.snapshots,
    )
    context.target = node.record
    context.target_snapshots = walk.snapshots
    context.target_paths = paths


def _record(context: _Context, node: _OpenNode) -> ParentRefV1 | None:
    ref = node.record.ref
    context.seen_ids.add(ref.generation_id)
    context.seen_digests.add(ref.commit_digest)
    context.lineage.append(node.record)
    context.nodes.append(node)
    if ref == context.session.requested:
        _materialize(context, node)
    return _parent(node)


def _walk_lineage(context: _Context) -> None:
    expected = _expected(context.session.current)
    while True:
        parent = _record(context, _open_node(context, expected))
        if parent is None:
            return
        expected = _expected(parent)


def _revalidate(context: _Context) -> None:
    session = context.session
    for node in context.nodes:
        if _read_stable(node.commit_file, _COMMIT_LIMIT) != node.commit_raw:
            raise HistoricalGenerationWalkError("historical commit changed")
        node.store.assert_stable()
        _recheck(node.generation)
    observed = parse_current_pointer(
        _read_stable(session.current_file, _CURRENT_LIMIT)
    )
    if observed != session.current:
        raise HistoricalGenerationWalkError(
            "CURRENT changed during resolution"
        )
    _recheck(session.generations)


def _result(context: _Context) -> HistoricalGenerationMaterializationV1:
    session = context.session
    if (
        context.target is None
        or context.target_paths is None
        or context.target_snapshots is None
    ):
        raise HistoricalGenerationWalkError(
            "requested parent is not on the selected CURRENT ancestry"
        )
    paths = verify_materialized(
        session.destination,
        session.policy,
        context.target.commit.files,
        context.target_snapshots,
    )
    if paths != context.target_paths:
        raise HistoricalGenerationWalkError("historical copy mapping changed")
    return HistoricalGenerationMaterializationV1(
        SELECTED_CURRENT_ANCESTRY_SCOPE,
        session.current,
        context.target,
        tuple(context.lineage),
        MappingProxyType(dict(sorted(paths.items()))),
        MappingProxyType(dict(sorted(context.target_snapshots.items()))),
    )


def _close(nodes: list[_OpenNode]) -> None:
    for node in reversed(nodes):
        os.close(node.commit_file.fd)
        os.close(node.generation.fd)


def walk_selected_ancestry(
    session: HistoricalWalkSession,
) -> HistoricalGenerationMaterializationV1:
    """Prove selected ancestry and materialize its exact target."""
    context = _Context(session)
    try:
        _walk_lineage(context)
        _revalidate(context)
        return _result(context)
    finally:
        _close(context.nodes)
