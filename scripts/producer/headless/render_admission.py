"""Render-specific admission facade binding attempts to closed artifacts."""
from __future__ import annotations

import os
from dataclasses import dataclass

from .admission_registry import AdmissionRequest
from .durability_controller import (
    ControllerAdmissionOutcome,
    _trace,
    admit_attempt,
    resolve_attempt,
)
from .durable_files import locked_private_dir
from .render_admission_artifact import (
    RENDER_ARTIFACT_LOCK,
    RenderArtifactLocator,
    ResolvedRenderArtifact,
    load_render_admission_artifact,
)
from .terminal_manifest import (
    TerminalSealRequest,
    seal_terminal_manifest,
)


class RenderAdmissionError(RuntimeError):
    """An admission does not bind the exact retained render artifact."""


@dataclass(frozen=True)
class RenderAdmissionMetadata:
    """Non-render identities supplied when admitting a closed artifact."""

    authority_root: str
    authority_id: str
    idempotency_key: str
    attempt_id: str
    unit_id: str
    first_submitted_at: str
    release_id: str
    policy_id: str
    expected_parent: str | None


@dataclass(frozen=True)
class AdmittedRenderRef:
    """The only caller-visible locator after render admission."""

    authority_root: str
    attempt_id: str


@dataclass(frozen=True)
class ResolvedAdmittedRender:
    """Admission, attempt root, and artifact rederived from authority bytes."""

    admission: ControllerAdmissionOutcome
    attempt_root: str
    artifact: ResolvedRenderArtifact

    @property
    def reference(self) -> AdmittedRenderRef:
        """Return the replay-safe reference derived from the durable record."""
        return AdmittedRenderRef(
            os.path.dirname(os.path.dirname(self.attempt_root)),
            self.admission.record["attemptId"])


def _request(metadata: RenderAdmissionMetadata,
             artifact: ResolvedRenderArtifact) -> AdmissionRequest:
    return AdmissionRequest(
        authority_root=metadata.authority_root,
        authority_id=metadata.authority_id,
        idempotency_key=metadata.idempotency_key,
        request_identity_digest=artifact.artifact_digest,
        attempt_id=metadata.attempt_id, unit_id=metadata.unit_id,
        first_submitted_at=metadata.first_submitted_at,
        release_id=metadata.release_id, build_id=artifact.build_digest,
        policy_id=metadata.policy_id, expected_parent=metadata.expected_parent)


def _resolved(authority_root: str, admission: ControllerAdmissionOutcome,
              artifact: ResolvedRenderArtifact) -> ResolvedAdmittedRender:
    record = admission.record
    if (record["requestIdentityDigest"] != artifact.artifact_digest
            or record["buildId"] != artifact.build_digest):
        raise RenderAdmissionError(
            "admission request/build does not match render artifact")
    attempt_root = os.path.join(
        authority_root, "attempts", record["attemptId"])
    return ResolvedAdmittedRender(admission, attempt_root, artifact)


def _block_unavailable(authority_root: str,
                       admission: ControllerAdmissionOutcome) -> None:
    if admission.terminal_manifest is not None:
        return
    trace = _trace(
        authority_root, admission.record, admission.trace_state.boot_id)
    result = {"schemaVersion": 1,
              "errorCode": "RENDER_ARTIFACT_UNAVAILABLE",
              "evidenceDigest": admission.record["requestIdentityDigest"]}
    seal_terminal_manifest(TerminalSealRequest(trace, "BLOCKED", result))


def admit_render_artifact(
        metadata: RenderAdmissionMetadata, locator: RenderArtifactLocator,
        boot_id: str | None = None) -> ResolvedAdmittedRender:
    """Verify a closed artifact, then derive both admission digests from it."""
    with locked_private_dir(
            metadata.authority_root, RENDER_ARTIFACT_LOCK):
        artifact = load_render_admission_artifact(
            metadata.authority_root, locator)
        admission = admit_attempt(_request(metadata, artifact), boot_id)
        try:
            retained = load_render_admission_artifact(
                metadata.authority_root, locator)
        except Exception as exc:
            _block_unavailable(metadata.authority_root, admission)
            raise RenderAdmissionError(
                "render artifact became unavailable during admission") from exc
    return _resolved(metadata.authority_root, admission, retained)


def load_admitted_render(
        reference: AdmittedRenderRef,
        boot_id: str | None = None) -> ResolvedAdmittedRender:
    """Resolve an attempt to its sole admitted artifact without loose locators."""
    admission = resolve_attempt(
        reference.authority_root, reference.attempt_id, boot_id)
    record = admission.record
    locator = RenderArtifactLocator(record["requestIdentityDigest"])
    with locked_private_dir(
            reference.authority_root, RENDER_ARTIFACT_LOCK):
        artifact = load_render_admission_artifact(
            reference.authority_root, locator)
    return _resolved(reference.authority_root, admission, artifact)
