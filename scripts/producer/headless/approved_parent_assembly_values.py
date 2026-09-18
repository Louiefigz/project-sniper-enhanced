"""Nested values for the exact private R0 assembly receipt parser."""

from __future__ import annotations

import math
from dataclasses import dataclass

from . import quality_receipt_json as wire
from .artifact_contract import ArtifactRefV1, MediaFactsV1, MediaRefV1
from .composite_media_checks import AlphaOccupancyV1
from .quality_pass_contract import (
    GraphicAssetRefV1,
    validate_graphic_asset,
    validate_media_ref,
)
from .repair_intent import ParentRefV1, validate_parent_ref

AssemblyReceiptSchemaError = wire.QualityReceiptSchemaError
_PARENT_KEYS = frozenset(
    "authorityId commitDigest generationId planDigest publicationSeq".split()
)
_GRAPHICS_KEYS = frozenset("assetSetDigest assets clipSetDigest clipsArtifact".split())
_GRAPHIC_KEYS = frozenset(
    "graphicId media renderArtifactDigest renderBuildDigest renderIntentDigest "
    "renderReceipt".split()
)
_MEDIA_KEYS = frozenset("artifact facts".split())
_FACT_KEYS = frozenset(
    "alphaMode audioCodec durationSeconds fps frameCount height pixelFormat "
    "profile sizeBytes videoCodec width".split()
)
_COMPOSITOR_KEYS = frozenset(
    "alphaOccupancy audio buildDigest encode ffmpegSha256 ffprobeSha256 "
    "filterGraphDigest framesIn framesOut fullDecode passes smoothness".split()
)
_ALPHA_KEYS = frozenset(
    "meanAlpha8 meaningfulFrames method peakMeanAlpha8 sampledFrames".split()
)


@dataclass(frozen=True)
class AssemblyCompositorProofV1:
    build_digest: str
    ffmpeg_sha256: str
    ffprobe_sha256: str
    filter_graph_digest: str
    alpha_occupancy: tuple[AlphaOccupancyV1, ...]
    passes: int
    frames_in: int
    frames_out: int
    duplicate_ratio: float
    fail_threshold: float
    base_audio_sha256: str
    final_audio_sha256: str


@dataclass(frozen=True)
class AssemblyReceiptV1:
    request_digest: str
    quality_policy_id: str
    parent: ParentRefV1
    parent_assembly_receipt_sha256: str
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


def parse_parent(value: object) -> ParentRefV1:
    row = wire.exact(value, _PARENT_KEYS, "assembly parent")
    parsed = ParentRefV1(
        wire.authority(row["authorityId"]),
        row["publicationSeq"],
        wire.canonical_uuid(row["generationId"], "parent generation ID"),
        wire.digest(row["commitDigest"], "parent commit digest"),
        wire.digest(row["planDigest"], "parent plan digest"),
    )
    try:
        validate_parent_ref(parsed)
    except RuntimeError as exc:
        raise AssemblyReceiptSchemaError("assembly parent is invalid") from exc
    return parsed


def _facts(value: object) -> MediaFactsV1:
    row = wire.exact(value, _FACT_KEYS, "assembly media facts")
    fps = row["fps"]
    valid = (
        type(fps) is list
        and len(fps) == 2
        and all(type(item) is int and item > 0 for item in fps)
        and type(row["durationSeconds"]) is float
    )
    if not valid:
        raise AssemblyReceiptSchemaError("assembly media timing is invalid")
    return MediaFactsV1(
        row["width"],
        row["height"],
        row["durationSeconds"],
        fps[0],
        fps[1],
        row["frameCount"],
        row["sizeBytes"],
        row["videoCodec"],
        row["pixelFormat"],
        row["profile"],
        row["alphaMode"],
        row["audioCodec"],
    )


def parse_media(value: object) -> MediaRefV1:
    row = wire.exact(value, _MEDIA_KEYS, "assembly media")
    parsed = MediaRefV1(wire.artifact(row["artifact"]), _facts(row["facts"]))
    try:
        validate_media_ref(parsed)
    except RuntimeError as exc:
        raise AssemblyReceiptSchemaError("assembly media is invalid") from exc
    return parsed


def _graphic(value: object) -> GraphicAssetRefV1:
    row = wire.exact(value, _GRAPHIC_KEYS, "assembly graphic")
    parsed = GraphicAssetRefV1(
        row["graphicId"],
        wire.digest(row["renderIntentDigest"], "graphic render intent"),
        parse_media(row["media"]),
        wire.artifact(row["renderReceipt"]),
        wire.digest(row["renderArtifactDigest"], "graphic render artifact"),
        wire.digest(row["renderBuildDigest"], "graphic render build"),
    )
    try:
        validate_graphic_asset(parsed)
    except RuntimeError as exc:
        raise AssemblyReceiptSchemaError("assembly graphic is invalid") from exc
    return parsed


