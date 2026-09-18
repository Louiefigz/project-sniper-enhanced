"""Validate and plan exact CaptionTrackV1 alpha-shard placements."""
from __future__ import annotations

import json
import os
from fractions import Fraction

from captions.caption_authority import expected_caption_hashes
from captions.caption_fingerprints import canonical_digest
from captions.caption_shard_authority import validate_bound_shards
from captions.caption_shard_contract import validate_caption_shard_manifest
from palmier.mcp_client import PalmierError

OP = "caption-alpha-shard"
TITLE_OP = "title-alpha-shard"
GRAPHICS_OP = "graphics-alpha-shard"
BROLL_OP = "native-broll"
ALPHA_OPS = {OP, TITLE_OP, GRAPHICS_OP, BROLL_OP}
FULL_CANVAS_TRANSFORM = {
    "width": 1.0, "height": 1.0, "centerX": 0.5, "centerY": 0.5,
}
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


def _caption_authority(plan: dict, out_dir: str) -> tuple[dict, dict]:
    authority = _object(
        os.path.join(out_dir, "caption_authority.json"),
        "caption render authority")
    payload = {key: value for key, value in authority.items()
               if key != "authorityHash"}
    expected = canonical_digest(
        "sniper-caption-render-authority-v1", payload)
    hashes = expected_caption_hashes(plan)
    actual = (authority.get("captionTrackHash"),
              authority.get("correctionLedgerHash"))
    if hashes is None or actual != hashes \
            or authority.get("authorityHash") != expected:
        raise PalmierError(
            "caption render authority does not bind CaptionTrackV1")
    stale = validate_bound_shards(out_dir, authority)
    if stale:
        raise PalmierError(stale)
    manifest = _object(
        os.path.join(out_dir, "caption_shards.json"),
        "caption alpha-shard manifest")
    try:
        return authority, validate_caption_shard_manifest(manifest, out_dir)
    except ValueError as exc:
        raise PalmierError(
            f"caption alpha-shard authority is stale: {exc}") from exc


def _palmier_entries(out_dir: str, manifest: dict) -> list[dict]:
    value = _object(
        os.path.join(out_dir, "caption_palmier.json"),
        "Palmier caption projection")
    required = {
        "schemaVersion", "kind", "fidelity", "readbackRequired", "entries"}
    if set(value) != required or value.get("schemaVersion") != 1 \
            or value.get("kind") != "regenerable-alpha-captions" \
            or value.get("fidelity") != "baked-regenerable" \
            or value.get("readbackRequired") is not True:
        raise PalmierError("Palmier caption projection is not exact alpha")
    entries = value.get("entries")
    by_cue = {row["cueId"]: row for row in manifest["entries"]}
    if not isinstance(entries, list) or {
            row.get("elementId") for row in entries
            if isinstance(row, dict)} != set(by_cue):
        raise PalmierError("Palmier captions do not cover every alpha shard")
    _validate_entries(entries, by_cue, out_dir)
    return entries


def _validate_entries(entries: list[dict], by_cue: dict,
                      out_dir: str) -> None:
    for row in entries:
        shard = by_cue.get(row.get("elementId"))
        expected = {
            "mediaKey": shard["mediaKey"],
            "mediaPath": os.path.join(out_dir, shard["media"]["name"]),
            "mediaSha256": shard["media"]["sha256"],
            "startFrame": shard["startFrame"],
            "endFrameExclusive": shard["endFrameExclusive"],
        }
        drifted = any(
            os.path.abspath(str(row.get(key))) != os.path.abspath(value)
            if key == "mediaPath" else row.get(key) != value
            for key, value in expected.items())
        if drifted:
            raise PalmierError(
                "Palmier caption projection drifted from shards")


def _placement(row: dict, target_frames: int) -> tuple[dict, dict]:
    start = row["startFrame"]
    end = row["endFrameExclusive"]
    if start < 0 or end <= start:
        raise PalmierError("caption shard falls outside exact master frames")
    if end > target_frames:
        raise PalmierError(
            "caption shard exceeds the exact master; regenerate the "
            "caption compilation at the sealed frame count")
    key = f"caption:{row['mediaKey']}"
    imported = {
        "op": "import", "lane": LANE, "key": key,
        "elementId": row["elementId"], "path": row["mediaPath"],
        "importName": f"Sniper · caption · {row['elementId']}",
    }
    placed = {
        "op": OP, "lane": LANE, "elementId": row["elementId"],
        "mediaKey": key, "assetPath": row["mediaPath"],
        "assetHash": row["mediaSha256"],
        "startFrame": start, "endFrame": end,
        "sourceEndFrameExclusive": row["endFrameExclusive"],
        "clippedToExactMaster": False,
        "trackPolicy": "new-top-video-track-per-cue",
        "alphaMode": row.get("alphaMode"),
        "transform": FULL_CANVAS_TRANSFORM,
    }
    return imported, placed


def _clock_matches(project: dict, manifest: dict) -> bool:
    settings = project.get("projectSettings") or {}
    fps = manifest["fps"]
    try:
        project_rate = Fraction(str(settings.get("fps")))
        manifest_rate = Fraction(
            int(fps["numerator"]), int(fps["denominator"]))
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return False
    expected = (project_rate,
                settings.get("width"), settings.get("height"))
    actual = (manifest_rate,
              manifest["destination"]["width"],
              manifest["destination"]["height"])
    return actual == expected


def plan_caption_shards(
        plan: dict, out_dir: str, project: dict,
        target_frames: int) -> tuple[list[dict], dict]:
    """Return one dedicated top-track alpha clip per exact compiled cue."""
    if not isinstance(plan.get("captionsTrack"), dict):
        return [], {}
    authority, manifest = _caption_authority(plan, out_dir)
    if not _clock_matches(project, manifest):
        raise PalmierError(
            "caption alpha-shard clock/canvas differs from project")
    entries = sorted(
        _palmier_entries(out_dir, manifest),
        key=lambda row: (row["startFrame"], row["elementId"]))
    pairs = [_placement(row, target_frames) for row in entries]
    imports, placements = zip(*pairs, strict=True) if pairs else ((), ())
    capability = {
        "schemaVersion": 1, "mode": "baked-regenerable-alpha-shards",
        "status": "required", "editableText": False,
        "nonEditableReason": (
            "Palmier native captions cannot prove exact karaoke timing/style"),
        "cueCount": len(placements),
        "captionAuthorityHash": authority["authorityHash"],
        "shardManifestHash": manifest["authorityHash"],
        "targetFrames": target_frames,
    }
    return [*imports, *placements], capability
