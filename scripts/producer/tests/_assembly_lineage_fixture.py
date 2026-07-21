"""Current assembly card bound to a real historical materialization."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass

from _assembly_receipt_fixture import assembly_fixture, canonical
from _historical_generation_fixture import HistoricalAuthorityFixture
from headless.approved_parent_assembly_receipt import parse_assembly_receipt_v1
from headless.approved_parent_schema import parse_approved_parent_descriptor
from headless.artifact_contract import ArtifactRefV1, MediaRefV1
from headless.generation_schema import parse_current_pointer, parse_generation_commit
from headless.historical_generation_resolver import resolve_historical_generation
from headless.historical_generation_types import (
    HistoricalGenerationMaterializationV1,
    HistoricalGenerationRecordV1,
)
from headless.repair_intent import ParentRefV1


def _artifact_document(ref: ArtifactRefV1) -> dict:
    return {
        "path": ref.relative_path,
        "sha256": ref.sha256,
        "sizeBytes": ref.size_bytes,
    }


def _parent_document(ref: ParentRefV1) -> dict:
    return {
        "authorityId": ref.authority_id,
        "publicationSeq": ref.publication_seq,
        "generationId": ref.generation_id,
        "commitDigest": ref.commit_digest,
        "planDigest": ref.plan_digest,
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
    facts = media.facts
    return {
        "artifact": _artifact_document(media.artifact),
        "facts": {
            "width": facts.width,
            "height": facts.height,
            "durationSeconds": facts.duration_seconds,
            "fps": [facts.fps_numerator, facts.fps_denominator],
            "frameCount": facts.frame_count,
            "sizeBytes": facts.size_bytes,
            "videoCodec": facts.video_codec,
            "pixelFormat": facts.pixel_format,
            "profile": facts.profile,
            "alphaMode": facts.alpha_mode,
            "audioCodec": facts.audio_codec,
        },
    }


def _changed_ref(ref: ArtifactRefV1, marker: str) -> ArtifactRefV1:
    return ArtifactRefV1(ref.relative_path, marker * 64, ref.size_bytes)


@dataclass(frozen=True)
class CurrentAssemblyV1:
    descriptor: object
    commit: object
    receipt: object


def _roles(historical: HistoricalGenerationMaterializationV1, scenario: str) -> dict:
    descriptor = historical.target.descriptor
    base = descriptor.base
    parent = historical.target.ref
    values = {
        "parent": parent,
        "parent_assembly": descriptor.output.assembly_receipt.sha256,
        "base": base.media,
        "base_plan": base.plan_artifact,
        "base_receipt": base.receipt,
        "timeline": base.timeline_map,
        "projection": descriptor.plan.base_projection_digest,
    }
    if scenario == "parent-target":
        values["parent"] = historical.lineage[-1].ref
    if scenario == "parent-assembly":
        values["parent_assembly"] = "0" * 64
    if scenario == "base-media":
        values["base"] = dataclasses.replace(
            base.media, artifact=_changed_ref(base.media.artifact, "6")
        )
    if scenario == "base-plan":
        values["base_plan"] = _changed_ref(base.plan_artifact, "2")
    if scenario == "base-receipt":
        values["base_receipt"] = _changed_ref(base.receipt, "3")
    if scenario == "timeline":
        values["timeline"] = _changed_ref(base.timeline_map, "4")
    if scenario == "projection":
        values["projection"] = "5" * 64
    return values


def _receipt(initial: object, roles: dict) -> tuple[object, bytes]:
    document = json.loads(initial.document_json)
    document["parent"] = _parent_document(roles["parent"])
    document["parentAssemblyReceiptSha256"] = roles["parent_assembly"]
    document["plan"]["baseProjectionDigest"] = roles["projection"]
    document["base"] = {
        "media": _receipt_media(roles["base"]),
        "baseReceiptSha256": roles["base_receipt"].sha256,
        "timelineMapSha256": roles["timeline"].sha256,
    }
    frames = roles["base"].facts.frame_count
    document["compositor"]["framesIn"] = frames
    document["compositor"]["framesOut"] = frames
    raw = canonical(document)
    return parse_assembly_receipt_v1(raw), raw


def _descriptor(
    initial: object, roles: dict, receipt_raw: bytes
) -> tuple[object, bytes]:
    document = json.loads(initial.document_json)
    document["plan"]["baseProjectionDigest"] = roles["projection"]
    document["base"] = {
        "media": _descriptor_media(roles["base"]),
        "planArtifact": _artifact_document(roles["base_plan"]),
        "receipt": _artifact_document(roles["base_receipt"]),
        "timelineMap": _artifact_document(roles["timeline"]),
    }
    assembly = document["output"]["assemblyReceipt"]
    assembly["sha256"] = hashlib.sha256(receipt_raw).hexdigest()
    assembly["sizeBytes"] = len(receipt_raw)
    raw = canonical(document)
    return parse_approved_parent_descriptor(raw), raw


def _replace_row(document: dict, artifact_class: str, ref: ArtifactRefV1) -> None:
    row = next(
        item for item in document["files"] if item["artifactClass"] == artifact_class
    )
    row.update(_artifact_document(ref))


def _commit(
    initial: object,
    roles: dict,
    descriptor_raw: bytes,
    receipt_raw: bytes,
) -> object:
    document = json.loads(initial.document_json)
    document["expectedParent"] = _parent_document(roles["parent"])
    descriptor_ref = ArtifactRefV1(
        document["approvedParentPath"],
        hashlib.sha256(descriptor_raw).hexdigest(),
        len(descriptor_raw),
    )
    receipt_row = next(
        item
        for item in document["files"]
        if item["artifactClass"] == "assembly-receipt-v1"
    )
    receipt_ref = ArtifactRefV1(
        receipt_row["path"], hashlib.sha256(receipt_raw).hexdigest(), len(receipt_raw)
    )
    replacements = {
        "approved-parent-v1": descriptor_ref,
        "assembly-receipt-v1": receipt_ref,
        "base-media-v1": roles["base"].artifact,
        "base-plan-v1": roles["base_plan"],
        "base-receipt-v1": roles["base_receipt"],
        "timeline-map-v1": roles["timeline"],
    }
    for artifact_class, ref in replacements.items():
        _replace_row(document, artifact_class, ref)
    document["files"] = sorted(document["files"], key=lambda row: row["path"])
    return parse_generation_commit(canonical(document))


def build_current(
    historical: HistoricalGenerationMaterializationV1, scenario: str = "success"
) -> CurrentAssemblyV1:
    initial = assembly_fixture()
    roles = _roles(historical, scenario)
    receipt, receipt_raw = _receipt(initial.receipt, roles)
    descriptor, descriptor_raw = _descriptor(initial.descriptor, roles, receipt_raw)
    commit = _commit(initial.commit, roles, descriptor_raw, receipt_raw)
    return CurrentAssemblyV1(descriptor, commit, receipt)


def _selected_history(
    historical: HistoricalGenerationMaterializationV1,
    current: CurrentAssemblyV1,
) -> HistoricalGenerationMaterializationV1:
    parent = historical.target
    child_ref = ParentRefV1(
        current.commit.authority_id,
        parent.ref.publication_seq + 1,
        current.commit.generation_id,
        current.commit.commit_digest,
        current.descriptor.plan.approved_plan_digest,
    )
    child = HistoricalGenerationRecordV1(child_ref, current.commit, current.descriptor)
    pointer = parse_current_pointer(
        canonical(
            {
                "schemaVersion": 1,
                "authorityId": child_ref.authority_id,
                "publicationSeq": child_ref.publication_seq,
                "generationId": child_ref.generation_id,
                "commitDigest": child_ref.commit_digest,
            }
        )
    )
    tail_index = historical.lineage.index(parent)
    return dataclasses.replace(
        historical,
        anchor_current=pointer,
        lineage=(child, *historical.lineage[tail_index:]),
    )


class AssemblyLineageFixture:
    """Real selected-chain target plus a structurally valid child assembly card."""

    def __init__(self, scenario: str = "success") -> None:
        self.authority = HistoricalAuthorityFixture()
        with resolve_historical_generation(
            str(self.authority.authority),
            str(self.authority.destination),
            self.authority.requested(1),
        ) as historical:
            self.historical = historical
        self.current = build_current(self.historical, scenario)
        self.historical = _selected_history(self.historical, self.current)

    def close(self) -> None:
        self.authority.close()
