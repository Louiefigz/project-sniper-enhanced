"""Canonical wire helpers for the normalized graphic render receipt."""

from __future__ import annotations

import json
import os
import re

from .artifact_contract import MediaRefV1

_DIGEST = re.compile(r"[0-9a-f]{64}")
_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")


def is_r0_media(value: MediaRefV1) -> bool:
    """Return whether media uses the exact qualified R0 overlay shape."""
    facts = value.facts
    shape = (
        facts.video_codec,
        facts.pixel_format,
        facts.profile,
        facts.alpha_mode,
        facts.audio_codec,
        facts.fps_numerator,
        facts.fps_denominator,
    )
    return shape == ("prores", "yuva444p12le", "4444", "straight", None, 30, 1)


def validate_lane_leaves(lane: dict, result: dict, output: dict, cache: dict) -> None:
    """Reject non-JSON or malformed critical leaves before equality checks."""
    proof = result["proof"]
    runtime = proof.get("runtimeAttestation") if type(proof) is dict else None
    runtime_map = runtime if type(runtime) is dict else {}
    digests = (
        lane["artifactDigest"],
        lane["renderBuildReceipt"],
        lane["launcherSha256"],
        result["key"],
        output["sha256"],
        cache["ownerReceiptSha256"],
        runtime_map.get("snapshotSha256"),
    )
    integers = tuple(
        row[key] for row in (output, cache) for key in ("device", "inode")
    ) + (output["sizeBytes"],)
    strings = (
        lane["selectionId"],
        lane["rendererMode"],
        result["fmt"],
        result["kind"],
        result["path"],
    )
    valid = all(type(item) is str and _DIGEST.fullmatch(item) for item in digests)
    valid = valid and all(type(item) is int and item > 0 for item in integers)
    valid = valid and all(type(item) is str and item for item in strings)
    image = runtime_map.get("imageId")
    valid = valid and type(image) is str and bool(_IMAGE_ID.fullmatch(image))
    valid = valid and type(result["cached"]) is bool
    valid = valid and os.path.isabs(result["path"])
    if not valid:
        raise ValueError("admitted render lane values are invalid")


def proof_methods(proof: dict) -> dict:
    """Return qualified R0 proof methods or raise a normalized value error."""
    decode = proof.get("decode")
    occupancy = proof.get("occupancy")
    terminal = proof.get("terminalFrame")
    if any(type(item) is not dict for item in (decode, occupancy, terminal)):
        raise ValueError("render proof method objects are invalid")
    measured = occupancy.get("measured")
    if type(measured) is not dict:
        raise ValueError("render occupancy measurement is invalid")
    methods = {
        "alphaMode": proof.get("alphaMode"),
        "decodeMethod": decode.get("method"),
        "occupancyMethod": measured.get("method"),
        "terminalAlphaMethod": terminal.get("method"),
    }
    expected = {
        "alphaMode": "required",
        "decodeMethod": "ffmpeg-full-xerror",
        "occupancyMethod": "ffmpeg-alpha-sustained-area",
        "terminalAlphaMethod": "ffmpeg-final-encoded-alpha",
    }
    exact_strings = all(type(value) is str for value in methods.values())
    if not exact_strings or methods != expected or decode.get("decoded") is not True:
        raise ValueError("render proof methods are outside qualified R0")
    return methods


def media_document(media: MediaRefV1) -> dict:
    """Serialize one already-validated media reference exactly."""
    facts = media.facts
    return {
        "artifact": {
            "path": media.artifact.relative_path,
            "sha256": media.artifact.sha256,
            "sizeBytes": media.artifact.size_bytes,
        },
        "facts": {
            "alphaMode": facts.alpha_mode,
            "audioCodec": facts.audio_codec,
            "durationSeconds": facts.duration_seconds,
            "fpsDenominator": facts.fps_denominator,
            "fpsNumerator": facts.fps_numerator,
            "frameCount": facts.frame_count,
            "height": facts.height,
            "pixelFormat": facts.pixel_format,
            "profile": facts.profile,
            "sizeBytes": facts.size_bytes,
            "videoCodec": facts.video_codec,
            "width": facts.width,
        },
    }


def encode_receipt(value: object) -> bytes:
    """Encode one receipt document as exact canonical ASCII JSON."""
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("ascii")