def parse_graphics(value: object) -> tuple[tuple[GraphicAssetRefV1, ...], dict]:
    row = wire.exact(value, _GRAPHICS_KEYS, "assembly graphics")
    if type(row["assets"]) is not list or not row["assets"]:
        raise AssemblyReceiptSchemaError("assembly graphic set is empty")
    assets = tuple(_graphic(item) for item in row["assets"])
    identities = tuple(item.graphic_id for item in assets)
    if len(identities) != len(set(identities)):
        raise AssemblyReceiptSchemaError("assembly graphic identities alias")
    return assets, row


def _alpha(value: object) -> AlphaOccupancyV1:
    row = wire.exact(value, _ALPHA_KEYS, "alpha occupancy")
    sampled, meaningful = row["sampledFrames"], row["meaningfulFrames"]
    peak, mean = row["peakMeanAlpha8"], row["meanAlpha8"]
    required = (
        max(2, math.ceil(sampled * 0.2)) if type(sampled) is int and sampled > 1 else 1
    )
    valid = (
        row["method"] == "decoded-alpha-signalstats-yavg"
        and type(sampled) is int
        and type(meaningful) is int
        and sampled > 0
        and required <= meaningful <= sampled
        and type(peak) is float
        and type(mean) is float
        and math.isfinite(peak)
        and math.isfinite(mean)
        and 0 <= mean <= peak <= 255
    )
    if not valid:
        raise AssemblyReceiptSchemaError("alpha occupancy is invalid")
    return AlphaOccupancyV1(sampled, meaningful, peak, mean)


def _method_constants(row: dict) -> None:
    encode = wire.exact(
        row["encode"],
        frozenset("audioDisposition eofAction proxyDisposition".split()),
        "assembly encode disposition",
    )
    decode = wire.exact(
        row["fullDecode"],
        frozenset("method passed".split()),
        "assembly full decode",
    )
    actual = (
        encode["audioDisposition"],
        encode["eofAction"],
        encode["proxyDisposition"],
        decode["method"],
        type(decode["passed"]),
        decode["passed"],
    )
    expected = ("copy", "pass", "omitted-by-policy", "ffmpeg-xerror-full", bool, True)
    if actual != expected:
        raise AssemblyReceiptSchemaError("assembly compositor methods are invalid")


def parse_compositor(value: object) -> AssemblyCompositorProofV1:
    row = wire.exact(value, _COMPOSITOR_KEYS, "assembly compositor")
    if type(row["alphaOccupancy"]) is not list or not row["alphaOccupancy"]:
        raise AssemblyReceiptSchemaError("alpha occupancy set is invalid")
    _method_constants(row)
    smooth = wire.exact(
        row["smoothness"],
        frozenset("duplicateRatio failThreshold method".split()),
        "assembly smoothness",
    )
    audio = wire.exact(
        row["audio"],
        frozenset("baseSha256 finalSha256 method".split()),
        "assembly audio",
    )
    ratio, threshold = smooth["duplicateRatio"], smooth["failThreshold"]
    integers = (row["passes"], row["framesIn"], row["framesOut"])
    valid = (
        smooth["method"] == "inline-preencode-signalstats-ydif"
        and audio["method"] == "ffmpeg-stream-copy-sha256"
        and all(type(item) is int and item > 0 for item in integers)
        and type(ratio) is float
        and type(threshold) is float
        and math.isfinite(ratio)
        and math.isfinite(threshold)
        and 0 <= ratio < threshold <= 1
    )
    base_audio = wire.digest(audio["baseSha256"], "base audio digest")
    final_audio = wire.digest(audio["finalSha256"], "final audio digest")
    if not valid or base_audio != final_audio:
        raise AssemblyReceiptSchemaError("assembly observations are invalid")
    return AssemblyCompositorProofV1(
        wire.digest(row["buildDigest"], "compositor build digest"),
        wire.digest(row["ffmpegSha256"], "ffmpeg digest"),
        wire.digest(row["ffprobeSha256"], "ffprobe digest"),
        wire.digest(row["filterGraphDigest"], "filter graph digest"),
        tuple(_alpha(item) for item in row["alphaOccupancy"]),
        *integers,
        ratio,
        threshold,
        base_audio,
        final_audio,
    )
