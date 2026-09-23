"""Synthetic admitted-lane evidence for graphic receipt binding tests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol

from _graphic_render_admission_fixture import (
    AdmissionRecordInputV1,
    admission_records,
    canonical_line,
    render_key,
)
from graphics.composition_transform import set_root_duration
from graphics.template_contract import planned_copy
from headless.graphic_render_receipt_semantics import GraphicRenderReceiptV1
from headless.graphic_render_receipt_writer import (
    GraphicRenderReceiptAuthorityV1,
    build_graphic_render_receipt_v1,
)
from headless.overlay_source_seal import effective_render_intent


class GraphicFixtureBuilder(Protocol):
    """Minimal assembly-builder values consumed by this fixture."""

    plan: dict
    asset: object
    parent: object
    ffmpeg: str
    ffprobe: str


@dataclass(frozen=True)
class GraphicReceiptFixtureV1:
    """Receipt plus its independently retained admission/source records."""

    receipt: GraphicRenderReceiptV1
    admission_manifest_json: bytes
    admission_request_json: bytes
    source_seal_json: bytes


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("ascii")


def _composition_html() -> str:
    variables = [
        {"id": "num", "type": "string", "default": "Part 1"},
        {"id": "line1", "type": "string", "default": "The Setup"},
        {"id": "line2", "type": "string", "default": "Basics"},
        {
            "id": "side",
            "type": "enum",
            "default": "left",
            "options": [{"value": "left"}, {"value": "right"}],
        },
        {"id": "accent", "type": "color", "default": "#054BC9"},
    ]
    catalog = json.dumps(variables, ensure_ascii=True, separators=(",", ":"))
    root = (
        '<div data-composition-id="section-marker" data-width="240" '
        'data-height="120" data-duration="2.5"></div>'
    )
    return f"<html data-composition-variables='{catalog}'><body>{root}</body></html>"


def _snapshot_manifest(html: str, intent: dict) -> list[dict]:
    payloads = {
        "motion/compositions/section-marker.html": set_root_duration(
            html, intent["duration"]
        ).encode(),
        "motion/hyperframes.json": b"{}",
        "motion/index.html": b"fixture-index",
        "motion/package.json": b"{}",
        "request/asset-bindings.json": b"[]",
        "request/render-intent.json": _canonical(intent),
        "request/variables.json": _canonical(intent["spec"]),
    }
    return [
        {
            "path": path,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "sizeBytes": len(raw),
        }
        for path, raw in sorted(payloads.items())
    ]


def _source(builder: GraphicFixtureBuilder, build_digest: str) -> tuple[bytes, str]:
    row = builder.plan["graphicsTrack"][0]
    selection = builder.asset.graphic_id
    snapshot = _hash("graphic-source-snapshot")
    key = render_key(snapshot, build_digest)
    html = _composition_html()
    intent = effective_render_intent(row)
    document = {
        "schemaVersion": 1,
        "buildDigest": build_digest,
        "selectionId": selection,
        "intent": intent,
        "composition": "compositions/section-marker.html",
        "compositionHtml": html,
        "sourceCompositionSha256": hashlib.sha256(html.encode()).hexdigest(),
        "snapshotSha256": snapshot,
        "snapshotManifest": _snapshot_manifest(html, intent),
        "expectedAssetBindings": [],
        "expectedCopy": planned_copy(row, html),
        "expectedDimensions": [240, 120],
        "expectedFormat": "mov",
        "extension": "mov",
        "expectedKey": key,
    }
    return canonical_line(document), key


def _proof(builder: GraphicFixtureBuilder, key: str, image: str) -> dict:
    facts = builder.asset.media.facts
    artifact = builder.asset.media.artifact
    return {
        "schemaVersion": 1,
        "kind": "section-marker",
        "alphaMode": "required",
        "asset": {
            "sha256": artifact.sha256,
            "sizeBytes": artifact.size_bytes,
            "width": facts.width,
            "height": facts.height,
            "durationS": facts.duration_seconds,
            "fps": facts.fps,
            "frameCount": facts.frame_count,
            "codec": facts.video_codec,
            "pixelFormat": facts.pixel_format,
            "profile": facts.profile,
        },
        "copy": {"renderInputKey": key},
        "decode": {"decoded": True, "method": "ffmpeg-full-xerror"},
        "occupancy": {"measured": {"method": "ffmpeg-alpha-sustained-area"}},
        "terminalFrame": {"method": "ffmpeg-final-encoded-alpha"},
        "runtimeAttestation": {
            "imageId": image,
            "snapshotSha256": _hash("graphic-source-snapshot"),
        },
    }


def _lane(builder: GraphicFixtureBuilder, key: str, image: str, admission: str) -> dict:
    artifact = builder.asset.media.artifact
    return {
        "artifactDigest": admission,
        "cacheBinding": {
            "device": 1,
            "inode": 2,
            "ownerReceiptSha256": _hash("cache-owner"),
        },
        "launcherSha256": _hash("render-launcher"),
        "outputBinding": {
            "device": 3,
            "inode": 4,
            "sha256": artifact.sha256,
            "sizeBytes": artifact.size_bytes,
        },
        "renderBuildReceipt": builder.asset.render_build_digest,
        "rendererMode": "sealed-oci-v2",
        "selectionId": builder.asset.graphic_id,
        "result": {
            "cached": False,
            "fmt": "mov",
            "key": key,
            "kind": "section-marker",
            "path": f"/attempt/cache/{key}.mov",
            "proof": _proof(builder, key, image),
        },
    }


def graphic_receipt_fixture(
    builder: GraphicFixtureBuilder, image_id: str, render_build_json: bytes
) -> GraphicReceiptFixtureV1:
    """Build receipt bytes through the real admitted-lane normalizer."""
    authority, plan_row, lane, admission, request_raw, source = graphic_writer_inputs(
        builder, image_id, render_build_json
    )
    receipt = build_graphic_render_receipt_v1(authority, plan_row, lane)
    return GraphicReceiptFixtureV1(receipt, admission, request_raw, source)


def graphic_writer_inputs(
    builder: GraphicFixtureBuilder,
    image_id: str,
    render_build_json: bytes | None = None,
) -> tuple[GraphicRenderReceiptAuthorityV1, dict, dict, bytes, bytes, bytes]:
    """Expose exact writer inputs for adversarial normalization tests."""
    source, key = _source(builder, builder.asset.render_build_digest)
    build_raw = render_build_json or canonical_line(
        {"buildDigest": builder.asset.render_build_digest, "schemaVersion": 1}
    )
    admission, request_raw, admission_digest = admission_records(
        AdmissionRecordInputV1(
            source,
            builder.asset.graphic_id,
            builder.asset.render_build_digest,
            builder.plan["graphicsTrack"][0],
            build_raw,
        )
    )
    authority = GraphicRenderReceiptAuthorityV1(
        0,
        builder.asset.graphic_id,
        builder.asset.graphic_id,
        admission_digest,
        "c" * 64,
        builder.parent.quality_policy_id,
        builder.asset.media,
        builder.asset.render_build_digest,
        key,
        _hash("graphic-source-snapshot"),
        image_id,
        builder.ffmpeg,
        builder.ffprobe,
    )
    return (
        authority,
        builder.plan["graphicsTrack"][0],
        _lane(builder, key, image_id, admission_digest),
        admission,
        request_raw,
        source,
    )
