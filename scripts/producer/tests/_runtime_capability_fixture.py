"""Self-consistent runtime/build/assembly/quality structural fixture."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass

from _assembly_receipt_fixture import _Builder, _artifact_dict, canonical, decoded
from _assembly_receipt_manifest_fixture import build_commit
from _runtime_capability_evidence_fixture import (
    RuntimeEvidenceContext,
    audit_document,
    effect_document,
    full_decode_document,
)
from headless.approved_parent_assembly_receipt import parse_assembly_receipt_v1
from headless.approved_parent_quality_evidence import (
    parse_approved_parent_quality_evidence_v1,
)
from headless.approved_parent_schema import parse_approved_parent_descriptor
from headless.artifact_contract import ArtifactRefV1
from headless.generation_schema import parse_generation_commit
from headless.runtime_capability_binding import RuntimeCapabilityBindingV1
from headless.runtime_capability_manifest import (
    parse_runtime_capability_manifest_v1,
)

DocumentMutator = Callable[[str, dict], None]


@dataclass(frozen=True)
class RuntimeCapabilityFixture:
    """One parse-valid immutable input set for runtime structural binding."""

    binding: RuntimeCapabilityBindingV1


def _ref_for_raw(path: str, raw: bytes) -> ArtifactRefV1:
    return ArtifactRefV1(path, hashlib.sha256(raw).hexdigest(), len(raw))


def _class_ref(commit: object, artifact_class: str) -> ArtifactRefV1:
    row = next(item for item in commit.files if item.artifact_class == artifact_class)
    return ArtifactRefV1(row.path, row.sha256, row.size_bytes)


def _runtime_document(
    builder: _Builder,
    descriptor: dict,
    compositor: ArtifactRefV1,
    render: ArtifactRefV1,
) -> dict:
    return {
        "schemaVersion": 1,
        "status": "declared-not-runtime-verified",
        "realizationKind": "deterministic-mp4",
        "requestDigest": descriptor["identity"]["requestDigest"],
        "qualityPolicyId": descriptor["policies"]["qualityPolicyId"],
        "tools": {
            "ffmpeg": {
                "sha256": builder.ffmpeg,
                "roles": ["compositor", "full-decode", "effect-proof", "audit-b"],
            },
            "ffprobe": {
                "sha256": builder.ffprobe,
                "roles": [
                    "media-probe",
                    "full-decode-counts",
                    "effect-proof",
                    "audit-b",
                ],
            },
        },
        "builds": {
            "compositor": {
                "artifact": _artifact_dict(compositor),
                "buildDigest": builder.build_digest,
            },
            "render": {
                "artifact": _artifact_dict(render),
                "buildDigest": builder.asset.render_build_digest,
            },
        },
        "closure": {
            "staticManifest": "declared",
            "executableReobservation": "not-proved",
            "dynamicLibraryClosure": "not-proved",
            "executionAttestation": "not-proved",
        },
    }


def _mutate(mutator: DocumentMutator | None, stage: str, document: dict) -> None:
    if mutator is not None:
        mutator(stage, document)


def _stage_evidence(
    builder: _Builder,
    descriptor: dict,
    runtime_ref: ArtifactRefV1,
    mutator: DocumentMutator | None,
) -> tuple[bytes, bytes, bytes]:
    context = RuntimeEvidenceContext(builder, descriptor, runtime_ref)
    full = full_decode_document(context)
    _mutate(mutator, "full-decode", full)
    full_raw = canonical(full)
    full_ref = _ref_for_raw(descriptor["quality"]["fullDecode"]["path"], full_raw)
    effect = effect_document(context)
    _mutate(mutator, "effect-proof", effect)
    effect_raw = canonical(effect)
    effect_ref = _ref_for_raw(descriptor["quality"]["effectProof"]["path"], effect_raw)
    audit = audit_document(context, full_ref, effect_ref)
    _mutate(mutator, "audit-b", audit)
    return full_raw, effect_raw, canonical(audit)


def _set_evidence_refs(descriptor: dict, raws: tuple[bytes, bytes, bytes]) -> tuple:
    keys = ("fullDecode", "effectProof", "audit")
    classes = ("full-decode-proof-v1", "effect-proof-v1", "audit-b-receipt-v1")
    refs = []
    for key, artifact_class, raw in zip(keys, classes, raws):
        ref = _ref_for_raw(descriptor["quality"][key]["path"], raw)
        descriptor["quality"][key] = _artifact_dict(ref)
        refs.append((artifact_class, ref))
    return tuple(refs)


def _commit(
    builder: _Builder,
    descriptor: dict,
    descriptor_raw: bytes,
    refs: tuple,
) -> object:
    document = decoded(build_commit(builder, descriptor, descriptor_raw).document_json)
    by_class = dict(refs)
    for row in document["files"]:
        ref = by_class.get(row["artifactClass"])
        if ref is not None:
            row.update(_artifact_dict(ref))
    document["files"].sort(key=lambda row: row["path"])
    return parse_generation_commit(canonical(document))


def runtime_capability_fixture(
    mutator: DocumentMutator | None = None,
) -> RuntimeCapabilityFixture:
    """Build one exact structural runtime card and all of its downstream claims."""
    builder = _Builder()
    descriptor = builder.descriptor_document()
    provisional_raw = canonical(descriptor)
    provisional = build_commit(builder, descriptor, provisional_raw)
    render = _class_ref(provisional, "render-build-receipt-v1")
    runtime = _runtime_document(builder, descriptor, builder.build_receipt, render)
    _mutate(mutator, "runtime", runtime)
    runtime_raw = canonical(runtime)
    runtime_path = descriptor["provenance"]["runtimeCapabilityManifest"]["path"]
    runtime_ref = _ref_for_raw(runtime_path, runtime_raw)
    descriptor["provenance"]["runtimeCapabilityManifest"] = _artifact_dict(runtime_ref)
    evidence_raws = _stage_evidence(builder, descriptor, runtime_ref, mutator)
    evidence_refs = _set_evidence_refs(descriptor, evidence_raws)
    descriptor_raw = canonical(descriptor)
    role_refs = (
        ("runtime-capability-manifest-v1", runtime_ref),
        *evidence_refs,
    )
    commit = _commit(builder, descriptor, descriptor_raw, role_refs)
    evidence = parse_approved_parent_quality_evidence_v1(*evidence_raws)
    binding = RuntimeCapabilityBindingV1(
        parse_approved_parent_descriptor(descriptor_raw),
        commit,
        parse_runtime_capability_manifest_v1(runtime_raw),
        parse_assembly_receipt_v1(builder.assembly_raw),
        evidence,
    )
    return RuntimeCapabilityFixture(binding)
