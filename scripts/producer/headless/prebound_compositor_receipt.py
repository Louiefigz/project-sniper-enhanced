"""Canonical assembly evidence for a private prebound MP4 candidate."""

from __future__ import annotations

import json
from dataclasses import dataclass

from .composite_media_checks import AlphaOccupancyV1
from .quality_pass_contract import (
    ArtifactRefV1,
    GraphicAssetRefV1,
    MediaFactsV1,
    MediaRefV1,
    ParentRefV1,
)


@dataclass(frozen=True)
class CompositorProofV1:
    """Observed compositor/build/tool/audio/smoothness facts."""

    build_digest: str
    ffmpeg_sha256: str
    ffprobe_sha256: str
    filter_graph_digest: str
    alpha_occupancy: tuple[AlphaOccupancyV1, ...]
    passes: int
    frames_in: int
    frames_out: int
    ydif_duplicate_ratio: float
    ydif_fail_threshold: float
    base_audio_sha256: str
    final_audio_sha256: str


@dataclass(frozen=True)
class AssemblyReceiptInputV1:
    """All authority and observations encoded by one assembly receipt."""

    request_digest: str
    quality_policy_id: str
    parent: ParentRefV1
    parent_assembly_sha256: str
    plan: ArtifactRefV1
    plan_digest: str
    base_projection_digest: str
    base: MediaRefV1
    base_receipt_sha256: str
    timeline_map_sha256: str
    graphic_assets: tuple[GraphicAssetRefV1, ...]
    graphic_asset_set_digest: str
    clips: ArtifactRefV1
    clip_set_digest: str
    proof: CompositorProofV1
    final: MediaRefV1
    cover: ArtifactRefV1
    cover_proof: ArtifactRefV1


def _artifact(value: ArtifactRefV1) -> dict:
    return {
        "path": value.relative_path,
        "sha256": value.sha256,
        "sizeBytes": value.size_bytes,
    }


def _facts(value: MediaFactsV1) -> dict:
    return {
        "width": value.width,
        "height": value.height,
        "durationSeconds": value.duration_seconds,
        "fps": [value.fps_numerator, value.fps_denominator],
        "frameCount": value.frame_count,
        "sizeBytes": value.size_bytes,
        "videoCodec": value.video_codec,
        "pixelFormat": value.pixel_format,
        "profile": value.profile,
        "alphaMode": value.alpha_mode,
        "audioCodec": value.audio_codec,
    }


def _media(value: MediaRefV1) -> dict:
    return {"artifact": _artifact(value.artifact), "facts": _facts(value.facts)}


def _parent(value: ParentRefV1) -> dict:
    return {
        "authorityId": value.authority_id,
        "publicationSeq": value.publication_seq,
        "generationId": value.generation_id,
        "commitDigest": value.commit_digest,
        "planDigest": value.plan_digest,
    }


def _graphic(value: GraphicAssetRefV1) -> dict:
    return {
        "graphicId": value.graphic_id,
        "renderIntentDigest": value.render_intent_digest,
        "renderArtifactDigest": value.render_artifact_digest,
        "renderBuildDigest": value.render_build_digest,
        "media": _media(value.media),
        "renderReceipt": _artifact(value.receipt),
    }


def _compositor(value: CompositorProofV1) -> dict:
    return {
        "buildDigest": value.build_digest,
        "ffmpegSha256": value.ffmpeg_sha256,
        "ffprobeSha256": value.ffprobe_sha256,
        "filterGraphDigest": value.filter_graph_digest,
        "alphaOccupancy": [
            {
                "sampledFrames": row.sampled_frames,
                "meaningfulFrames": row.meaningful_frames,
                "peakMeanAlpha8": row.peak_mean_alpha8,
                "meanAlpha8": row.mean_alpha8,
                "method": "decoded-alpha-signalstats-yavg",
            }
            for row in value.alpha_occupancy
        ],
        "encode": {
            "audioDisposition": "copy",
            "eofAction": "pass",
            "proxyDisposition": "omitted-by-policy",
        },
        "passes": value.passes,
        "framesIn": value.frames_in,
        "framesOut": value.frames_out,
        "smoothness": {
            "method": "inline-preencode-signalstats-ydif",
            "duplicateRatio": value.ydif_duplicate_ratio,
            "failThreshold": value.ydif_fail_threshold,
        },
        "fullDecode": {"passed": True, "method": "ffmpeg-xerror-full"},
        "audio": {
            "method": "ffmpeg-stream-copy-sha256",
            "baseSha256": value.base_audio_sha256,
            "finalSha256": value.final_audio_sha256,
        },
    }


def build_assembly_receipt(value: AssemblyReceiptInputV1) -> bytes:
    """Encode the exact private candidate assembly closure canonically."""
    document = {
        "schemaVersion": 1,
        "status": "complete-private-counterfactual",
        "requestDigest": value.request_digest,
        "qualityPolicyId": value.quality_policy_id,
        "parent": _parent(value.parent),
        "parentAssemblyReceiptSha256": value.parent_assembly_sha256,
        "plan": {
            "artifact": _artifact(value.plan),
            "planDigest": value.plan_digest,
            "baseProjectionDigest": value.base_projection_digest,
        },
        "base": {
            "media": _media(value.base),
            "baseReceiptSha256": value.base_receipt_sha256,
            "timelineMapSha256": value.timeline_map_sha256,
        },
        "graphics": {
            "assetSetDigest": value.graphic_asset_set_digest,
            "assets": [_graphic(item) for item in value.graphic_assets],
            "clipSetDigest": value.clip_set_digest,
            "clipsArtifact": _artifact(value.clips),
        },
        "compositor": _compositor(value.proof),
        "output": {
            "final": _media(value.final),
            "cover": _artifact(value.cover),
            "coverProof": _artifact(value.cover_proof),
            "proxyDisposition": "omitted-by-policy",
        },
    }
    return json.dumps(
        document,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("ascii")
