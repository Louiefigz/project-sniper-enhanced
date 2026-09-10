"""Validate CaptionTrackV1 page authority for one bounded Palmier track."""
from __future__ import annotations

import json
import os
from fractions import Fraction

from captions.caption_fingerprints import canonical_digest
from captions.caption_page_contract import validate_caption_page_manifest
from captions.caption_pages import PAGE_MANIFEST_NAME
from fingerprints import file_sha256
from palmier.desktop_caption_shard_plan import (
    FULL_CANVAS_TRANSFORM, _caption_authority,
)
from palmier.mcp_client import PalmierError

OP = "caption-alpha-pages"
LANE = "captions-alpha"


def _object(path: str, label: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PalmierError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise PalmierError(f"{label} is malformed")
    return value


def _manifest(out_dir: str, authority: dict) -> dict:
    value = _object(
        os.path.join(out_dir, PAGE_MANIFEST_NAME),
        "caption alpha-page manifest")
    try:
        return validate_caption_page_manifest(
            value, out_dir, authority)
    except ValueError as exc:
        raise PalmierError(
            f"caption alpha-page authority is stale: {exc}") from exc


def _clock(project: dict, pages: dict, target: int) -> None:
    settings = project.get("projectSettings") or {}
    fps = pages.get("fps") or {}
    destination = pages.get("destination") or {}
    try:
        actual_rate = Fraction(
            int(fps["numerator"]), int(fps["denominator"]))
        project_rate = Fraction(str(settings["fps"]))
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise PalmierError("caption alpha-page clock is malformed") from exc
    actual = (
        pages.get("totalFrames"), actual_rate,
        destination.get("width"), destination.get("height"))
    expected = (
        target, project_rate, settings.get("width"), settings.get("height"))
    if actual != expected:
        raise PalmierError("caption alpha-page master/canvas clock differs")


def _entry(value: object, out_dir: str, target: int) -> tuple[dict, dict]:
    if not isinstance(value, dict):
        raise PalmierError("caption alpha-page entry is malformed")
    media = value.get("media") or {}
    name, digest = media.get("name"), media.get("sha256")
    path = os.path.join(out_dir, str(name))
    start, end = value.get("startFrame"), value.get("endFrameExclusive")
    valid = (
        isinstance(name, str) and os.path.basename(name) == name
        and os.path.isfile(path) and not os.path.islink(path)
        and isinstance(digest, str) and file_sha256(path) == digest
        and isinstance(start, int) and not isinstance(start, bool)
        and isinstance(end, int) and not isinstance(end, bool)
        and 0 <= start < end <= target
        and isinstance(value.get("pageId"), str))
    if not valid:
        raise PalmierError("caption alpha-page media authority is stale")
    receipt = _object(path + ".json", "caption alpha-page receipt")
    payload = {key: item for key, item in receipt.items()
               if key != "authorityHash"}
    expected_hash = canonical_digest(
        "sniper-caption-alpha-page-authority-v1", payload)
    if receipt.get("authorityHash") != value.get("authorityHash") \
            or receipt.get("authorityHash") != expected_hash \
            or receipt.get("media") != media:
        raise PalmierError("caption alpha-page receipt is stale")
    key = f"caption-page:{value['pageId']}"
    imported = {
        "op": "import", "lane": LANE, "key": key,
        "elementId": f"caption-page:{value['pageId']}",
        "path": path, "importName": f"Sniper · caption page · {start}",
    }
    placed = {
        "elementId": imported["elementId"], "mediaKey": key,
        "assetPath": path, "assetHash": digest,
        "startFrame": start, "endFrame": end,
        "transform": FULL_CANVAS_TRANSFORM,
    }
    return imported, placed


def plan_caption_pages(
        plan: dict, out_dir: str, project: dict,
        target_frames: int) -> tuple[list[dict], dict]:
    """Plan all bounded caption pages on one dedicated top video track."""
    if not isinstance(plan.get("captionsTrack"), dict):
        return [], {}
    authority, shards = _caption_authority(plan, out_dir)
    pages = _manifest(out_dir, authority)
    _clock(project, pages, target_frames)
    expected = (
        authority["authorityHash"], shards["authorityHash"])
    actual = (
        pages.get("captionAuthorityHash"), pages.get("shardManifestHash"))
    if actual != expected:
        raise PalmierError("caption pages do not bind current caption shards")
    values = pages.get("entries")
    if not isinstance(values, list) or not values:
        raise PalmierError("CaptionTrackV1 produced no governed alpha pages")
    pairs = [_entry(value, out_dir, target_frames) for value in values]
    imports, placements = zip(*pairs, strict=True)
    ordered = [(row["startFrame"], row["endFrame"]) for row in placements]
    if ordered != sorted(ordered) \
            or any(left[1] > right[0]
                   for left, right in zip(ordered, ordered[1:])):
        raise PalmierError("caption alpha pages overlap or are unordered")
    step = {
        "op": OP, "lane": LANE, "entries": list(placements),
        "trackPolicy": "one-new-top-video-track-for-all-pages",
        "alphaMode": "straight",
    }
    return [*imports, step], {
        "schemaVersion": 1, "mode": "baked-regenerable-alpha-pages",
        "status": "required", "editableText": False,
        "pageCount": len(placements),
        "captionAuthorityHash": authority["authorityHash"],
        "pageManifestHash": pages["authorityHash"],
        "targetFrames": target_frames,
    }
