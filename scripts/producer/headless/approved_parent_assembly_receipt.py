"""Exact semantic wire record emitted by the private R0 compositor."""

from __future__ import annotations

from . import approved_parent_assembly_values as values
from . import quality_receipt_json as wire

AssemblyReceiptSchemaError = values.AssemblyReceiptSchemaError
AssemblyCompositorProofV1 = values.AssemblyCompositorProofV1
AssemblyReceiptV1 = values.AssemblyReceiptV1
_TOP_KEYS = frozenset(
    "base compositor graphics output parent parentAssemblyReceiptSha256 plan "
    "qualityPolicyId requestDigest schemaVersion status".split()
)
_PLAN_KEYS = frozenset("artifact baseProjectionDigest planDigest".split())
_BASE_KEYS = frozenset("baseReceiptSha256 media timelineMapSha256".split())
_OUTPUT_KEYS = frozenset("cover coverProof final proxyDisposition".split())


def _parsed(document: dict, raw: bytes) -> AssemblyReceiptV1:
    wire.exact(document, _TOP_KEYS, "assembly receipt")
    valid = (
        type(document["schemaVersion"]) is int
        and document["schemaVersion"] == 1
        and document["status"] == "complete-private-counterfactual"
    )
    if not valid:
        raise AssemblyReceiptSchemaError("assembly receipt envelope is invalid")
    plan = wire.exact(document["plan"], _PLAN_KEYS, "assembly plan")
    base = wire.exact(document["base"], _BASE_KEYS, "assembly base")
    assets, graphics = values.parse_graphics(document["graphics"])
    output = wire.exact(document["output"], _OUTPUT_KEYS, "assembly output")
    if output["proxyDisposition"] != "omitted-by-policy":
        raise AssemblyReceiptSchemaError("assembly proxy disposition is invalid")
    return AssemblyReceiptV1(
        wire.digest(document["requestDigest"], "assembly request digest"),
        wire.digest(document["qualityPolicyId"], "assembly quality policy"),
        values.parse_parent(document["parent"]),
        wire.digest(document["parentAssemblyReceiptSha256"], "parent assembly"),
        wire.artifact(plan["artifact"]),
        wire.digest(plan["planDigest"], "assembly plan digest"),
        wire.digest(plan["baseProjectionDigest"], "base projection digest"),
        values.parse_media(base["media"]),
        wire.digest(base["baseReceiptSha256"], "base receipt digest"),
        wire.digest(base["timelineMapSha256"], "timeline map digest"),
        wire.digest(graphics["assetSetDigest"], "graphic asset set digest"),
        assets,
        wire.digest(graphics["clipSetDigest"], "clip set digest"),
        wire.artifact(graphics["clipsArtifact"]),
        values.parse_compositor(document["compositor"]),
        values.parse_media(output["final"]),
        wire.artifact(output["cover"]),
        wire.artifact(output["coverProof"]),
        raw,
    )


def parse_assembly_receipt_v1(raw: object) -> AssemblyReceiptV1:
    """Parse only the exact canonical bytes emitted by ``build_assembly_receipt``."""
    document = wire.canonical_document(raw, "assembly receipt")
    parsed = _parsed(document, raw)
    paths = (
        parsed.plan.relative_path,
        parsed.base.artifact.relative_path,
        parsed.clips_artifact.relative_path,
        parsed.final.artifact.relative_path,
        parsed.cover.relative_path,
        parsed.cover_proof.relative_path,
        *(
            ref.relative_path
            for asset in parsed.assets
            for ref in (asset.media.artifact, asset.receipt)
        ),
    )
    if len(paths) != len(set(paths)):
        raise AssemblyReceiptSchemaError("assembly artifact paths alias")
    return parsed


def validate_assembly_receipt_v1(value: object) -> None:
    """Reject direct construction that differs from the authoritative bytes."""
    if type(value) is not AssemblyReceiptV1 or type(value.document_json) is not bytes:
        raise AssemblyReceiptSchemaError("assembly receipt instance is invalid")
    parsed = parse_assembly_receipt_v1(value.document_json)
    if not wire.same_typed_value(value, parsed):
        raise AssemblyReceiptSchemaError("assembly receipt construction is invalid")
