"""Self-consistent child-generation fixture for assembly semantic tests."""

from __future__ import annotations
import copy
import hashlib
import json
from dataclasses import dataclass

from _approved_parent_schema_fixture import _descriptor
from _assembly_receipt_manifest_fixture import build_commit
from test_quality_pass_contract import _approved, _plan
from fingerprints import base_plan_digest, plan_content_hash
from graphics.composite_core import build_graph
from headless.approved_parent_assembly_receipt import parse_assembly_receipt_v1
from headless.artifact_contract import ArtifactRefV1, MediaFactsV1, MediaRefV1
from headless.composite_media_checks import AlphaOccupancyV1
from headless.prebound_clips import parse_prebound_clips, prebound_clip_set_digest
from headless.prebound_compositor_receipt import (
    AssemblyReceiptInputV1,
    CompositorProofV1,
    build_assembly_receipt,
)
from headless.quality_pass_contract import (
    GraphicAssetRefV1,
    graphic_render_intent_digest,
)
from headless.quality_pass_outputs import graphic_asset_set_digest
from headless.repair_intent import approved_plan_digest
from headless.approved_parent_schema import parse_approved_parent_descriptor

GENERATION = "44444444-4444-4444-8444-444444444444"
ATTEMPT = "55555555-5555-4555-8555-555555555555"
UNIT = "66666666-6666-4666-8666-666666666666"
REQUEST = "c" * 64


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("ascii")


def decoded(raw: bytes) -> dict:
    return json.loads(raw)


def changed(raw: bytes, path: tuple[str, ...], value: object) -> bytes:
    document = decoded(raw)
    target = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return canonical(document)


def _artifact(path: str, marker: str, size: int = 100) -> ArtifactRefV1:
    return ArtifactRefV1(path, marker * 64, size)


def _artifact_dict(value: ArtifactRefV1) -> dict:
    return {
        "path": value.relative_path,
        "sha256": value.sha256,
        "sizeBytes": value.size_bytes,
    }


