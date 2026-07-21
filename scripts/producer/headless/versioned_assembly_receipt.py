"""Assembly receipt V2 with an explicit origin-or-assembly parent authority."""

from __future__ import annotations

from dataclasses import dataclass

from . import approved_parent_assembly_values as values
from . import quality_receipt_json as wire
from .artifact_contract import ArtifactRefV1, MediaRefV1
from .quality_pass_contract import GraphicAssetRefV1
from .repair_intent import ParentRefV1
from .versioned_parent_authority import ParentAuthorityV2, parse_parent_authority_v2

AssemblyReceiptV2Error = wire.QualityReceiptSchemaError
AssemblyCompositorProofV1 = values.AssemblyCompositorProofV1
_TOP_KEYS = frozenset(
    "base compositor graphics output parent parentAuthority plan qualityPolicyId "
    "requestDigest schemaVersion status".split()
)
_PLAN_KEYS = frozenset("artifact baseProjectionDigest planDigest".split())
_BASE_KEYS = frozenset("baseReceiptSha256 media timelineMapSha256".split())
_OUTPUT_KEYS = frozenset("cover coverProof final proxyDisposition".split())


@dataclass(frozen=True)
class AssemblyReceiptV2:
    """Private quality-pass receipt with no origin-as-assembly alias."""

    request_digest: str
    quality_policy_id: str
    parent: ParentRefV1
    parent_authority: ParentAuthorityV2
    plan: ArtifactRefV1
    plan_digest: str
    base_projection_digest: str
    base: MediaRefV1
    base_receipt_sha256: str
    timeline_map_sha256: str
    asset_set_digest: str
    assets: tuple[GraphicAssetRefV1, ...]
    clip_set_digest: str
    clips_artifact: ArtifactRefV1
    compositor: AssemblyCompositorProofV1
    final: MediaRefV1
    cover: ArtifactRefV1
    cover_proof: ArtifactRefV1
    document_json: bytes


def _parsed(document: dict, raw: bytes) -> AssemblyReceiptV2:
    wire.exact(document, _TOP_KEYS, "assembly receipt V2")
    valid = (
        type(document["schemaVersion"]) is int
        and document["schemaVersion"] == 2
        and document["status"] == "complete-private-quality-pass-v2"
    )
    if not valid:
        raise AssemblyReceiptV2Error("assembly receipt V2 envelope is invalid")
    plan = wire.exact(document["plan"], _PLAN_KEYS, "assembly V2 plan")
    base = wire.exact(document["base"], _BASE_KEYS, "assembly V2 base")
    assets, graphics = values.parse_graphics(document["graphics"])
    output = wire.exact(document["output"], _OUTPUT_KEYS, "assembly V2 output")
    if output["proxyDisposition"] != "omitted-by-policy":
        raise AssemblyReceiptV2Error("assembly V2 proxy disposition is invalid")
    return AssemblyReceiptV2(
        wire.digest(document["requestDigest"], "assembly V2 request digest"),
        wire.digest(document["qualityPolicyId"], "assembly V2 quality policy"),
        values.parse_parent(document["parent"]),
        parse_parent_authority_v2(document["parentAuthority"]),
        wire.artifact(plan["artifact"]),
        wire.digest(plan["planDigest"], "assembly V2 plan digest"),
        wire.digest(plan["baseProjectionDigest"], "assembly V2 base projection"),
        values.parse_media(base["media"]),
        wire.digest(base["baseReceiptSha256"], "assembly V2 base receipt"),
        wire.digest(base["timelineMapSha256"], "assembly V2 timeline map"),
        wire.digest(graphics["assetSetDigest"], "assembly V2 graphic assets"),
        assets,
        wire.digest(graphics["clipSetDigest"], "assembly V2 clip set"),
        wire.artifact(graphics["clipsArtifact"]),
        values.parse_compositor(document["compositor"]),
        values.parse_media(output["final"]),
        wire.artifact(output["cover"]),
        wire.artifact(output["coverProof"]),
        raw,
    )


def _artifact_paths(value: AssemblyReceiptV2) -> tuple[str, ...]:
    return (
        value.plan.relative_path,
        value.base.artifact.relative_path,
        value.clips_artifact.relative_path,
        value.final.artifact.relative_path,
        value.cover.relative_path,
        value.cover_proof.relative_path,
        *(
            ref.relative_path
            for asset in value.assets
            for ref in (asset.media.artifact, asset.receipt)
        ),
    )


def parse_assembly_receipt_v2(raw: object) -> AssemblyReceiptV2:
    """Parse exact canonical V2 bytes with a required parent discriminant."""
    document = wire.canonical_document(raw, "assembly receipt V2")
    parsed = _parsed(document, raw)
    paths = tuple(path.casefold() for path in _artifact_paths(parsed))
    if len(paths) != len(set(paths)):
        raise AssemblyReceiptV2Error("assembly V2 artifact paths alias")
    return parsed


def validate_assembly_receipt_v2(value: object) -> None:
    """Reject direct construction that differs from authoritative V2 bytes."""
    valid = type(value) is AssemblyReceiptV2 and type(value.document_json) is bytes
    if not valid:
        raise AssemblyReceiptV2Error("assembly receipt V2 instance is invalid")
    parsed = parse_assembly_receipt_v2(value.document_json)
    if not wire.same_typed_value(value, parsed):
        raise AssemblyReceiptV2Error("assembly receipt V2 construction is invalid")
