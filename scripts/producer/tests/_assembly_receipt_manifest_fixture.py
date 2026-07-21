"""R0 manifest construction for the assembly receipt fixture."""

from __future__ import annotations

import hashlib
import json
from typing import Protocol

from headless.artifact_contract import ArtifactRefV1
from headless.generation_profile import R0_GENERATION_ARTIFACT_CLASS_COUNTS
from headless.generation_schema import parse_generation_commit


class AssemblyBuilder(Protocol):
    plan_ref: ArtifactRefV1
    parent: object
    clips_ref: ArtifactRefV1
    build_receipt: ArtifactRefV1
    asset: object
    final: object
    cover: ArtifactRefV1
    cover_proof: ArtifactRefV1


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("ascii")


def _ref(value: ArtifactRefV1) -> dict:
    return {
        "path": value.relative_path,
        "sha256": value.sha256,
        "sizeBytes": value.size_bytes,
    }


def _placeholder(artifact_class: str, ordinal: int) -> ArtifactRefV1:
    raw = f"{artifact_class}:{ordinal}".encode("ascii")
    return ArtifactRefV1(
        f"manifest/{artifact_class}-{ordinal}.bin",
        hashlib.sha256(raw).hexdigest(),
        len(raw),
    )


def _relevant(builder: AssemblyBuilder, document: dict, raw: bytes) -> dict:
    output = document["output"]["assemblyReceipt"]
    return {
        "approved-parent-v1": ArtifactRefV1(
            "authority/approved-parent.json", hashlib.sha256(raw).hexdigest(), len(raw)
        ),
        "plan-v1": builder.plan_ref,
        "base-media-v1": builder.parent.base.artifact,
        "base-plan-v1": builder.parent.base_plan,
        "base-receipt-v1": builder.parent.base_receipt,
        "timeline-map-v1": builder.parent.timeline_map,
        "prebound-clips-v1": builder.clips_ref,
        "render-build-receipt-v1": ArtifactRefV1("build/render.json", "e" * 64, 100),
        "compositor-build-receipt-v1": builder.build_receipt,
        "graphic-media-v1": builder.asset.media.artifact,
        "graphic-render-receipt-v1": builder.asset.receipt,
        "final-media-v1": builder.final.artifact,
        "assembly-receipt-v1": ArtifactRefV1(
            output["path"], output["sha256"], output["sizeBytes"]
        ),
        "cover-image-v1": builder.cover,
        "cover-proof-v1": builder.cover_proof,
    }


def _manifest(builder: AssemblyBuilder, document: dict, raw: bytes) -> list[dict]:
    relevant = _relevant(builder, document, raw)
    rows = []
    for artifact_class, count in R0_GENERATION_ARTIFACT_CLASS_COUNTS.items():
        for ordinal in range(count):
            ref = relevant.get(artifact_class) or _placeholder(artifact_class, ordinal)
            rows.append({"artifactClass": artifact_class, **_ref(ref)})
    return sorted(rows, key=lambda row: row["path"])


def build_commit(builder: AssemblyBuilder, document: dict, raw: bytes) -> object:
    """Build the exact child commit selected by the assembly fixture."""
    parent = builder.parent.ref
    parent_row = {
        "authorityId": parent.authority_id,
        "publicationSeq": parent.publication_seq,
        "generationId": parent.generation_id,
        "commitDigest": parent.commit_digest,
        "planDigest": parent.plan_digest,
    }
    commit = {
        "schemaVersion": 1,
        **document["identity"],
        "expectedParent": parent_row,
        **document["policies"],
        "approvedParentPath": "authority/approved-parent.json",
        "files": _manifest(builder, document, raw),
    }
    return parse_generation_commit(_canonical(commit))
