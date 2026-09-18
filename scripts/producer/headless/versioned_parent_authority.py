"""Exact discriminant for genesis-origin versus prior-assembly parent authority."""

from __future__ import annotations

from dataclasses import dataclass

from . import quality_receipt_json as wire
from .artifact_contract import ArtifactRefV1

VersionedParentAuthorityError = wire.QualityReceiptSchemaError
_KEYS = frozenset("artifactClass kind receipt".split())
_VALID = frozenset(
    {
        ("genesis-origin", "initialization-origin-receipt-v1"),
        ("prior-assembly", "assembly-receipt-v1"),
        ("prior-assembly", "assembly-receipt-v2"),
    }
)


@dataclass(frozen=True)
class ParentAuthorityV2:
    """One non-aliasing parent authority receipt selected by exact class."""

    kind: str
    artifact_class: str
    receipt: ArtifactRefV1


def parse_parent_authority_v2(value: object) -> ParentAuthorityV2:
    """Parse a closed origin/assembly discriminant from a receipt section."""
    row = wire.exact(value, _KEYS, "parent authority")
    pair = (row["kind"], row["artifactClass"])
    if pair not in _VALID:
        raise VersionedParentAuthorityError("parent authority discriminant is invalid")
    return ParentAuthorityV2(pair[0], pair[1], wire.artifact(row["receipt"]))


def parent_authority_document(value: object) -> dict:
    """Return the exact wire projection of a validated parent authority."""
    if type(value) is not ParentAuthorityV2:
        raise VersionedParentAuthorityError("parent authority instance is invalid")
    document = {
        "kind": value.kind,
        "artifactClass": value.artifact_class,
        "receipt": {
            "path": value.receipt.relative_path,
            "sha256": value.receipt.sha256,
            "sizeBytes": value.receipt.size_bytes,
        },
    }
    parsed = parse_parent_authority_v2(document)
    if not wire.same_typed_value(value, parsed):
        raise VersionedParentAuthorityError("parent authority construction is invalid")
    return document
