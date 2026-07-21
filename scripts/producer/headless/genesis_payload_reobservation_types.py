"""Path-free evidence types for streamed genesis R1 payload observation."""

from __future__ import annotations

from dataclasses import dataclass

from .artifact_contract import ArtifactRefV1

GENESIS_PAYLOAD_REOBSERVATION_STATUS = (
    "GENESIS_R1_FULL_PAYLOAD_STREAM_REOBSERVED_NOT_RUNTIME_AUTHORIZED"
)


@dataclass(frozen=True)
class ObservedGenesisArtifactV1:
    """One committed class and relative artifact identity, never a host path."""

    artifact_class: str
    artifact: ArtifactRefV1


@dataclass(frozen=True)
class GenesisPayloadReobservationV1:
    """Point-in-time proof that every selected payload byte was reobserved."""

    status: str
    profile: str
    authority_id: str
    generation_id: str
    commit_digest: str
    manifest_evidence_digest: str
    payload_manifest_digest: str
    artifacts: tuple[ObservedGenesisArtifactV1, ...]
    artifact_count: int
    total_size_bytes: int
    exact_materialization_closure_bound: bool
    complete_manifest_reobserved: bool
    final_current_rechecked: bool
    runtime_verified: bool
    execution_authorized: bool
    publication_authorized: bool
