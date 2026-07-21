"""Exact quality-pass V2 child fixture over a supplied parent authority."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass

from _approved_parent_loader_values import canonical
from _assembly_receipt_fixture import assembly_fixture
from _quality_pass_v2_fixture_manifest import finish_quality_pass_v2_fixture
from headless.artifact_contract import ArtifactRefV1, MediaRefV1
from headless.operation_wire import parent_document
from headless.repair_intent import ParentRefV1
from headless.versioned_assembly_receipt import parse_assembly_receipt_v2
from headless.versioned_parent_authority import (
    ParentAuthorityV2,
    parent_authority_document,
)
from headless.versioned_quality_pass_card import parse_quality_pass_approved_card_v2
from headless.versioned_quality_pass_types import QualityPassAuthorityInputsV2

_IDENTITIES = (
    (
        "77777777-7777-4777-8777-777777777777",
        "88888888-8888-4888-8888-888888888888",
        "d" * 64,
    ),
    (
        "99999999-9999-4999-8999-999999999999",
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "e" * 64,
    ),
)


@dataclass(frozen=True)
class QualityPassV2Fixture:
    """Parsed current V2 inputs and their parent-facing authority values."""

    inputs: QualityPassAuthorityInputsV2
    parent_ref: ParentRefV1
    parent_authority: ParentAuthorityV2


def decoded(raw: bytes) -> dict:
    return json.loads(raw)


def changed(raw: bytes, path: tuple, value: object) -> bytes:
    document = decoded(raw)
    target = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return canonical(document)


def _artifact_document(ref: ArtifactRefV1) -> dict:
    return {
        "path": ref.relative_path,
        "sha256": ref.sha256,
        "sizeBytes": ref.size_bytes,
    }


def _raw_ref(path: str, raw: bytes) -> dict:
    return {
        "path": path,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "sizeBytes": len(raw),
    }


def _descriptor_media(media: MediaRefV1) -> dict:
    facts = media.facts
    return {
        "artifact": _artifact_document(media.artifact),
        "facts": {
            "width": facts.width,
            "height": facts.height,
            "durationSeconds": facts.duration_seconds,
            "fpsNumerator": facts.fps_numerator,
            "fpsDenominator": facts.fps_denominator,
            "frameCount": facts.frame_count,
            "sizeBytes": facts.size_bytes,
            "videoCodec": facts.video_codec,
            "pixelFormat": facts.pixel_format,
            "profile": facts.profile,
            "alphaMode": facts.alpha_mode,
            "audioCodec": facts.audio_codec,
        },
    }


def _receipt_media(media: MediaRefV1) -> dict:
    value = _descriptor_media(media)
    facts = value["facts"]
    facts["fps"] = [facts.pop("fpsNumerator"), facts.pop("fpsDenominator")]
    return value


def _current_final(initial: object, parent_card: object) -> MediaRefV1:
    artifact = initial.receipt.final.artifact
    facts = dataclasses.replace(
        parent_card.base.media.facts, size_bytes=artifact.size_bytes
    )
    return MediaRefV1(artifact, facts)


def _receipt_document(
    initial: object,
    parent_ref: ParentRefV1,
    authority: ParentAuthorityV2,
    parent: object,
) -> dict:
    document = decoded(initial.receipt.document_json)
    final = _current_final(initial, parent)
    document["schemaVersion"] = 2
    document["status"] = "complete-private-quality-pass-v2"
    document["parent"] = parent_document(parent_ref)
    document.pop("parentAssemblyReceiptSha256")
    document["parentAuthority"] = parent_authority_document(authority)
    document["plan"]["baseProjectionDigest"] = parent.plan.base_projection_digest
    document["base"] = {
        "media": _receipt_media(parent.base.media),
        "baseReceiptSha256": parent.base.receipt.sha256,
        "timelineMapSha256": parent.base.timeline_map.sha256,
    }
    document["compositor"]["framesIn"] = parent.base.media.facts.frame_count
    document["compositor"]["framesOut"] = final.facts.frame_count
    document["output"]["final"] = _receipt_media(final)
    return document


def _card_document(
    initial: object, receipt_raw: bytes, parent_ref: ParentRefV1, parent: object
) -> dict:
    document = decoded(initial.descriptor.document_json)
    generation, attempt, request = _IDENTITIES[0]
    document["schemaVersion"] = 2
    document["status"] = "approved-private-quality-pass-generation"
    document["expectedParent"] = parent_document(parent_ref)
    document["identity"]["generationId"] = generation
    document["identity"]["attemptId"] = attempt
    document["identity"]["requestDigest"] = request
    document["plan"]["baseProjectionDigest"] = parent.plan.base_projection_digest
    document["base"] = {
        "media": _descriptor_media(parent.base.media),
        "planArtifact": _artifact_document(parent.base.plan_artifact),
        "receipt": _artifact_document(parent.base.receipt),
        "timelineMap": _artifact_document(parent.base.timeline_map),
    }
    final = _current_final(initial, parent)
    document["output"]["final"] = _descriptor_media(final)
    assembly_path = document["output"]["assemblyReceipt"]["path"]
    document["output"]["assemblyReceipt"] = _raw_ref(assembly_path, receipt_raw)
    return document


def build_quality_pass_v2_child(
    parent_ref: ParentRefV1,
    parent_card: object,
    parent_authority: ParentAuthorityV2,
    identity_index: int = 0,
) -> QualityPassV2Fixture:
    """Build one structurally exact V2 child over origin or assembly authority."""
    initial = assembly_fixture()
    identity = _IDENTITIES[identity_index]
    receipt_document = _receipt_document(
        initial, parent_ref, parent_authority, parent_card
    )
    receipt_document["requestDigest"] = identity[2]
    receipt_raw = canonical(receipt_document)
    receipt = parse_assembly_receipt_v2(receipt_raw)
    card_document = _card_document(initial, receipt_raw, parent_ref, parent_card)
    card_document["identity"]["generationId"] = identity[0]
    card_document["identity"]["attemptId"] = identity[1]
    card_document["identity"]["requestDigest"] = identity[2]
    card_raw = canonical(card_document)
    card = parse_quality_pass_approved_card_v2(card_raw)
    commit, verification = finish_quality_pass_v2_fixture(initial, card, receipt)
    inputs = QualityPassAuthorityInputsV2(commit, card, receipt, verification)
    return QualityPassV2Fixture(inputs, parent_ref, parent_authority)
