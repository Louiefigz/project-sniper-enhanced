"""Validate production title-card authority and plan exact Palmier assets."""
from __future__ import annotations

import json
import os
from fractions import Fraction

from captions.caption_fingerprints import canonical_digest
from captions.title_card_shards import TITLE_CARD_AUTHORITY_NAME
from cut_manifestation_authority import verify_manifestation
from fingerprints import file_sha256
from palmier.desktop_caption_shard_plan import (
    FULL_CANVAS_TRANSFORM, TITLE_OP,
)
from palmier.mcp_client import PalmierError

LANE = "title-cards-alpha"


def _receipt(out_dir: str) -> dict:
    path = os.path.join(out_dir, TITLE_CARD_AUTHORITY_NAME)
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PalmierError(
            f"title-card alpha authority is unavailable: {exc}") from exc
    if not isinstance(value, dict):
        raise PalmierError("title-card alpha authority is malformed")
    payload = {key: item for key, item in value.items()
               if key != "authorityHash"}
    expected = canonical_digest(
        "sniper-title-card-alpha-authority-v1", payload)
    if value.get("authorityHash") != expected:
        raise PalmierError("title-card alpha authority hash is stale")
    return value


def _validate_header(
        receipt: dict, plan: dict, out_dir: str,
        project: dict, target_frames: int) -> None:
    manifestation = verify_manifestation(out_dir, plan)
    settings = project.get("projectSettings") or {}
    try:
        rate = Fraction(receipt["frameRate"])
        project_rate = Fraction(str(settings["fps"]))
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise PalmierError("title-card clock is malformed") from exc
    expected = (
        canonical_digest(
            "sniper-title-card-plan-v1", plan.get("titleCards") or []),
        manifestation["receiptHash"], manifestation["timelineMapSha256"],
        project_rate, settings.get("width"), settings.get("height"),
        target_frames,
    )
    canvas = receipt.get("canvas") or {}
    actual = (
        receipt.get("planTitleCardsHash"),
        receipt.get("manifestationReceiptHash"),
        receipt.get("timelineMapSha256"), rate,
        canvas.get("width"), canvas.get("height"),
        manifestation["concat"]["videoFrames"],
    )
    if actual != expected:
        raise PalmierError(
            "title-card alpha authority differs from plan/project/master")


def _row(value: object, target_frames: int) -> tuple[dict, dict]:
    if not isinstance(value, dict):
        raise PalmierError("title-card alpha entry is malformed")
    media = value.get("media") or {}
    path, digest = media.get("path"), media.get("sha256")
    start, end = value.get("startFrame"), value.get("endFrameExclusive")
    valid = (
        isinstance(path, str) and os.path.isabs(path)
        and os.path.isfile(path) and not os.path.islink(path)
        and isinstance(digest, str) and file_sha256(path) == digest
        and isinstance(start, int) and not isinstance(start, bool)
        and isinstance(end, int) and not isinstance(end, bool)
        and 0 <= start < end <= target_frames
        and isinstance(value.get("elementId"), str))
    if not valid:
        raise PalmierError("title-card alpha media authority is stale")
    key = f"title:{digest}"
    imported = {
        "op": "import", "lane": LANE, "key": key,
        "elementId": value["elementId"], "path": path,
        "importName": f"Sniper · title · {value['elementId']}",
    }
    placed = {
        "op": TITLE_OP, "lane": LANE, "elementId": value["elementId"],
        "mediaKey": key, "assetPath": path, "assetHash": digest,
        "startFrame": start, "endFrame": end, "alphaMode": "straight",
        "trackPolicy": "new-top-video-track-per-card",
        "transform": FULL_CANVAS_TRANSFORM,
    }
    return imported, placed


def plan_title_card_shards(
        plan: dict, out_dir: str, project: dict,
        target_frames: int) -> tuple[list[dict], dict]:
    """Return governed full-canvas title assets or fail before mutation."""
    cards = plan.get("titleCards") or []
    if not cards:
        return [], {}
    receipt = _receipt(out_dir)
    _validate_header(receipt, plan, out_dir, project, target_frames)
    entries = receipt.get("entries")
    if not isinstance(entries, list) or len(entries) != len(cards):
        raise PalmierError("title-card alpha authority has incomplete coverage")
    pairs = [_row(value, target_frames) for value in entries]
    imports, placements = zip(*pairs, strict=True)
    return [*imports, *placements], {
        "schemaVersion": 1, "mode": "baked-regenerable-alpha-shards",
        "status": "required", "editableText": False,
        "nonEditableReason": (
            "brand geometry/font/fade are exact in the governed alpha asset"),
        "cardCount": len(placements),
        "authorityHash": receipt["authorityHash"],
        "targetFrames": target_frames,
    }
