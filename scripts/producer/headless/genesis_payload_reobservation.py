"""Stream and reobserve the complete selected genesis R1 materialization."""

from __future__ import annotations

import hashlib
import os

from .artifact_contract import ArtifactRefV1
from .generation_artifact_store import GenerationArtifactStoreV1
from .generation_reader_fs import (
    GenerationReadError,
    _open_root,
    _recheck,
)
from .generation_materialized_verification import verify_materialized
from .generation_schema import (
    GenerationCommitV1,
    GenerationManifestRowV1,
    parse_generation_commit,
)
from .genesis_generation_profile import (
    GENESIS_R1_MANIFEST_ROWS,
    GENESIS_R1_PROFILE,
)
from .genesis_generation_verification import genesis_payload_manifest_digest
from .genesis_payload_reobservation_types import (
    GENESIS_PAYLOAD_REOBSERVATION_STATUS,
    GenesisPayloadReobservationV1,
    ObservedGenesisArtifactV1,
)
from .operation_wire import canonical
from .versioned_generation_reader import (
    VersionedResolvedGenerationV2,
    validate_versioned_resolved_generation,
)
from .wire_identity import same_wire_value

_EVIDENCE_DOMAIN = b"sniper-genesis-payload-reobservation-v1\0"


class GenesisPayloadReobservationError(RuntimeError):
    """The selected genesis materialization changed or is not exact closure."""


def _artifact(row: GenerationManifestRowV1) -> ObservedGenesisArtifactV1:
    return ObservedGenesisArtifactV1(
        row.artifact_class,
        ArtifactRefV1(row.path, row.sha256, row.size_bytes),
    )


def _artifact_document(value: ObservedGenesisArtifactV1) -> dict:
    ref = value.artifact
    return {
        "artifactClass": value.artifact_class,
        "path": ref.relative_path,
        "sha256": ref.sha256,
        "sizeBytes": ref.size_bytes,
    }


def _evidence_digest(artifacts: tuple[ObservedGenesisArtifactV1, ...]) -> str:
    document = [_artifact_document(value) for value in artifacts]
    return hashlib.sha256(_EVIDENCE_DOMAIN + canonical(document)).hexdigest()


def _validated_selection(value: object) -> VersionedResolvedGenerationV2:
    if type(value) is not VersionedResolvedGenerationV2:
        raise GenesisPayloadReobservationError(
            "genesis selection type is invalid"
        )
    try:
        selection = validate_versioned_resolved_generation(value)
    except RuntimeError as exc:
        raise GenesisPayloadReobservationError(
            "genesis selection is invalid"
        ) from exc
    if selection.profile != GENESIS_R1_PROFILE:
        raise GenesisPayloadReobservationError("selection is not genesis R1")
    return value


def _stream_materialization(selected: VersionedResolvedGenerationV2) -> None:
    generation = selected.generation
    store = GenerationArtifactStoreV1.from_resolved(generation)
    root = None
    try:
        root, policy = _open_root(store.root)
        observed = verify_materialized(
            root,
            policy,
            generation.commit.files,
            dict(generation.materialized_snapshots),
        )
        _recheck(root)
    except (OSError, GenerationReadError, RuntimeError) as exc:
        raise GenesisPayloadReobservationError(
            "genesis payload materialization changed or is unsafe"
        ) from exc
    finally:
        if root is not None:
            os.close(root.fd)
    if observed != dict(generation.materialized):
        raise GenesisPayloadReobservationError(
            "genesis materialization mapping is not exact closure"
        )


def _expected_artifacts(
    commit: GenerationCommitV1,
) -> tuple[ObservedGenesisArtifactV1, ...]:
    return tuple(_artifact(row) for row in commit.files)


def _payload_digest(commit: GenerationCommitV1) -> str:
    payload = tuple(
        row
        for row in commit.files
        if row.artifact_class != "generation-verification-v2"
    )
    return genesis_payload_manifest_digest(payload)


def reobserve_genesis_payload(value: object) -> GenesisPayloadReobservationV1:
    """Stream every selected R1 artifact without retaining aggregate bytes."""
    selected = _validated_selection(value)
    _stream_materialization(selected)
    commit = selected.generation.commit
    artifacts = _expected_artifacts(commit)
    return GenesisPayloadReobservationV1(
        GENESIS_PAYLOAD_REOBSERVATION_STATUS,
        GENESIS_R1_PROFILE,
        commit.authority_id,
        commit.generation_id,
        commit.commit_digest,
        _evidence_digest(artifacts),
        _payload_digest(commit),
        artifacts,
        len(artifacts),
        sum(value.artifact.size_bytes for value in artifacts),
        True,
        True,
        False,
        False,
        False,
        False,
    )


def _expected_values(
    commit: GenerationCommitV1,
) -> tuple:
    artifacts = _expected_artifacts(commit)
    return (
        GENESIS_PAYLOAD_REOBSERVATION_STATUS,
        GENESIS_R1_PROFILE,
        commit.authority_id,
        commit.generation_id,
        commit.commit_digest,
        _evidence_digest(artifacts),
        _payload_digest(commit),
        artifacts,
        GENESIS_R1_MANIFEST_ROWS,
        sum(item.artifact.size_bytes for item in artifacts),
        True,
        True,
        False,
        False,
        False,
        False,
    )


def _observed_values(value: GenesisPayloadReobservationV1) -> tuple:
    return (
        value.status,
        value.profile,
        value.authority_id,
        value.generation_id,
        value.commit_digest,
        value.manifest_evidence_digest,
        value.payload_manifest_digest,
        value.artifacts,
        value.artifact_count,
        value.total_size_bytes,
        value.exact_materialization_closure_bound,
        value.complete_manifest_reobserved,
        value.final_current_rechecked,
        value.runtime_verified,
        value.execution_authorized,
        value.publication_authorized,
    )


def validate_genesis_payload_reobservation(
    value: object, commit: object
) -> GenesisPayloadReobservationV1:
    """Reject forged or cross-generation payload observation dataclasses."""
    if type(value) is not GenesisPayloadReobservationV1:
        raise GenesisPayloadReobservationError(
            "genesis observation type is invalid"
        )
    if type(commit) is not GenerationCommitV1:
        raise GenesisPayloadReobservationError(
            "genesis commit type is invalid"
        )
    try:
        parsed = parse_generation_commit(commit.document_json)
    except RuntimeError as exc:
        raise GenesisPayloadReobservationError(
            "genesis commit is invalid"
        ) from exc
    if not same_wire_value(commit, parsed):
        raise GenesisPayloadReobservationError("genesis commit is forged")
    if not same_wire_value(_observed_values(value), _expected_values(parsed)):
        raise GenesisPayloadReobservationError(
            "genesis observation contradicts the selected commit"
        )
    return value


def require_genesis_payload_execution_authorized(value: object) -> None:
    """Never treat point-in-time payload evidence as execution authority."""
    if type(value) is not GenesisPayloadReobservationV1:
        raise GenesisPayloadReobservationError(
            "genesis observation type is invalid"
        )
    raise GenesisPayloadReobservationError(
        "genesis payload reobservation is not execution-authorized"
    )
