#!/usr/bin/env python3
"""Strict runtime validation for bounded CaptionTrackV1 alpha pages."""
from __future__ import annotations

import json
import os
from pathlib import Path

from captions.caption_context import validate_destination
from captions.caption_contract import CaptionContractError, SHA256_RE
from captions.caption_fingerprints import canonical_digest
from captions.caption_page_media import (
    CaptionPageMediaContext,
    caption_page_command,
)
from captions.caption_pages import (
    caption_page_compositor_identity,
    caption_page_key,
    plan_caption_pages,
)
from captions.caption_shard_contract import validate_caption_shard_manifest
from fingerprints import file_sha256

_MANIFEST_KEYS = {
    "schemaVersion", "kind", "totalFrames", "maxPageFrames", "fps",
    "destination", "captionAuthorityHash", "shardManifestHash",
    "compositorHash", "entries", "authorityHash",
}
_ENTRY_KEYS = {
    "pageId", "startFrame", "endFrameExclusive", "cueIds",
    "media", "proof", "authorityHash",
}
_RECEIPT_KEYS = {
    "schemaVersion", "kind", "pageId", "startFrame", "endFrameExclusive",
    "cueIds", "captionAuthorityHash", "shardManifestHash", "compositorHash",
    "inputs", "command", "proof", "media", "authorityHash",
}
_INPUT_KEYS = {
    "cueId", "media", "sourceStartFrame", "sourceEndFrameExclusive",
    "pageStartFrame",
}


