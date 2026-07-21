"""Shared exact wire values for headless MP4 operation contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from . import quality_receipt_json as wire
from .artifact_contract import ArtifactRefV1, validate_artifact_ref
from .repair_intent import ParentRefV1, validate_parent_ref

OperationWireError = wire.QualityReceiptSchemaError
_PARENT_KEYS = frozenset(
    "authorityId commitDigest generationId planDigest publicationSeq".split()
)
_SNAPSHOT_KEYS = frozenset(
    "archive authorityKind manifest sealReceipt snapshotId".split()
)
_SNAPSHOT_DOMAIN = b"sniper-presealed-initialization-snapshot-v1\0"


@dataclass(frozen=True)
class InitializationSnapshotAuthorityV1:
    """Three immutable refs and their domain-separated snapshot identity."""

    snapshot_id: str
    archive: ArtifactRefV1
    manifest: ArtifactRefV1
    seal_receipt: ArtifactRefV1


def canonical(value: object) -> bytes:
    """Encode one exact ASCII JSON value for a derived identity."""
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise OperationWireError("operation JSON cannot be canonicalized") from exc
    return encoded.encode("ascii")


def parse_parent(value: object) -> ParentRefV1:
    """Parse the exact five-field non-null approved-parent reference."""
    row = wire.exact(value, _PARENT_KEYS, "operation expected parent")
    parent = ParentRefV1(
        wire.authority(row["authorityId"]),
        row["publicationSeq"],
        wire.canonical_uuid(row["generationId"], "parent generation ID"),
        wire.digest(row["commitDigest"], "parent commit digest"),
        wire.digest(row["planDigest"], "parent plan digest"),
    )
    try:
        validate_parent_ref(parent)
    except RuntimeError as exc:
        raise OperationWireError("operation expected parent is invalid") from exc
    return parent


def parent_document(value: ParentRefV1) -> dict:
    """Return the canonical wire projection of a validated parent."""
    try:
        validate_parent_ref(value)
    except RuntimeError as exc:
        raise OperationWireError("operation expected parent is invalid") from exc
    return {
        "authorityId": value.authority_id,
        "publicationSeq": value.publication_seq,
        "generationId": value.generation_id,
        "commitDigest": value.commit_digest,
        "planDigest": value.plan_digest,
    }


def _artifact_document(value: ArtifactRefV1) -> dict:
    return {
        "path": value.relative_path,
        "sha256": value.sha256,
        "sizeBytes": value.size_bytes,
    }


def initialization_snapshot_id(
    archive: ArtifactRefV1,
    manifest: ArtifactRefV1,
    seal_receipt: ArtifactRefV1,
) -> str:
    """Derive the identity of the exact presealed immutable snapshot closure."""
    try:
        for ref in (archive, manifest, seal_receipt):
            validate_artifact_ref(ref)
    except RuntimeError as exc:
        raise OperationWireError("initialization snapshot refs are invalid") from exc
    value = {
        "authorityKind": "presealed-immutable-snapshot-v1",
        "archive": _artifact_document(archive),
        "manifest": _artifact_document(manifest),
        "sealReceipt": _artifact_document(seal_receipt),
    }
    return hashlib.sha256(_SNAPSHOT_DOMAIN + canonical(value)).hexdigest()


def parse_initialization_snapshot(value: object) -> InitializationSnapshotAuthorityV1:
    """Parse a closed presealed snapshot authority with no live-root fallback."""
    row = wire.exact(value, _SNAPSHOT_KEYS, "initialization snapshot")
    if row["authorityKind"] != "presealed-immutable-snapshot-v1":
        raise OperationWireError("initialization snapshot authority is invalid")
    archive = wire.artifact(row["archive"])
    manifest = wire.artifact(row["manifest"])
    seal = wire.artifact(row["sealReceipt"])
    refs = (archive, manifest, seal)
    paths = tuple(ref.relative_path.casefold() for ref in refs)
    digests = tuple(ref.sha256 for ref in refs)
    if len(set(paths)) != 3 or len(set(digests)) != 3:
        raise OperationWireError("initialization snapshot artifacts alias")
    expected = initialization_snapshot_id(archive, manifest, seal)
    actual = wire.digest(row["snapshotId"], "initialization snapshot ID")
    if actual != expected:
        raise OperationWireError("initialization snapshot identity is stale")
    return InitializationSnapshotAuthorityV1(actual, archive, manifest, seal)
