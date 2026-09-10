#!/usr/bin/env python3
"""Closed runtime contract for render-consumed caption alpha-shard manifests."""
from __future__ import annotations

import os
import re
from fractions import Fraction

from captions.caption_context import validate_destination
from captions.caption_contract import CaptionContractError, SHA256_RE
from captions.caption_fingerprints import canonical_digest
from fingerprints import file_sha256

_CODEPOINT_RE = re.compile(r"^U\+[0-9A-F]{4,6}$")
_MANIFEST_KEYS = {
    "schemaVersion", "kind", "fps", "destination", "rendererHash",
    "fontClosure", "entries", "authorityHash",
}
_ENTRY_KEYS = {
    "cueId", "mediaKey", "placedShardKey", "contentAssetKey",
    "startFrame", "endFrameExclusive", "fps", "destination", "media",
    "rendererHash", "fontClosureHash", "proof",
}


def _exact(value: object, keys: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise CaptionContractError(f"{label} has unknown or missing fields")
    return value


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise CaptionContractError(f"{label} is not a SHA-256 digest")
    return value


def _rate(value: object) -> dict:
    row = _exact(value, {"numerator", "denominator"},
                 "caption shard frame rate")
    try:
        numerator, denominator = int(row["numerator"]), int(row["denominator"])
        rate = Fraction(numerator, denominator)
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise CaptionContractError(
            "caption shard frame rate is malformed") from exc
    canonical = (
        str(numerator) == row["numerator"]
        and str(denominator) == row["denominator"]
        and numerator > 0 and denominator > 0
        and (rate.numerator, rate.denominator) == (numerator, denominator)
    )
    if not canonical:
        raise CaptionContractError(
            "caption shard frame rate is not canonical")
    return dict(row)


def _file_identity(value: object, label: str,
                   verify: bool) -> dict:
    row = _exact(value, {"path", "sha256"}, label)
    path = row["path"]
    if not isinstance(path, str) or not os.path.isabs(path):
        raise CaptionContractError(f"{label} path is not absolute")
    _sha(row["sha256"], f"{label} hash")
    if verify and (not os.path.isfile(path)
                   or file_sha256(path) != row["sha256"]):
        raise CaptionContractError(f"{label} bytes are missing or stale")
    return row


def _font_request(value: object) -> dict:
    row = _exact(value, {"styleId", "family", "codepoints"},
                 "caption font request")
    if any(not isinstance(row[key], str) or not row[key]
           for key in ("styleId", "family")):
        raise CaptionContractError("caption font request name is malformed")
    codepoints = row["codepoints"]
    if not isinstance(codepoints, list) or len(codepoints) != len(
            set(codepoints)) or any(
            not isinstance(item, str) or not _CODEPOINT_RE.fullmatch(item)
            for item in codepoints):
        raise CaptionContractError(
            "caption font request codepoints are malformed")
    return row


def _font_file(value: object, verify: bool) -> dict:
    row = _exact(value, {"path", "sha256", "families"},
                 "caption font file")
    _file_identity(
        {"path": row["path"], "sha256": row["sha256"]},
        "caption font file", verify)
    families = row["families"]
    if not isinstance(families, list) or not families \
            or len(families) != len(set(families)) \
            or any(not isinstance(item, str) or not item for item in families):
        raise CaptionContractError("caption font families are malformed")
    return row


def _font_closure(value: object, verify: bool) -> dict:
    row = _exact(value, {
        "schemaVersion", "kind", "tools", "requests", "files",
        "authorityHash",
    }, "caption font closure")
    if row["schemaVersion"] != 1 or row["kind"] != "caption-font-closure":
        raise CaptionContractError("caption font closure version is unsupported")
    tools = _exact(row["tools"], {"fcMatch", "fcQuery"},
                   "caption font tools")
    for name, tool in tools.items():
        _file_identity(tool, f"caption font tool {name}", verify)
    requests, files = row["requests"], row["files"]
    if not isinstance(requests, list) or not isinstance(files, list):
        raise CaptionContractError("caption font closure lists are malformed")
    for request in requests:
        _font_request(request)
    for font in files:
        _font_file(font, verify)
    payload = {key: item for key, item in row.items()
               if key != "authorityHash"}
    expected = canonical_digest("sniper-caption-font-closure-v1", payload)
    if row["authorityHash"] != expected:
        raise CaptionContractError("caption font closure digest is stale")
    return row


def _proof(value: object, frames: int, destination: dict) -> dict:
    row = _exact(value, {
        "stream", "edgeAlphaMax", "shapedSafeBounds",
    }, "caption shard proof")
    stream = _exact(row["stream"], {
        "codec_name", "pix_fmt", "width", "height", "r_frame_rate",
        "nb_read_frames",
    }, "caption shard stream proof")
    if stream["codec_name"] != "png" or stream["pix_fmt"] != "rgba" \
            or stream["width"] != destination["width"] \
            or stream["height"] != destination["height"] \
            or stream["nb_read_frames"] != str(frames):
        raise CaptionContractError("caption shard stream proof is stale")
    maxima = row["edgeAlphaMax"]
    expected_edges = 1 if frames == 1 else 2
    if not isinstance(maxima, list) or len(maxima) != expected_edges \
            or any(isinstance(item, bool)
                   or not isinstance(item, (int, float))
                   or not 0 < item <= 255 for item in maxima):
        raise CaptionContractError("caption shard edge-alpha proof is malformed")
    bounds = _exact(row["shapedSafeBounds"], {
        "minX", "maxX", "minY", "maxY", "framesMeasured",
    }, "caption shaped-bounds proof")
    safe = destination["safeZones"]
    valid = all(isinstance(bounds[key], int) and not isinstance(
        bounds[key], bool) for key in bounds)
    valid = valid and bounds["framesMeasured"] == frames
    valid = valid and safe["left"] <= bounds["minX"] <= bounds["maxX"] \
        < destination["width"] - safe["right"]
    valid = valid and safe["top"] <= bounds["minY"] <= bounds["maxY"] \
        < destination["height"] - safe["bottom"]
    if not valid:
        raise CaptionContractError("caption shaped-bounds proof is stale")
    return row


def _entry(value: object, manifest: dict, directory: str | None) -> dict:
    row = _exact(value, _ENTRY_KEYS, "caption shard entry")
    for key in ("mediaKey", "placedShardKey", "contentAssetKey",
                "rendererHash", "fontClosureHash"):
        _sha(row[key], f"caption shard {key}")
    if not isinstance(row["cueId"], str) or not row["cueId"]:
        raise CaptionContractError("caption shard cueId is malformed")
    start, end = row["startFrame"], row["endFrameExclusive"]
    if any(isinstance(item, bool) or not isinstance(item, int)
           for item in (start, end)) or start < 0 or end <= start:
        raise CaptionContractError("caption shard frame range is malformed")
    if row["fps"] != manifest["fps"] \
            or row["destination"] != manifest["destination"]:
        raise CaptionContractError("caption shard clock/canvas authority drifted")
    media = _exact(row["media"], {"name", "sha256"},
                   "caption shard media")
    expected_name = f"caption-shard-{row['mediaKey']}.mov"
    if media["name"] != expected_name:
        raise CaptionContractError("caption shard media name is stale")
    _sha(media["sha256"], "caption shard media hash")
    if directory is not None:
        path = os.path.join(directory, media["name"])
        if not os.path.isfile(path) or file_sha256(path) != media["sha256"]:
            raise CaptionContractError("caption shard media is missing or stale")
    _proof(row["proof"], end - start, manifest["destination"])
    return row


def validate_caption_shard_manifest(
    value: object,
    directory: str | None = None,
) -> dict:
    """Validate a closed manifest and optionally every local dependency byte."""
    row = _exact(value, _MANIFEST_KEYS, "caption alpha-shard manifest")
    if row["schemaVersion"] != 1 \
            or row["kind"] != "caption-alpha-shard-manifest":
        raise CaptionContractError(
            "caption alpha-shard manifest version is unsupported")
    _rate(row["fps"])
    validate_destination(row["destination"])
    _sha(row["rendererHash"], "caption renderer-set hash")
    _font_closure(row["fontClosure"], directory is not None)
    entries = row["entries"]
    if not isinstance(entries, list):
        raise CaptionContractError("caption alpha-shard entries are malformed")
    for item in entries:
        _entry(item, row, directory)
    cue_ids = [item["cueId"] for item in entries]
    if len(cue_ids) != len(set(cue_ids)):
        raise CaptionContractError("caption alpha-shard cue ids are duplicate")
    renderer_hash = canonical_digest(
        "sniper-caption-alpha-renderer-set-v1",
        [item["rendererHash"] for item in entries])
    if row["rendererHash"] != renderer_hash:
        raise CaptionContractError("caption renderer-set hash is stale")
    payload = {key: item for key, item in row.items()
               if key != "authorityHash"}
    expected = canonical_digest(
        "sniper-caption-alpha-shard-manifest-v1", payload)
    if row["authorityHash"] != expected:
        raise CaptionContractError("caption alpha-shard manifest digest is stale")
    return row
