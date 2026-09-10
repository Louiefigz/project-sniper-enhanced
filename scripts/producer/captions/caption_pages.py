#!/usr/bin/env python3
"""Precompose exact CaptionTrackV1 shards into bounded Palmier alpha pages."""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass

import captions.caption_page_media as caption_page_media
import captions.caption_page_decode as caption_page_decode
import captions.caption_page_proof as caption_page_proof
import audit.audit_glitch_scan as page_progress_parser
import headless.process_runner as page_process_runner
import palmier.process_deadline as page_process_deadline
from captions.caption_page_media import (
    CaptionPageMediaContext,
    prove_caption_page,
    render_caption_page,
)
from captions.caption_contract import SHA256_RE
from captions.caption_fingerprints import canonical_digest
from captions.caption_shard_contract import validate_caption_shard_manifest
from fingerprints import file_sha256, write_json_atomic

PAGE_MANIFEST_NAME = "caption_pages.json"
_MEDIA_PREFIX = "caption-page-"
MAX_PAGE_SECONDS = 30


@dataclass(frozen=True)
class CaptionPageSet:
    """Materialized page media and its cache behavior."""

    manifest: dict
    cache_hits: int
    rendered: int


def _tool(name: str) -> dict:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"caption page compositor cannot resolve {name}")
    resolved = os.path.realpath(path)
    return {"path": resolved, "sha256": file_sha256(resolved)}


def _tools() -> dict:
    return {"ffmpeg": _tool("ffmpeg"), "ffprobe": _tool("ffprobe")}


def caption_page_implementation_paths() -> dict[str, str]:
    """One exact source map shared by ordinary and held projection identities."""
    modules = {"media": caption_page_media, "pageDecode": caption_page_decode,
               "pageProof": caption_page_proof, "progressParser": page_progress_parser,
               "ownedRunner": page_process_runner, "processDeadline": page_process_deadline}
    return {"planner": os.path.realpath(__file__),
            **{name: os.path.realpath(module.__file__) for name, module in modules.items()}}


def caption_page_compositor_identity() -> tuple[dict, str]:
    """Return the exact current tools/code closure and its canonical digest."""
    tools = _tools()
    digest = canonical_digest(
        "sniper-caption-alpha-page-compositor-v1", {
            "tools": tools, "codec": "png", "pixelFormat": "rgba",
            "alphaMode": "straight", "implementation": {
                name: file_sha256(path) for name, path in caption_page_implementation_paths().items()},
        })
    return tools, digest


def _intersections(rows: list[dict], start: int, end: int) -> list[dict]:
    result = []
    for row in rows:
        left, right = max(start, row["startFrame"]), min(
            end, row["endFrameExclusive"])
        if right <= left:
            continue
        result.append({
            "cueId": row["cueId"], "media": dict(row["media"]),
            "sourceStartFrame": left - row["startFrame"],
            "sourceEndFrameExclusive": right - row["startFrame"],
            "pageStartFrame": left - start,
        })
    return result


def plan_caption_pages(
    manifest: dict,
    total_frames: int,
    max_page_frames: int,
) -> list[dict]:
    """Partition an exact alpha timeline without changing cue z-order."""
    if isinstance(total_frames, bool) or not isinstance(total_frames, int) \
            or total_frames <= 0:
        raise ValueError("caption page total frame authority is invalid")
    if isinstance(max_page_frames, bool) \
            or not isinstance(max_page_frames, int) or max_page_frames <= 0:
        raise ValueError("caption page bound is invalid")
    rows = manifest.get("entries")
    if not isinstance(rows, list):
        raise ValueError("caption page source entries are malformed")
    ordering = [(row["startFrame"], row["endFrameExclusive"], row["cueId"])
                for row in rows]
    if ordering != sorted(ordering):
        raise ValueError("caption page source entries are not ordered")
    if any(row["endFrameExclusive"] > total_frames for row in rows):
        raise ValueError("caption shard exceeds the sealed picture frame extent")
    pages = []
    for start in range(0, total_frames, max_page_frames):
        end = min(total_frames, start + max_page_frames)
        inputs = _intersections(rows, start, end)
        if inputs:
            pages.append({
                "startFrame": start, "endFrameExclusive": end,
                "inputs": inputs,
            })
    return pages


def caption_page_key(
        manifest: dict, compositor_hash: str, page: dict) -> str:
    """Return the deterministic identity for one exact page projection."""
    return canonical_digest("sniper-caption-alpha-page-v1", {
        "fps": manifest["fps"], "destination": manifest["destination"],
        "compositorHash": compositor_hash, "page": page,
    })