def _exact(value: object, keys: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise CaptionContractError(f"{label} has unknown or missing fields")
    return value


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise CaptionContractError(f"{label} is not a SHA-256 digest")
    return value


def _positive(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CaptionContractError(f"{label} is not a positive integer")
    return value


def _object(path: str, label: str) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CaptionContractError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise CaptionContractError(f"{label} is not an object")
    return value


def _media(value: object, page_id: str, directory: str) -> dict:
    row = _exact(value, {"name", "sha256"}, "caption page media")
    expected = f"caption-page-{page_id}.mov"
    if row["name"] != expected:
        raise CaptionContractError("caption page media name is stale")
    _sha(row["sha256"], "caption page media hash")
    path = os.path.join(directory, expected)
    if not os.path.isfile(path) or os.path.islink(path) \
            or file_sha256(path) != row["sha256"]:
        raise CaptionContractError("caption page media bytes are stale")
    return row


def _proof(value: object, manifest: dict, frames: int) -> dict:
    row = _exact(value, {
        "stream", "decodedFrameMd5Sha256", "alphaMax", "framesMeasured",
    }, "caption page proof")
    stream = _exact(row["stream"], {
        "codec_name", "pix_fmt", "width", "height", "r_frame_rate",
        "nb_read_frames",
    }, "caption page stream proof")
    fps = manifest["fps"]
    expected_rate = f"{fps['numerator']}/{fps['denominator']}"
    destination = manifest["destination"]
    expected = {
        "codec_name": "png", "pix_fmt": "rgba",
        "width": destination["width"], "height": destination["height"],
        "r_frame_rate": expected_rate, "nb_read_frames": str(frames),
    }
    valid = stream == expected and row["framesMeasured"] == frames \
        and isinstance(row["alphaMax"], (int, float)) \
        and not isinstance(row["alphaMax"], bool) \
        and 0 < row["alphaMax"] <= 255
    if not valid:
        raise CaptionContractError("caption page decoded proof is stale")
    _sha(row["decodedFrameMd5Sha256"], "caption page decoded hash")
    return row


def _input(value: object, source: dict) -> dict:
    row = _exact(value, _INPUT_KEYS, "caption page input")
    if row["cueId"] != source["cueId"] or row["media"] != source["media"]:
        raise CaptionContractError("caption page input source is stale")
    numbers = (
        row["sourceStartFrame"], row["sourceEndFrameExclusive"],
        row["pageStartFrame"])
    if any(isinstance(item, bool) or not isinstance(item, int)
           for item in numbers) or numbers[0] < 0 \
            or numbers[1] <= numbers[0] or numbers[2] < 0 \
            or numbers[1] > source["endFrameExclusive"] - source["startFrame"]:
        raise CaptionContractError("caption page input range is malformed")
    return row


def _receipt(entry: dict, manifest: dict, shards: dict,
             directory: str) -> dict:
    page_id = _sha(entry["pageId"], "caption page id")
    path = os.path.join(directory, f"caption-page-{page_id}.mov.json")
    receipt = _exact(_object(path, "caption page receipt"),
                     _RECEIPT_KEYS, "caption page receipt")
    payload = {key: value for key, value in receipt.items()
               if key != "authorityHash"}
    expected_hash = canonical_digest(
        "sniper-caption-alpha-page-authority-v1", payload)
    if receipt["authorityHash"] != expected_hash \
            or entry != {key: receipt[key] for key in _ENTRY_KEYS}:
        raise CaptionContractError("caption page receipt authority is stale")
    expected = (
        manifest["captionAuthorityHash"], manifest["shardManifestHash"],
        manifest["compositorHash"])
    actual = (
        receipt["captionAuthorityHash"], receipt["shardManifestHash"],
        receipt["compositorHash"])
    if actual != expected:
        raise CaptionContractError("caption page source authority drifted")
    _validate_receipt_content(receipt, manifest, shards, directory)
    return receipt


def _validate_receipt_content(
        receipt: dict, manifest: dict, shards: dict, directory: str) -> None:
    start, end = receipt["startFrame"], receipt["endFrameExclusive"]
    frames = end - start
    _media(receipt["media"], receipt["pageId"], directory)
    _proof(receipt["proof"], manifest, frames)
    command = receipt["command"]
    media_path = os.path.join(directory, receipt["media"]["name"])
    if not isinstance(command, list) or not command \
            or any(not isinstance(item, str) for item in command) \
            or command[-1] != media_path:
        raise CaptionContractError("caption page command is malformed")
    by_cue = {row["cueId"]: row for row in shards["entries"]}
    inputs = receipt["inputs"]
    if not isinstance(inputs, list):
        raise CaptionContractError("caption page cue coverage is malformed")
    cue_ids = []
    for row in inputs:
        source = by_cue.get(row.get("cueId")) if isinstance(row, dict) else None
        if source is None:
            raise CaptionContractError("caption page references unknown cue")
        _input(row, source)
        cue_ids.append(row["cueId"])
        if row["pageStartFrame"] + (
                row["sourceEndFrameExclusive"] - row["sourceStartFrame"]
        ) > frames:
            raise CaptionContractError("caption page input exceeds its page")
    if receipt["cueIds"] != cue_ids:
        raise CaptionContractError("caption page cue coverage is malformed")


def _coverage(receipts: list[dict], shards: dict) -> None:
    observed: dict[str, list[tuple[int, int]]] = {}
    for receipt in receipts:
        for row in receipt["inputs"]:
            observed.setdefault(row["cueId"], []).append((
                row["sourceStartFrame"], row["sourceEndFrameExclusive"]))
    for source in shards["entries"]:
        frames = source["endFrameExclusive"] - source["startFrame"]
        ranges = sorted(observed.get(source["cueId"]) or [])
        cursor = 0
        for start, end in ranges:
            if start != cursor:
                raise CaptionContractError("caption page cue coverage has a gap")
            cursor = end
        if cursor != frames:
            raise CaptionContractError("caption page cue coverage is incomplete")


def _determinism(
        receipts: list[dict], pages: list[dict],
        manifest: dict, directory: str) -> None:
    if len(receipts) != len(pages):
        raise CaptionContractError("caption page projection count is stale")
    tools, compositor = caption_page_compositor_identity()
    media_context = CaptionPageMediaContext(manifest, directory, tools)
    for receipt, page in zip(receipts, pages, strict=True):
        expected_id = caption_page_key(
            manifest, compositor, page)
        expected_path = os.path.join(
            directory, f"caption-page-{expected_id}.mov")
        expected = (
            page["startFrame"], page["endFrameExclusive"], page["inputs"],
            expected_id, caption_page_command(
                page, media_context, expected_path))
        actual = (
            receipt["startFrame"], receipt["endFrameExclusive"],
            receipt["inputs"], receipt["pageId"], receipt["command"])
        if actual != expected:
            raise CaptionContractError(
                "caption page deterministic projection is stale")


def validate_caption_page_manifest(
        value: object, directory: str, caption_authority: dict) -> dict:
    """Validate every page/receipt/media byte against the final caption chain."""
    manifest = _exact(value, _MANIFEST_KEYS, "caption page manifest")
    if manifest["schemaVersion"] != 1 \
            or manifest["kind"] != "caption-alpha-page-manifest":
        raise CaptionContractError("caption page manifest version is unsupported")
    _positive(manifest["totalFrames"], "caption page total frames")
    _positive(manifest["maxPageFrames"], "caption page maximum frames")
    validate_destination(manifest["destination"])
    for key in ("captionAuthorityHash", "shardManifestHash",
                "compositorHash", "authorityHash"):
        _sha(manifest[key], f"caption page {key}")
    if manifest["captionAuthorityHash"] != caption_authority.get(
            "authorityHash"):
        raise CaptionContractError("caption page final authority is stale")
    shards_path = os.path.join(directory, "caption_shards.json")
    shards = validate_caption_shard_manifest(
        _object(shards_path, "caption shard manifest"), directory)
    _, current_compositor = caption_page_compositor_identity()
    if manifest["shardManifestHash"] != shards["authorityHash"] \
            or manifest["compositorHash"] != current_compositor \
            or manifest["fps"] != shards["fps"] \
            or manifest["destination"] != shards["destination"]:
        raise CaptionContractError("caption page source/compositor is stale")
    receipts = _entries(manifest, shards, directory)
    pages = plan_caption_pages(
        shards, manifest["totalFrames"], manifest["maxPageFrames"])
    _determinism(receipts, pages, manifest, directory)
    _coverage(receipts, shards)
    payload = {key: value for key, value in manifest.items()
               if key != "authorityHash"}
    if manifest["authorityHash"] != canonical_digest(
            "sniper-caption-alpha-page-manifest-v1", payload):
        raise CaptionContractError("caption page manifest digest is stale")
    return manifest


def _entries(manifest: dict, shards: dict, directory: str) -> list[dict]:
    entries = manifest["entries"]
    if not isinstance(entries, list):
        raise CaptionContractError("caption page entries are malformed")
    receipts, prior_end = [], 0
    for index, value in enumerate(entries):
        entry = _exact(value, _ENTRY_KEYS, f"caption page entry {index}")
        start, end = entry["startFrame"], entry["endFrameExclusive"]
        valid = isinstance(start, int) and not isinstance(start, bool) \
            and isinstance(end, int) and not isinstance(end, bool) \
            and prior_end <= start < end <= manifest["totalFrames"] \
            and end - start <= manifest["maxPageFrames"]
        if not valid:
            raise CaptionContractError("caption page timeline is malformed")
        receipts.append(_receipt(entry, manifest, shards, directory))
        prior_end = end
    return receipts
