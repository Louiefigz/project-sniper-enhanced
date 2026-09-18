"""Disk-real genesis, frozen-R0, and quality-pass V2 authority payloads."""

from __future__ import annotations

import hashlib
import json
import dataclasses
from dataclasses import dataclass

from _approved_parent_loader_documents import AuthorityDocuments
from _approved_parent_loader_values import artifact_path, canonical
from _assembly_receipt_fixture import assembly_fixture
from _genesis_r1_fixture import genesis_r1_fixture
from headless.approved_parent_schema import parse_approved_parent_descriptor
from headless.generation_schema import parse_generation_commit
from headless.operation_wire import parent_document
from headless.prebound_clips import parse_prebound_clips, prebound_clip_set_digest
from headless.quality_pass_outputs import graphic_asset_set_digest
from headless.repair_intent import ParentRefV1
from headless.versioned_assembly_receipt import parse_assembly_receipt_v2
from headless.versioned_parent_authority import (
    ParentAuthorityV2,
    parent_authority_document,
)
from headless.versioned_quality_pass_card import parse_quality_pass_approved_card_v2
from headless.versioned_quality_pass_types import QualityPassAuthorityInputsV2
from headless.versioned_quality_pass_verification import (
    parse_quality_pass_generation_verification_v2,
    quality_pass_payload_manifest_digest,
)

_GENERATION = "77777777-7777-4777-8777-777777777777"
_ATTEMPT = "88888888-8888-4888-8888-888888888888"
_REQUEST = "d" * 64


@dataclass(frozen=True)
class DiskAuthorityPayload:
    """One parsed commit and its exact disk payload closure."""

    commit: object
    files: dict[str, bytes]


@dataclass(frozen=True)
class QualityPassDiskAuthority:
    """Disk payload plus parsed authority inputs for expected-result checks."""

    inputs: QualityPassAuthorityInputsV2
    files: dict[str, bytes]


@dataclass(frozen=True)
class _VerificationParts:
    commit: object
    card: dict
    card_raw: bytes
    assembly_raw: bytes
    parent: ParentRefV1
    authority: ParentAuthorityV2


def _raw_ref(path: str, raw: bytes) -> dict:
    return {
        "path": path,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "sizeBytes": len(raw),
    }


def _receipt_media(value: dict) -> dict:
    result = json.loads(json.dumps(value))
    facts = result["facts"]
    facts["fps"] = [facts.pop("fpsNumerator"), facts.pop("fpsDenominator")]
    return result


def _receipt_graphic(value: dict) -> dict:
    return {
        "graphicId": value["graphicId"],
        "renderIntentDigest": value["renderIntentDigest"],
        "media": _receipt_media(value["media"]),
        "renderReceipt": value["receipt"],
        "renderArtifactDigest": value["renderArtifactDigest"],
        "renderBuildDigest": value["renderBuildDigest"],
    }


def _genesis_parent() -> tuple[ParentRefV1, ParentAuthorityV2]:
    inputs = genesis_r1_fixture().inputs
    ref = ParentRefV1(
        inputs.commit.authority_id,
        1,
        inputs.commit.generation_id,
        inputs.commit.commit_digest,
        inputs.approved_card.plan.approved_plan_digest,
    )
    authority = ParentAuthorityV2(
        "genesis-origin",
        "initialization-origin-receipt-v1",
        inputs.approved_card.origin.receipt,
    )
    return ref, authority


def _quality_card_document(r0: AuthorityDocuments, parent: ParentRefV1) -> dict:
    document = json.loads(r0.files[r0.commit.approved_parent_path])
    document.update(
        {
            "schemaVersion": 2,
            "status": "approved-private-quality-pass-generation",
            "expectedParent": parent_document(parent),
        }
    )
    document["identity"].update(
        {
            "generationId": _GENERATION,
            "attemptId": _ATTEMPT,
            "requestDigest": _REQUEST,
        }
    )
    return document


def _receipt_sections(r0: AuthorityDocuments, card: dict) -> dict:
    descriptor = parse_approved_parent_descriptor(
        r0.files[r0.commit.approved_parent_path]
    )
    clips = parse_prebound_clips(r0.files[artifact_path("prebound-clips-v1")])
    return {
        "plan": {
            "artifact": card["plan"]["artifact"],
            "planDigest": card["plan"]["approvedPlanDigest"],
            "baseProjectionDigest": card["plan"]["baseProjectionDigest"],
        },
        "base": {
            "media": _receipt_media(card["base"]["media"]),
            "baseReceiptSha256": card["base"]["receipt"]["sha256"],
            "timelineMapSha256": card["base"]["timelineMap"]["sha256"],
        },
        "graphics": {
            "assetSetDigest": graphic_asset_set_digest(descriptor.graphics.assets),
            "assets": [_receipt_graphic(value) for value in card["graphics"]["assets"]],
            "clipSetDigest": prebound_clip_set_digest(clips),
            "clipsArtifact": card["graphics"]["preboundClips"],
        },
        "output": {
            "final": _receipt_media(card["output"]["final"]),
            "cover": card["output"]["cover"],
            "coverProof": card["output"]["coverProof"],
            "proxyDisposition": "omitted-by-policy",
        },
    }