def _current(path: str, receipt_path: str, expected: dict,
             media_context: CaptionPageMediaContext) -> dict | None:
    try:
        with open(receipt_path, encoding="utf-8") as handle:
            receipt = json.load(handle)
        payload = {key: value for key, value in receipt.items()
                   if key != "authorityHash"}
        valid = receipt.get("authorityHash") == canonical_digest(
            "sniper-caption-alpha-page-authority-v1", payload)
        cache_keys = set(expected) - {
            "captionAuthorityHash", "shardManifestHash"}
        valid = valid and all(
            receipt.get(key) == expected[key] for key in cache_keys)
        valid = valid and receipt.get("media") == {
            "name": os.path.basename(path), "sha256": file_sha256(path)}
        if valid:
            frames = expected["endFrameExclusive"] - expected["startFrame"]
            prove_caption_page(path, media_context, frames)
            payload = {**receipt, **expected}
            payload.pop("authorityHash", None)
            rebound = {
                **payload, "authorityHash": canonical_digest(
                    "sniper-caption-alpha-page-authority-v1", payload),
            }
            if rebound != receipt:
                write_json_atomic(receipt_path, rebound, indent=2)
            return rebound
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError,
            AttributeError):
        return None
    return None


def _entry(receipt: dict) -> dict:
    return {
        key: receipt[key] for key in (
            "pageId", "startFrame", "endFrameExclusive", "cueIds",
            "media", "proof", "authorityHash",
        )
    }


def _one(page: dict, context: dict) -> tuple[dict, bool]:
    key = caption_page_key(
        context["manifest"], context["compositorHash"], page)
    media_path = os.path.join(context["directory"], f"{_MEDIA_PREFIX}{key}.mov")
    receipt_path = media_path + ".json"
    expected = {
        "schemaVersion": 1, "kind": "caption-alpha-page-authority",
        "pageId": key, "startFrame": page["startFrame"],
        "endFrameExclusive": page["endFrameExclusive"],
        "cueIds": [row["cueId"] for row in page["inputs"]],
        "captionAuthorityHash": context["captionAuthorityHash"],
        "shardManifestHash": context["shardHash"],
        "compositorHash": context["compositorHash"],
        "inputs": page["inputs"],
        "command": caption_page_media.caption_page_command(
            page, context["mediaContext"], media_path),
    }
    receipt = _current(
        media_path, receipt_path, expected, context["mediaContext"])
    rendered = receipt is None
    if rendered:
        proof, command = render_caption_page(
            page, media_path, context["mediaContext"])
        if command != expected["command"]:
            raise RuntimeError("caption page renderer command drifted")
        payload = {
            **expected,
            "proof": proof, "media": {
                "name": os.path.basename(media_path),
                "sha256": file_sha256(media_path),
            },
        }
        receipt = {
            **payload, "authorityHash": canonical_digest(
                "sniper-caption-alpha-page-authority-v1", payload),
        }
        write_json_atomic(receipt_path, receipt, indent=2)
    return _entry(receipt), rendered


def materialize_caption_pages(
        shard_manifest: dict, caption_authority: dict,
        directory: str, total_frames: int) -> CaptionPageSet:
    """Render/reuse bounded full-canvas pages from a final-bound shard set."""
    manifest = validate_caption_shard_manifest(shard_manifest, directory)
    caption_hash = caption_authority.get("authorityHash")
    if not isinstance(caption_hash, str) or not SHA256_RE.fullmatch(
            caption_hash):
        raise ValueError("caption page source authority is malformed")
    fps = manifest["fps"]
    max_page_frames = max(
        1, int(fps["numerator"]) * MAX_PAGE_SECONDS
        // int(fps["denominator"]))
    pages = plan_caption_pages(manifest, total_frames, max_page_frames)
    tools, compositor_hash = caption_page_compositor_identity()
    context = {
        "manifest": manifest, "directory": os.path.abspath(directory),
        "captionAuthorityHash": caption_hash,
        "shardHash": manifest["authorityHash"], "tools": tools,
        "compositorHash": compositor_hash,
    }
    context["mediaContext"] = CaptionPageMediaContext(
        manifest, context["directory"], tools)
    entries, hits, rendered = [], 0, 0
    for page in pages:
        entry, changed = _one(page, context)
        entries.append(entry)
        rendered += int(changed)
        hits += int(not changed)
    payload = {
        "schemaVersion": 1, "kind": "caption-alpha-page-manifest",
        "totalFrames": total_frames, "maxPageFrames": max_page_frames,
        "fps": manifest["fps"], "destination": manifest["destination"],
        "captionAuthorityHash": caption_hash,
        "shardManifestHash": manifest["authorityHash"],
        "compositorHash": compositor_hash, "entries": entries,
    }
    result = {
        **payload, "authorityHash": canonical_digest(
            "sniper-caption-alpha-page-manifest-v1", payload),
    }
    write_json_atomic(
        os.path.join(directory, PAGE_MANIFEST_NAME), result, indent=2)
    return CaptionPageSet(result, hits, rendered)
