"""Materialize normalized program media before any legacy/direct audio mix."""
from __future__ import annotations

import json
import os
import subprocess

from audio.channel_normalization import (
    ChannelAuthority,
    ChannelNormalizationError,
    verify_channel_receipt,
)
from contracts.schema_validator import SchemaValidationError, validate_document
from edit.picture_lock_common import content_hash
from fingerprints import file_sha256


def materialization_policy() -> dict[str, object]:
    """Version the byte-changing pre-master boundary, not source authority."""
    return {
        "version": 2, "codec": "pcm_f32le", "sampleFormat": "flt",
        "headroom": "preserved-no-limiter",
        "multichannelMatrix": "coefficient-row-sum-at-most-one",
        "masteringApplied": False,
    }


def _materialization_filter(authority: ChannelAuthority) -> str:
    """Keep the old matrix gain without an integer intermediate or limiter."""
    prefix = "aformat=sample_fmts=flt"
    if authority.receipt["stream"]["channels"] > 2:  # type: ignore[index]
        # Integer auto-rematrixing normalized coefficient sums; float defaults
        # do not. Set the same linear matrix bound explicitly, not a peak clamp.
        return (f"{prefix},aresample=48000:out_chlayout=stereo:"
                "rematrix_maxval=1")
    return f"{prefix},{authority.filter_for('stereo')},aresample=48000"


def _run(command: list[str], label: str) -> str:
    result = subprocess.run(
        command, text=True, capture_output=True, check=False)
    if result.returncode:
        detail = (result.stderr or result.stdout)[-1200:].strip()
        raise ChannelNormalizationError(f"{label} failed: {detail}")
    return result.stdout


def _probe_output(authority: ChannelAuthority, path: str) -> dict[str, object]:
    raw = _run([
        authority.request.tools.ffprobe_path, "-v", "error",
        "-show_streams", "-of", "json", path,
    ], "normalized program probe")
    try:
        streams = json.loads(raw)["streams"]
        video = [row for row in streams if row.get("codec_type") == "video"]
        audio = [row for row in streams if row.get("codec_type") == "audio"]
        row = audio[0]
        channels = int(row["channels"])
        sample_rate = int(row["sample_rate"])
    except (KeyError, IndexError, TypeError, ValueError,
            json.JSONDecodeError) as exc:
        raise ChannelNormalizationError(
            "normalized program probe is malformed") from exc
    if len(video) != 1 or len(audio) != 1 \
            or row.get("codec_name") != "pcm_f32le" \
            or row.get("sample_fmt") != "flt" \
            or channels != 2 or sample_rate != 48_000:
        raise ChannelNormalizationError(
            "normalized program media violates the float stereo PCM boundary")
    return {
        "codec": "pcm_f32le", "sampleFormat": "flt", "sampleRate": sample_rate,
        "channels": channels, "channelLayout": "stereo",
    }


def _verify_receipt(authority: ChannelAuthority, value: object) -> dict:
    """Reject historical/unversioned output proofs and rehashed policy drift."""
    try:
        receipt = validate_document(
            "channel-normalization-materialization-v2.schema.json", value)
    except SchemaValidationError as exc:
        raise ChannelNormalizationError(
            "normalized program materialization receipt violates its schema") from exc
    body = {key: item for key, item in receipt.items() if key != "receiptHash"}
    expected = {
        "sourceReceiptHash": authority.receipt["receiptHash"],
        "stereoFilter": authority.filter_for("stereo"),
        "appliedFilter": _materialization_filter(authority),
        "policy": materialization_policy(),
    }
    if receipt["receiptHash"] != content_hash(body) \
            or any(receipt[key] != item for key, item in expected.items()):
        raise ChannelNormalizationError(
            "normalized program materialization authority or policy drifted")
    return receipt


def verify_normalized_program(authority: ChannelAuthority, value: object) -> dict:
    """Read back current float bytes; a historical s32 proof is not reusable."""
    verify_channel_receipt(authority.receipt)
    authority.assert_stable()
    receipt = _verify_receipt(authority, value)
    path = receipt["outputPath"]
    if not os.path.isfile(path) or file_sha256(path) != receipt["outputSha256"]:
        raise ChannelNormalizationError("normalized program output bytes drifted")
    if any(receipt[key] != item for key, item in _probe_output(authority, path).items()):
        raise ChannelNormalizationError("normalized program output format proof drifted")
    return receipt


def materialize_normalized_program(
    authority: ChannelAuthority,
    destination: str,
) -> dict[str, object]:
    """Copy picture and normalize stereo in float; leave mastering downstream."""
    verify_channel_receipt(authority.receipt)
    authority.assert_stable()
    if os.path.lexists(destination):
        raise ChannelNormalizationError(
            "normalized program destination already exists")
    os.makedirs(os.path.dirname(os.path.abspath(destination)), exist_ok=True)
    source = authority.request.source_path
    index = authority.receipt["source"]["selectedStreamIndex"]  # type: ignore[index]
    command = [
        authority.request.tools.ffmpeg_path,
        "-nostdin", "-v", "error", "-n", "-i", source,
        "-map", "0:v:0", "-c:v", "copy", "-map", f"0:{index}",
        "-af", _materialization_filter(authority),
        "-ar", "48000", "-ac", "2", "-c:a", "pcm_f32le",
        "-map_metadata", "0", destination,
    ]
    _run(command, "normalized program materialization")
    authority.assert_stable()
    if not os.path.isfile(destination) or os.path.getsize(destination) <= 0:
        raise ChannelNormalizationError(
            "normalized program materialization wrote no media")
    body = {
        "schemaVersion": 2, "kind": "channel-normalization-materialization",
        "sourceReceiptHash": authority.receipt["receiptHash"],
        "stereoFilter": authority.filter_for("stereo"),
        "appliedFilter": _materialization_filter(authority),
        "policy": materialization_policy(),
        "outputPath": destination,
        "outputSha256": file_sha256(destination),
        **_probe_output(authority, destination),
    }
    return _verify_receipt(authority, {**body, "receiptHash": content_hash(body)})
