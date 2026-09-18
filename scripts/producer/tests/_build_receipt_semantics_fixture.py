"""Self-consistent generation fixture with a real render build receipt."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import stat
from collections.abc import Callable

from _assembly_receipt_fixture import _Builder, _clip_bytes, canonical
from _graphic_render_receipt_fixture import (
    GraphicReceiptFixtureV1,
    graphic_receipt_fixture,
)
from _runtime_capability_fixture import (
    RuntimeCapabilityFixture,
    _commit,
    _ref_for_raw,
    _runtime_document,
    _set_evidence_refs,
    _stage_evidence,
)
from headless.approved_parent_assembly_receipt import parse_assembly_receipt_v1
from headless.approved_parent_quality_evidence import (
    parse_approved_parent_quality_evidence_v1,
)
from headless.approved_parent_schema import parse_approved_parent_descriptor
from headless.artifact_contract import ArtifactRefV1
from headless.build_receipt_binding import BuildReceiptBindingV1
from headless.compositor_build_manifest_v1_contract import (
    COMPOSITOR_BUILD_V1_IMPLEMENTATION_PATHS,
    COMPOSITOR_BUILD_V1_POLICY,
)
from headless.compositor_build_receipt_semantics import (
    parse_compositor_build_receipt_v1,
)
from headless.prebound_compositor_build import compositor_build_manifest_digest
from headless.prebound_clips import parse_prebound_clips
from headless.graphic_render_receipt_semantics import (
    parse_graphic_render_receipt_v1,
)
from headless.render_build import render_build_manifest_digest
from headless.render_build_manifest_v1_contract import (
    RENDER_BUILD_V1_IMPLEMENTATION_PATHS,
    RENDER_BUILD_V1_POLICY,
)
from headless.render_build_receipt_semantics import (
    parse_render_build_receipt_v1,
)
from headless.runtime_capability_binding import RuntimeCapabilityBindingV1
from headless.runtime_capability_manifest import (
    parse_runtime_capability_manifest_v1,
)


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _source_bytes(path: str) -> bytes:
    return f"source:{path}".encode("ascii")


def render_manifest_document(ffmpeg: str, ffprobe: str) -> dict:
    """Return a closed render manifest with synthetic identities."""
    implementation = [
        {
            "path": path,
            "sha256": hashlib.sha256(_source_bytes(path)).hexdigest(),
            "sizeBytes": len(_source_bytes(path)),
        }
        for path in RENDER_BUILD_V1_IMPLEMENTATION_PATHS
    ]
    tools = [
        {
            "label": label,
            "path": f"/opt/sniper/bin/{label}",
            "sha256": digest,
            "sizeBytes": 100 + ordinal,
        }
        for ordinal, (label, digest) in enumerate(
            (
                ("docker", _hash("tool:docker")),
                ("proof-ffmpeg", ffmpeg),
                ("proof-ffprobe", ffprobe),
                ("python", _hash("tool:python")),
            )
        )
    ]
    return {
        "schemaVersion": 1,
        "policy": RENDER_BUILD_V1_POLICY,
        "imageId": "sha256:" + "1" * 64,
        "userId": "501:20",
        "dockerSocket": {
            "path": "/opt/sniper/docker.sock",
            "device": 1,
            "inode": 2,
            "mode": stat.S_IFSOCK,
            "ownerUid": 501,
        },
        "runtimeRoot": "/srv/sniper",
        "pipelineRoot": "/srv/sniper",
        "timeoutSeconds": 30,
        "pythonFlags": ["-I", "-S", "-B", "-X", "pycache_prefix=<attempt>"],
        "implementation": implementation,
        "tools": tools,
    }


def render_receipt_bytes(manifest: dict) -> bytes:
    """Encode the exact newline-terminated retained receipt format."""
    document = {
        "buildDigest": render_build_manifest_digest(manifest),
        "manifest": manifest,
        "schemaVersion": 1,
    }
    return canonical(document) + b"\n"


def compositor_manifest_document() -> dict:
    """Return a closed compositor manifest with synthetic identities."""
    rows = [
        {
            "path": path,
            "sha256": hashlib.sha256(_source_bytes(path)).hexdigest(),
            "sizeBytes": len(_source_bytes(path)),
        }
        for path in COMPOSITOR_BUILD_V1_IMPLEMENTATION_PATHS
    ]
    return {
        "schemaVersion": 1,
        "policy": COMPOSITOR_BUILD_V1_POLICY,
        "implementation": rows,
    }


def compositor_receipt_bytes(manifest: dict) -> bytes:
    """Encode a newline-terminated compositor build receipt V1."""
    document = {
        "buildDigest": compositor_build_manifest_digest(manifest),
        "manifest": manifest,
        "schemaVersion": 1,
    }
    return canonical(document) + b"\n"


def build_receipt_fixture(
    render_mutator: Callable[[dict], None] | None = None,
    compositor_mutator: Callable[[dict], None] | None = None,
    runtime_tool_digests: tuple[str, str] | None = None,
    graphic_mutator: Callable[[dict], None] | None = None,
) -> BuildReceiptBindingV1:
    """Build a cross-bound runtime input around both receipt artifacts."""
    builder = _Builder()
    if runtime_tool_digests is not None:
        builder.ffmpeg, builder.ffprobe = runtime_tool_digests
    compositor_manifest = compositor_manifest_document()
    if compositor_mutator is not None:
        compositor_mutator(compositor_manifest)
    compositor_raw = compositor_receipt_bytes(compositor_manifest)
    builder.build_digest = compositor_build_manifest_digest(compositor_manifest)
    compositor_ref = _ref_for_raw("build/compositor.json", compositor_raw)
    manifest = render_manifest_document(builder.ffmpeg, builder.ffprobe)
    if render_mutator is not None:
        render_mutator(manifest)
    render_raw = render_receipt_bytes(manifest)
    render_digest = render_build_manifest_digest(manifest)
    builder.build_receipt = compositor_ref
    builder.asset = dataclasses.replace(
        builder.asset,
        render_artifact_digest=builder.asset.media.artifact.sha256,
        render_build_digest=render_digest,
    )
    graphic = graphic_receipt_fixture(builder, manifest["imageId"], render_raw)
    if graphic_mutator is not None:
        document = json.loads(graphic.receipt.document_json)
        graphic_mutator(document)
        graphic = dataclasses.replace(
            graphic,
            receipt=parse_graphic_render_receipt_v1(canonical(document)),
        )
    raw = graphic.receipt.document_json
    receipt_ref = _ref_for_raw(builder.asset.receipt.relative_path, raw)
    builder.asset = dataclasses.replace(builder.asset, receipt=receipt_ref)
    builder.clips_json = _clip_bytes(builder.plan, builder.asset)
    builder.clips = parse_prebound_clips(builder.clips_json)
    builder.clips_ref = ArtifactRefV1(
        builder.clips_ref.relative_path,
        hashlib.sha256(builder.clips_json).hexdigest(),
        len(builder.clips_json),
    )
    builder.assembly_raw = builder._assembly()
    return _finalize_binding(builder, compositor_raw, render_raw, graphic)


def _authority_documents(
    builder: _Builder,
    compositor_ref: ArtifactRefV1,
    render_ref: ArtifactRefV1,
    graphic: GraphicReceiptFixtureV1,
) -> tuple:
    descriptor = builder.descriptor_document()
    admission_path = descriptor["provenance"]["admissionInputs"]["path"]
    admission_ref = _ref_for_raw(admission_path, graphic.admission_manifest_json)
    descriptor["provenance"]["admissionInputs"] = {
        "path": admission_ref.relative_path,
        "sha256": admission_ref.sha256,
        "sizeBytes": admission_ref.size_bytes,
    }
    runtime_doc = _runtime_document(builder, descriptor, compositor_ref, render_ref)
    runtime_raw = canonical(runtime_doc)
    runtime_path = descriptor["provenance"]["runtimeCapabilityManifest"]["path"]
    runtime_ref = _ref_for_raw(runtime_path, runtime_raw)
    descriptor["provenance"]["runtimeCapabilityManifest"] = {
        "path": runtime_ref.relative_path,
        "sha256": runtime_ref.sha256,
        "sizeBytes": runtime_ref.size_bytes,
    }
    evidence_raws = _stage_evidence(builder, descriptor, runtime_ref, None)
    evidence_refs = _set_evidence_refs(descriptor, evidence_raws)
    return (
        descriptor,
        admission_ref,
        runtime_raw,
        runtime_ref,
        evidence_raws,
        evidence_refs,
    )


def _finalize_binding(
    builder: _Builder,
    compositor_raw: bytes,
    render_raw: bytes,
    graphic: GraphicReceiptFixtureV1,
) -> BuildReceiptBindingV1:
    compositor_ref = _ref_for_raw("build/compositor.json", compositor_raw)
    render_ref = _ref_for_raw("build/render.json", render_raw)
    authority = _authority_documents(builder, compositor_ref, render_ref, graphic)
    descriptor, admission_ref, runtime_raw, runtime_ref = authority[:4]
    evidence_raws, evidence_refs = authority[4:]
    descriptor_raw = canonical(descriptor)
    refs = (
        ("runtime-capability-manifest-v1", runtime_ref),
        ("compositor-build-receipt-v1", compositor_ref),
        ("render-build-receipt-v1", render_ref),
        ("admission-inputs-v1", admission_ref),
        *evidence_refs,
    )
    commit = _commit(builder, descriptor, descriptor_raw, refs)
    runtime_binding = RuntimeCapabilityBindingV1(
        parse_approved_parent_descriptor(descriptor_raw),
        commit,
        parse_runtime_capability_manifest_v1(runtime_raw),
        parse_assembly_receipt_v1(builder.assembly_raw),
        parse_approved_parent_quality_evidence_v1(*evidence_raws),
    )
    return BuildReceiptBindingV1(
        runtime_binding,
        parse_compositor_build_receipt_v1(compositor_raw),
        parse_render_build_receipt_v1(render_raw),
        builder.plan_json,
        (graphic.receipt,),
        graphic.admission_manifest_json,
        graphic.admission_request_json,
        (graphic.source_seal_json,),
    )


def runtime_fixture_from_build(
    value: BuildReceiptBindingV1,
) -> RuntimeCapabilityFixture:
    """Expose a build fixture's nested runtime input to existing assertions."""
    return RuntimeCapabilityFixture(value.runtime_binding)


def recanonical_receipt(document: dict) -> bytes:
    """Re-encode one edited render receipt exactly."""
    return (
        json.dumps(
            document,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("ascii")
        + b"\n"
    )