def _media_dict(value: MediaRefV1) -> dict:
    facts = value.facts
    return {
        "artifact": _artifact_dict(value.artifact),
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


def _graphic_dict(value: GraphicAssetRefV1) -> dict:
    return {
        "graphicId": value.graphic_id,
        "renderIntentDigest": value.render_intent_digest,
        "media": _media_dict(value.media),
        "receipt": _artifact_dict(value.receipt),
        "renderArtifactDigest": value.render_artifact_digest,
        "renderBuildDigest": value.render_build_digest,
    }


def _graphic_media() -> MediaRefV1:
    artifact = _artifact("graphics/g-00000001.mov", "1")
    facts = MediaFactsV1(
        240,
        120,
        2.5,
        30,
        1,
        75,
        artifact.size_bytes,
        "prores",
        "yuva444p12le",
        "4444",
        "straight",
        None,
    )
    return MediaRefV1(artifact, facts)


def _current_plan() -> dict:
    value = copy.deepcopy(_plan())
    value["graphicsTrack"][0]["spec"]["accent"] = "#FFD400"
    return value


def _clip_bytes(plan: dict, asset: GraphicAssetRefV1) -> bytes:
    row = plan["graphicsTrack"][0]
    return canonical(
        [
            {
                "graphicId": row["id"],
                "outStart": row["outStart"],
                "outEnd": row["outEnd"],
                "anchor": row["anchor"],
                "x": row["placement"]["x"],
                "y": row["placement"]["y"],
                "mediaSha256": asset.media.artifact.sha256,
                "renderReceiptSha256": asset.receipt.sha256,
            }
        ]
    )


def _filter_digest(clips: tuple) -> str:
    rows = [
        {
            "path": "verified-overlay-0",
            "outStart": clips[0].out_start,
            "outEnd": clips[0].out_end,
            "anchor": clips[0].anchor,
            "x": clips[0].x,
            "y": clips[0].y,
        }
    ]
    graph, _label = build_graph(rows, True)
    return hashlib.sha256(
        b"sniper-prebound-filter-graph-v1\0" + graph.encode()
    ).hexdigest()


@dataclass(frozen=True)
class AssemblyFixture:
    descriptor: object
    commit: object
    receipt: object


class _Builder:
    def __init__(self) -> None:
        self.parent = _approved(_plan())
        self.plan = _current_plan()
        self.plan_json = canonical(self.plan)
        self.plan_ref = ArtifactRefV1(
            "candidate-plan.json",
            hashlib.sha256(self.plan_json).hexdigest(),
            len(self.plan_json),
        )
        media = _graphic_media()
        self.asset = GraphicAssetRefV1(
            "g-00000001",
            graphic_render_intent_digest(self.plan["graphicsTrack"][0]),
            media,
            _artifact("graphics/g-00000001.receipt.json", "f"),
            "a" * 64,
            "b" * 64,
        )
        self.clips_json = _clip_bytes(self.plan, self.asset)
        self.clips = parse_prebound_clips(self.clips_json)
        self.clips_ref = ArtifactRefV1(
            "candidate-clips.json",
            hashlib.sha256(self.clips_json).hexdigest(),
            len(self.clips_json),
        )
        self.final = MediaRefV1(_artifact("final.mp4", "0"), self.parent.base.facts)
        self.cover = _artifact("cover.png", "a")
        self.cover_proof = _artifact("cover-proof.json", "b")
        self.build_receipt = _artifact("build/compositor.json", "d")
        self.alpha = (AlphaOccupancyV1(10, 10, 255.0, 200.0),)
        self.build_digest = "5" * 64
        self.ffmpeg = "2" * 64
        self.ffprobe = "3" * 64
        self.audio = "7" * 64
        self.assembly_raw = self._assembly()

    def _assembly(self) -> bytes:
        proof = CompositorProofV1(
            self.build_digest,
            self.ffmpeg,
            self.ffprobe,
            _filter_digest(self.clips),
            self.alpha,
            1,
            self.parent.base.facts.frame_count,
            self.final.facts.frame_count,
            0.01,
            0.08,
            self.audio,
            self.audio,
        )
        value = AssemblyReceiptInputV1(
            REQUEST,
            self.parent.quality_policy_id,
            self.parent.ref,
            self.parent.assembly_receipt.sha256,
            self.plan_ref,
            approved_plan_digest(self.plan),
            base_plan_digest(self.plan),
            self.parent.base,
            self.parent.base_receipt.sha256,
            self.parent.timeline_map.sha256,
            (self.asset,),
            graphic_asset_set_digest((self.asset,)),
            self.clips_ref,
            prebound_clip_set_digest(self.clips),
            proof,
            self.final,
            self.cover,
            self.cover_proof,
        )
        return build_assembly_receipt(value)

    def descriptor_document(self) -> dict:
        document = _descriptor()
        document["identity"] = {
            "authorityId": self.parent.ref.authority_id,
            "generationId": GENERATION,
            "attemptId": ATTEMPT,
            "unitId": UNIT,
            "requestDigest": REQUEST,
        }
        document["policies"] = {
            "executionPolicyId": "2" * 64,
            "repairPolicyId": self.parent.repair_policy_id,
            "qualityPolicyId": self.parent.quality_policy_id,
            "fallbackPolicyId": "5" * 64,
        }
        document["plan"] = {
            "artifact": _artifact_dict(self.plan_ref),
            "approvedPlanDigest": approved_plan_digest(self.plan),
            "contentHash": plan_content_hash(self.plan),
            "baseProjectionDigest": base_plan_digest(self.plan),
        }
        document["base"] = {
            "media": _media_dict(self.parent.base),
            "planArtifact": _artifact_dict(self.parent.base_plan),
            "receipt": _artifact_dict(self.parent.base_receipt),
            "timelineMap": _artifact_dict(self.parent.timeline_map),
        }
        document["graphics"] = {
            "preboundClips": _artifact_dict(self.clips_ref),
            "assets": [_graphic_dict(self.asset)],
        }
        assembly = ArtifactRefV1(
            "assembly-receipt.json",
            hashlib.sha256(self.assembly_raw).hexdigest(),
            len(self.assembly_raw),
        )
        document["output"] = {
            "final": _media_dict(self.final),
            "assemblyReceipt": _artifact_dict(assembly),
            "cover": _artifact_dict(self.cover),
            "coverProof": _artifact_dict(self.cover_proof),
            "proxyDisposition": "omitted-by-policy",
        }
        return document


def assembly_fixture() -> AssemblyFixture:
    builder = _Builder()
    document = builder.descriptor_document()
    descriptor_raw = canonical(document)
    return AssemblyFixture(
        parse_approved_parent_descriptor(descriptor_raw),
        build_commit(builder, document, descriptor_raw),
        parse_assembly_receipt_v1(builder.assembly_raw),
    )
