"""Exact initialization-capable policy with no execution gate authority."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache

from . import quality_receipt_json as wire
from .generation_policy_documents import GenerationPolicyDocumentError
from .operation_contract import (
    InitializeOperationV1,
    validate_headless_mp4_operation_v1,
)
from .wire_identity import same_wire_value

GenesisExecutionPolicyError = GenerationPolicyDocumentError
_DOMAIN = b"sniper-initialization-execution-policy-v2\0"
_TOP_KEYS = frozenset(
    "compositor executionPath initialization publication realization "
    "schemaVersion".split()
)
_PATH_KEYS = frozenset("guiAllowed kind palmierAllowed".split())
_INITIALIZATION_KEYS = frozenset(
    "expectedParent initialBaseBuild operation snapshotAuthorityKind "
    "writerRebuildAllowed".split()
)
_REALIZATION_KEYS = frozenset("fallbackPolicy kind".split())
_COMPOSITOR_KEYS = frozenset("audioDisposition eofAction kind proxyDisposition".split())
_PUBLICATION_KEYS = frozenset("allowed candidateDisposition".split())


@dataclass(frozen=True)
class InitializationExecutionPolicyV2:
    """Closed initialize semantics; not a runtime-execution capability."""

    operation: str
    expected_parent: None
    initial_base_build: str
    snapshot_authority_kind: str
    writer_rebuild_allowed: bool
    fallback_policy: str
    publication_allowed: bool
    document_json: bytes
    policy_id: str


@dataclass(frozen=True)
class InitializationPolicyCompatibilityV2:
    """Structural compatibility that deliberately cannot authorize execution."""

    status: str
    operation_digest: str
    execution_policy_id: str
    policy_compatible: bool
    runtime_verified: bool
    execution_authorized: bool
    publication_authorized: bool


def _document() -> dict:
    return {
        "schemaVersion": 2,
        "executionPath": {
            "kind": "code-agent-only",
            "guiAllowed": False,
            "palmierAllowed": False,
        },
        "initialization": {
            "operation": "initialize",
            "expectedParent": None,
            "initialBaseBuild": "from-presealed-snapshot",
            "snapshotAuthorityKind": "presealed-immutable-snapshot-v1",
            "writerRebuildAllowed": False,
        },
        "realization": {
            "kind": "deterministic-mp4",
            "fallbackPolicy": "none",
        },
        "compositor": {
            "kind": "prebound-compositor",
            "eofAction": "pass",
            "audioDisposition": "copy",
            "proxyDisposition": "omitted-by-policy",
        },
        "publication": {
            "allowed": False,
            "candidateDisposition": "private-initialization-candidate",
        },
    }


def _exact_sections(document: dict) -> None:
    wire.exact(document, _TOP_KEYS, "initialization execution policy")
    wire.exact(document["executionPath"], _PATH_KEYS, "execution path")
    wire.exact(
        document["initialization"], _INITIALIZATION_KEYS, "initialization authority"
    )
    wire.exact(document["realization"], _REALIZATION_KEYS, "realization")
    wire.exact(document["compositor"], _COMPOSITOR_KEYS, "compositor")
    wire.exact(document["publication"], _PUBLICATION_KEYS, "publication")


def _valid_semantics(document: dict) -> bool:
    path = document["executionPath"]
    initialization = document["initialization"]
    realization = document["realization"]
    compositor = document["compositor"]
    publication = document["publication"]
    return (
        type(document["schemaVersion"]) is int
        and document["schemaVersion"] == 2
        and path
        == {
            "kind": "code-agent-only",
            "guiAllowed": False,
            "palmierAllowed": False,
        }
        and initialization == _document()["initialization"]
        and realization == _document()["realization"]
        and compositor == _document()["compositor"]
        and publication == _document()["publication"]
    )


def parse_initialization_execution_policy_v2(
    raw: object,
) -> InitializationExecutionPolicyV2:
    """Parse only the one exact canonical initialization policy V2."""
    try:
        document = wire.canonical_document(raw, "initialization execution policy")
        _exact_sections(document)
    except RuntimeError as exc:
        raise GenesisExecutionPolicyError(
            "initialization execution policy is invalid"
        ) from exc
    from .operation_wire import canonical

    if raw != canonical(_document()) or not _valid_semantics(document):
        raise GenesisExecutionPolicyError(
            "initialization execution policy semantics are invalid"
        )
    initialization = document["initialization"]
    policy_id = hashlib.sha256(_DOMAIN + raw).hexdigest()
    return InitializationExecutionPolicyV2(
        initialization["operation"],
        None,
        initialization["initialBaseBuild"],
        initialization["snapshotAuthorityKind"],
        False,
        document["realization"]["fallbackPolicy"],
        False,
        raw,
        policy_id,
    )


@lru_cache(maxsize=1)
def current_initialization_execution_policy_v2() -> InitializationExecutionPolicyV2:
    """Return the process-stable sole initialization-capable policy."""
    from .operation_wire import canonical

    return parse_initialization_execution_policy_v2(canonical(_document()))


def validate_initialization_execution_policy_v2(value: object) -> None:
    """Reject direct construction that disagrees with canonical policy bytes."""
    if type(value) is not InitializationExecutionPolicyV2:
        raise GenesisExecutionPolicyError("initialization policy instance is invalid")
    parsed = parse_initialization_execution_policy_v2(value.document_json)
    current = current_initialization_execution_policy_v2()
    if not same_wire_value(value, parsed) or not same_wire_value(parsed, current):
        raise GenesisExecutionPolicyError("initialization policy identity is invalid")


def bind_initialize_operation_policy_v2(
    operation: object, policy: object
) -> InitializationPolicyCompatibilityV2:
    """Bind initialize semantics while retaining a closed execution gate."""
    try:
        validate_headless_mp4_operation_v1(operation)
        validate_initialization_execution_policy_v2(policy)
    except RuntimeError as exc:
        raise GenesisExecutionPolicyError(
            "initialization policy binding is invalid"
        ) from exc
    if type(operation) is not InitializeOperationV1:
        raise GenesisExecutionPolicyError("policy V2 accepts only initialize")
    expected = (
        policy.policy_id,
        policy.expected_parent,
        policy.initial_base_build,
        policy.snapshot_authority_kind,
        policy.writer_rebuild_allowed,
        policy.fallback_policy,
    )
    actual = (
        operation.execution_policy_id,
        operation.expected_parent,
        operation.initial_base_build,
        "presealed-immutable-snapshot-v1",
        operation.writer_rebuild_allowed,
        operation.fallback_policy,
    )
    if actual != expected:
        raise GenesisExecutionPolicyError("initialize operation contradicts policy V2")
    return InitializationPolicyCompatibilityV2(
        "BOUND_INITIALIZATION_POLICY_V2_NOT_EXECUTION_AUTHORIZED",
        operation.operation_digest,
        policy.policy_id,
        True,
        False,
        False,
        False,
    )
