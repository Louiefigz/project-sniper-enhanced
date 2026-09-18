#!/usr/bin/env python3
"""Validate pinned exact/codec-floor repeat equivalence and calibration."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from baseline_validation_common import (
    SHA256,
    document_sha256,
    valid_direct_tool,
)
from current_render_graph_contract import canonical_bytes, object_hash
from current_render_calibration_source import validate_source_record_shape
from current_render_oracle import CODEC_FLOOR_POLICY, codec_floor_passes

PIXEL_IDENTICAL_CLASS = "pixel-identical"
CODEC_FLOOR_CLASS = CODEC_FLOOR_POLICY["pictureClaim"]
CALIBRATION_PATH = (
    "docs/producer/command-driven-editing/contracts/"
    "current-render-codec-floor-calibration-v1.json"
)


def _oracle_media_matches(value: object, expected_sha: object) -> bool:
    keys = {
        "path", "fileSha256", "sizeBytes", "pictureFrameMd5Sha256",
        "pcmSha256", "pcmBytes", "streamFacts",
    }
    if not isinstance(value, dict) or set(value) != keys:
        return False
    facts = value.get("streamFacts")
    video = facts.get("video") if isinstance(facts, dict) else None
    hashes = (value.get("pictureFrameMd5Sha256"), value.get("pcmSha256"))
    return (
        value.get("fileSha256") == expected_sha
        and isinstance(video, dict)
        and type(video.get("decodedFrames")) is int
        and all(isinstance(item, str) and SHA256.fullmatch(item)
                for item in hashes)
        and type(value.get("pcmBytes")) is int
        and value["pcmBytes"] > 0
    )


def _oracle_toolchain_matches(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"ffmpeg", "ffprobe", "oracle"}
        and all(valid_direct_tool(value[name]) for name in value)
    )


def _tool_matches(left: object, right: object) -> bool:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    return (
        left.get("path") == right.get("path")
        and left.get("sha256") == right.get("sha256")
    )


def _picture_classification(
    picture: object,
    left: dict,
    right: dict,
    expected_frames: int,
) -> str | None:
    if not isinstance(picture, dict) or picture.get(
            "codecFloorEquivalent") is not True:
        return None
    exact = picture.get("pixelIdentical")
    hashes_equal = (
        left["pictureFrameMd5Sha256"] == right["pictureFrameMd5Sha256"])
    if exact is True:
        valid = (
            picture.get("method") == "exact-framemd5"
            and picture.get("metrics") is None
            and hashes_equal
        )
        return PIXEL_IDENTICAL_CLASS if valid else None
    metrics = picture.get("metrics")
    valid = (
        exact is False
        and picture.get("method") == "full-frame-ssim"
        and not hashes_equal
        and isinstance(metrics, dict)
        and metrics.get("comparedFrames") == expected_frames
        and codec_floor_passes(metrics)
    )
    return CODEC_FLOOR_CLASS if valid else None


def _receipt_classification(
    fixture: dict[str, Any],
    runs: list[dict[str, Any]],
    receipt: dict,
) -> str | None:
    keys = {
        "schemaVersion", "kind", "policy", "policyHash", "toolchain",
        "incremental", "forcedFull", "pictureComparison",
        "decodedAudioMatch", "streamFactsMatch", "byteIdentical",
        "passed", "receiptHash",
    }
    if set(receipt) != keys:
        return None
    left, right = receipt.get("incremental"), receipt.get("forcedFull")
    if (
        not _oracle_media_matches(left, runs[0]["outputs"][0].get("sha256"))
        or not _oracle_media_matches(right, runs[1]["outputs"][0].get("sha256"))
    ):
        return None
    unhashed = {key: value for key, value in receipt.items()
                if key != "receiptHash"}
    media_tools = runs[0]["outputs"][0]["media"].get("tools") or {}
    receipt_tools = receipt.get("toolchain") or {}
    common = (
        receipt.get("schemaVersion") == 1
        and receipt.get("kind") == "current-render-forced-full-oracle"
        and receipt.get("policy") == CODEC_FLOOR_POLICY
        and receipt.get("policyHash") == object_hash(CODEC_FLOOR_POLICY)
        and receipt.get("receiptHash") == object_hash(unhashed)
        and _oracle_toolchain_matches(receipt.get("toolchain"))
        and all(_tool_matches(receipt_tools.get(name), media_tools.get(name))
                for name in ("ffmpeg", "ffprobe"))
        and left["streamFacts"] == right["streamFacts"]
        and left["pcmSha256"] == right["pcmSha256"]
        and left["pcmBytes"] == right["pcmBytes"]
        and receipt.get("byteIdentical")
        is (left["fileSha256"] == right["fileSha256"])
        and receipt.get("decodedAudioMatch") is True
        and receipt.get("streamFactsMatch") is True
        and receipt.get("passed") is True
    )
    if not common:
        return None
    return _picture_classification(
        receipt.get("pictureComparison"), left, right,
        fixture["durationFrames"])


def _calibration_matches(value: object) -> bool:
    keys = {"path", "sha256", "documentSha256", "document"}
    if not isinstance(value, dict) or set(value) != keys:
        return False
    document = value["document"]
    if not isinstance(document, dict):
        return False
    unhashed = {key: item for key, item in document.items()
                if key != "receiptHash"}
    observed = document.get("observed")
    sources = document.get("sourceFiles")
    tools = document.get("tools")
    canonical_file = canonical_bytes(document) + b"\n"
    try:
        validate_source_record_shape(document.get("source"))
    except (RuntimeError, TypeError, ValueError):
        return False
    return (
        value["path"] == CALIBRATION_PATH
        and value["sha256"] == hashlib.sha256(canonical_file).hexdigest()
        and value["documentSha256"] == document_sha256(document)
        and document.get("policy") == CODEC_FLOOR_POLICY
        and document.get("policyHash") == object_hash(CODEC_FLOOR_POLICY)
        and document.get("receiptHash") == object_hash(unhashed)
        and document.get("passed") is True
        and isinstance(observed, dict)
        and observed.get("pairCount", 0)
        >= CODEC_FLOOR_POLICY["minimumControlPairs"]
        and isinstance(document.get("pairs"), list)
        and len(document["pairs"]) == observed.get("pairCount")
        and isinstance(sources, dict)
        and bool(sources)
        and all(isinstance(path, str) and path.startswith("/")
                and isinstance(digest, str) and SHA256.fullmatch(digest)
                for path, digest in sources.items())
        and isinstance(tools, dict)
    )


def repeat_classification(
    fixture: dict[str, Any],
    runs: list[dict[str, Any]],
    value: object,
) -> str | None:
    """Return exact/codec class only for a closed calibrated oracle receipt."""
    keys = {
        "schemaVersion", "classification", "receiptPath",
        "receiptSha256", "receipt", "calibrationAuthority", "error",
    }
    if not isinstance(value, dict) or set(value) != keys:
        return None
    receipt = value["receipt"]
    raw_path = value["receiptPath"]
    if not isinstance(receipt, dict) or not isinstance(raw_path, str) or not raw_path:
        return None
    path = Path(raw_path)
    receipt_bytes = canonical_bytes(receipt) + b"\n"
    classification = _receipt_classification(fixture, runs, receipt)
    calibration = value["calibrationAuthority"]
    calibration_doc = calibration.get("document") \
        if isinstance(calibration, dict) else {}
    calibration_tools = calibration_doc.get("tools") \
        if isinstance(calibration_doc, dict) else {}
    receipt_tools = receipt.get("toolchain") or {}
    valid = (
        value["schemaVersion"] == 1
        and value["error"] is None
        and not path.is_absolute()
        and ".." not in path.parts
        and value["receiptSha256"]
        == hashlib.sha256(receipt_bytes).hexdigest()
        and _calibration_matches(calibration)
        and all(_tool_matches(receipt_tools.get(name),
                              calibration_tools.get(name))
                for name in ("ffmpeg", "ffprobe", "oracle"))
    )
    return classification if valid and value["classification"] == classification \
        else None