def _quality_receipt_document(
    r0: AuthorityDocuments,
    card: dict,
    parent: ParentRefV1,
    authority: ParentAuthorityV2,
) -> dict:
    template = json.loads(assembly_fixture().receipt.document_json)
    template.update(
        {
            "schemaVersion": 2,
            "status": "complete-private-quality-pass-v2",
            "requestDigest": _REQUEST,
            "qualityPolicyId": card["policies"]["qualityPolicyId"],
            "parent": parent_document(parent),
            "parentAuthority": parent_authority_document(authority),
            **_receipt_sections(r0, card),
        }
    )
    template.pop("parentAssemblyReceiptSha256")
    proof = template["compositor"]
    proof["framesIn"] = card["base"]["media"]["facts"]["frameCount"]
    proof["framesOut"] = card["output"]["final"]["facts"]["frameCount"]
    proof["audio"]["baseSha256"] = card["base"]["media"]["artifact"]["sha256"]
    proof["audio"]["finalSha256"] = proof["audio"]["baseSha256"]
    return template


def _rows(files: dict[str, bytes], classes: dict[str, str]) -> list[dict]:
    return [
        {"artifactClass": classes[path], **_raw_ref(path, raw)}
        for path, raw in sorted(files.items())
    ]


def _commit_document(
    card: dict,
    parent: ParentRefV1,
    files: dict[str, bytes],
    classes: dict[str, str],
) -> dict:
    return {
        "schemaVersion": 1,
        **card["identity"],
        "expectedParent": parent_document(parent),
        **card["policies"],
        "approvedParentPath": artifact_path("approved-parent-v1"),
        "files": _rows(files, classes),
    }


def _verification_document(parts: _VerificationParts) -> dict:
    payload = tuple(
        row
        for row in parts.commit.files
        if row.artifact_class != "quality-pass-generation-verification-v2"
    )
    return {
        "schemaVersion": 2,
        "status": "structural-pass-runtime-unverified",
        "profile": "deterministic-mp4-quality-pass-r1-v2",
        "expectedParent": parent_document(parts.parent),
        "identity": parts.card["identity"],
        "policies": parts.card["policies"],
        "approvedCard": _raw_ref(artifact_path("approved-parent-v1"), parts.card_raw),
        "assemblyReceipt": _raw_ref(
            artifact_path("assembly-receipt-v1"), parts.assembly_raw
        ),
        "parentAuthority": parent_authority_document(parts.authority),
        "payloadManifestDigest": quality_pass_payload_manifest_digest(payload),
    }


def quality_pass_v2_disk_authority() -> QualityPassDiskAuthority:
    """Build one all-real-bytes V2 CURRENT over a genesis-origin parent."""
    r0 = AuthorityDocuments()
    files, classes = dict(r0.files), dict(r0.classes)
    parent, authority = _genesis_parent()
    card = _quality_card_document(r0, parent)
    assembly_raw = canonical(_quality_receipt_document(r0, card, parent, authority))
    assembly_path = artifact_path("assembly-receipt-v1")
    files[assembly_path] = assembly_raw
    classes[assembly_path] = "assembly-receipt-v2"
    card["output"]["assemblyReceipt"] = _raw_ref(assembly_path, assembly_raw)
    card_raw = canonical(card)
    card_path = artifact_path("approved-parent-v1")
    files[card_path] = card_raw
    classes[card_path] = "quality-pass-approved-card-v2"
    verify_path = artifact_path("generation-verification-v1")
    files[verify_path] = b"provisional"
    classes[verify_path] = "quality-pass-generation-verification-v2"
    provisional = parse_generation_commit(
        _commit_document(card, parent, files, classes)
    )
    verification_raw = canonical(
        _verification_document(
            _VerificationParts(
                provisional, card, card_raw, assembly_raw, parent, authority
            )
        )
    )
    files[verify_path] = verification_raw
    commit = parse_generation_commit(_commit_document(card, parent, files, classes))
    inputs = QualityPassAuthorityInputsV2(
        commit,
        parse_quality_pass_approved_card_v2(card_raw),
        parse_assembly_receipt_v2(assembly_raw),
        parse_quality_pass_generation_verification_v2(verification_raw),
    )
    return QualityPassDiskAuthority(inputs, files)


def frozen_r0_quality_pass_disk_authority() -> DiskAuthorityPayload:
    """Give frozen R0 a real non-null immediate parent without changing R0 rows."""
    r0 = AuthorityDocuments()
    document = json.loads(r0.commit.document_json)
    parent = dataclasses.replace(
        _genesis_parent()[0],
        generation_id="99999999-9999-4999-8999-999999999999",
    )
    document["expectedParent"] = parent_document(parent)
    return DiskAuthorityPayload(parse_generation_commit(canonical(document)), r0.files)
