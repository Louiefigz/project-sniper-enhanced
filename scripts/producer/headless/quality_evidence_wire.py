"""Shared exact wire parsing for full-decode and terminal Audit-B evidence."""

from __future__ import annotations

import math

from . import quality_receipt_json as wire
from .artifact_contract import ArtifactRefV1
from .quality_evidence_types import (
    DecodeAudioV1,
    DecodeExecutionV1,
    DecodeStreamsV1,
    DecodeToolsV1,
    DecodeVideoV1,
    FullDecodeProofV1,
)

QualityEvidenceSchemaError = wire.QualityReceiptSchemaError

_FULL_KEYS = frozenset(
    "approvedPlanDigest assemblyReceipt audio execution final method plan qualityPolicyId "
    "runtimeCapabilityManifest schemaVersion streams tools verdict video".split()
)
_STREAM_KEYS = frozenset(
    "decodedAudio decodedVideo expectedAudio expectedVideo".split()
)
_VIDEO_KEYS = frozenset(
    "decodedFrames decodedPackets expectedFrames expectedPackets".split()
)
_AUDIO_KEYS = frozenset(
    "channels decodedPackets decodedSamplesPerChannel expectedPackets "
    "expectedSamplesPerChannel sampleRateHz".split()
)
_TOOL_KEYS = frozenset("ffmpegSha256 ffprobeSha256".split())
_EXECUTION_KEYS = frozenset("audioSink errorPolicy exitCode videoSink".split())
_COUNT_MAX = (1 << 63) - 1


def _envelope(document: dict, keys: frozenset[str], label: str) -> None:
    row = wire.exact(document, keys, label)
    valid = (
        type(row.get("schemaVersion")) is int
        and row["schemaVersion"] == 1
        and row.get("verdict") == "pass"
    )
    if not valid:
        raise QualityEvidenceSchemaError(f"{label} envelope is invalid")


def integer(value: object, label: str, minimum: int = 0) -> int:
    """Require an exact bounded JSON integer, never bool."""
    valid = type(value) is int and minimum <= value <= _COUNT_MAX
    if not valid:
        raise QualityEvidenceSchemaError(f"{label} is invalid")
    return value


def number(value: object, label: str) -> int | float:
    """Require a finite JSON number, never bool."""
    valid = type(value) in {int, float} and math.isfinite(value)
    if not valid:
        raise QualityEvidenceSchemaError(f"{label} is invalid")
    return value


def rgb(value: object, label: str) -> tuple[int, int, int]:
    """Require one exact three-byte RGB array."""
    valid = (
        type(value) is list
        and len(value) == 3
        and all(type(item) is int and 0 <= item <= 255 for item in value)
    )
    if not valid:
        raise QualityEvidenceSchemaError(f"{label} is invalid")
    return value[0], value[1], value[2]


def distinct_artifacts(refs: tuple[ArtifactRefV1, ...], label: str) -> None:
    """Reject path aliases and same-byte reuse across semantic roles."""
    paths = tuple(ref.relative_path for ref in refs)
    digests = tuple(ref.sha256 for ref in refs)
    if len(set(paths)) != len(paths) or len(set(digests)) != len(digests):
        raise QualityEvidenceSchemaError(f"{label} artifact roles alias")


def _decode_streams(value: object) -> DecodeStreamsV1:
    row = wire.exact(value, _STREAM_KEYS, "decode stream coverage")
    counts = tuple(integer(row[key], f"stream {key}", 0) for key in _STREAM_KEYS)
    expected = (1, 1, 1, 1)
    if counts != expected:
        raise QualityEvidenceSchemaError("decode stream coverage is incomplete")
    return DecodeStreamsV1(
        row["expectedVideo"],
        row["decodedVideo"],
        row["expectedAudio"],
        row["decodedAudio"],
    )


def _decode_video(value: object) -> DecodeVideoV1:
    row = wire.exact(value, _VIDEO_KEYS, "video decode coverage")
    counts = tuple(integer(row[key], f"video {key}", 1) for key in _VIDEO_KEYS)
    expected_frames, expected_packets, decoded_frames, decoded_packets = counts
    valid = expected_frames == decoded_frames == expected_packets == decoded_packets
    if not valid:
        raise QualityEvidenceSchemaError("video decode coverage is incomplete")
    return DecodeVideoV1(
        row["expectedFrames"],
        row["decodedFrames"],
        row["expectedPackets"],
        row["decodedPackets"],
    )


def _decode_audio(value: object) -> DecodeAudioV1:
    row = wire.exact(value, _AUDIO_KEYS, "audio decode coverage")
    channels = integer(row["channels"], "audio channels", 1)
    rate = integer(row["sampleRateHz"], "audio sample rate", 1)
    samples = integer(row["expectedSamplesPerChannel"], "audio samples", 1)
    decoded = integer(row["decodedSamplesPerChannel"], "decoded audio samples", 1)
    packets = integer(row["expectedPackets"], "audio packets", 1)
    decoded_packets = integer(row["decodedPackets"], "decoded audio packets", 1)
    valid = channels <= 32 and 8_000 <= rate <= 384_000
    valid = valid and samples == decoded and packets == decoded_packets <= samples
    if not valid:
        raise QualityEvidenceSchemaError("audio decode coverage is incomplete")
    return DecodeAudioV1(channels, rate, samples, decoded, packets, decoded_packets)


def _decode_tools(value: object) -> DecodeToolsV1:
    row = wire.exact(value, _TOOL_KEYS, "decode tools")
    return DecodeToolsV1(
        wire.digest(row["ffmpegSha256"], "ffmpeg digest"),
        wire.digest(row["ffprobeSha256"], "ffprobe digest"),
    )


def _decode_execution(value: object) -> DecodeExecutionV1:
    row = wire.exact(value, _EXECUTION_KEYS, "decode execution")
    actual = (
        row["errorPolicy"],
        type(row["exitCode"]),
        row["exitCode"],
        row["videoSink"],
        row["audioSink"],
    )
    if actual != ("xerror", int, 0, "null", "null"):
        raise QualityEvidenceSchemaError("decode execution did not pass")
    return DecodeExecutionV1("xerror", 0, "null", "null")


def parse_full_decode_proof_v1(raw: object) -> FullDecodeProofV1:
    """Parse exact fail-on-error video/audio coverage bytes."""
    document = wire.canonical_document(raw, "full-decode proof")
    _envelope(document, _FULL_KEYS, "full-decode proof")
    if document["method"] != "ffmpeg-xerror-full-av-v1":
        raise QualityEvidenceSchemaError("full-decode method is invalid")
    refs = tuple(
        wire.artifact(document[key])
        for key in ("plan", "final", "assemblyReceipt", "runtimeCapabilityManifest")
    )
    distinct_artifacts(refs, "full-decode")
    return FullDecodeProofV1(
        refs[0],
        wire.digest(document["approvedPlanDigest"], "decode plan digest"),
        refs[1],
        refs[2],
        wire.digest(document["qualityPolicyId"], "decode quality policy ID"),
        refs[3],
        _decode_tools(document["tools"]),
        _decode_execution(document["execution"]),
        _decode_streams(document["streams"]),
        _decode_video(document["video"]),
        _decode_audio(document["audio"]),
        raw,
    )

