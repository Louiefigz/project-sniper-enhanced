#!/usr/bin/env python3
"""Materialize bounded CaptionTrackV1 cues as cacheable alpha video shards."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from fractions import Fraction

from audio.master import _filter_quote
from captions.caption_ass_projection import build_local_cue_ass
from captions.caption_contract import CaptionContractError, SHA256_RE
from captions.caption_fingerprints import canonical_digest
from captions.caption_font_closure import (
    CaptionFontResolver,
    merge_caption_font_closures,
)
from captions.caption_plan_pipeline import caption_styles
from captions.caption_shard_media import prove_caption_shard_media
from fingerprints import file_sha256, write_json_atomic

SHARD_MANIFEST_NAME = "caption_shards.json"
_MEDIA_PREFIX = "caption-shard-"

@dataclass(frozen=True)
class CaptionShardSet:
    """Materialized alpha media plus cache behavior for one compilation."""

    manifest: dict
    cache_hits: int
    rendered: int


def _rate(compilation: dict) -> tuple[Fraction, str]:
    fps = compilation.get("fps")
    try:
        rate = Fraction(int(fps["numerator"]), int(fps["denominator"]))
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise CaptionContractError("caption shard fps is malformed") from exc
    return rate, f"{rate.numerator}/{rate.denominator}"


def _tool_identity(name: str) -> dict:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"caption shard renderer cannot resolve {name}")
    resolved = os.path.realpath(path)
    return {"path": resolved, "sha256": file_sha256(resolved)}


def _render_tools() -> dict:
    return {
        "ffmpeg": _tool_identity("ffmpeg"),
        "ffprobe": _tool_identity("ffprobe"),
    }


def _renderer_hash(font_closure: dict, tools: dict) -> str:
    return canonical_digest("sniper-caption-alpha-renderer-v1", {
        **tools,
        "fontClosureHash": font_closure["authorityHash"],
        "codec": "png", "pixelFormat": "rgba", "alphaMode": "straight",
    })


def _media_key(cue: dict, renderer_hash: str) -> str:
    placement_key = cue.get("placedShardKey")
    if not isinstance(placement_key, str) \
            or not SHA256_RE.fullmatch(placement_key):
        raise CaptionContractError("caption cue has no placed shard key")
    return canonical_digest("sniper-caption-alpha-media-v1", {
        "placedShardKey": placement_key, "rendererHash": renderer_hash,
    })


def _asset_paths(out_dir: str, media_key: str) -> tuple[str, str]:
    name = f"{_MEDIA_PREFIX}{media_key}.mov"
    media = os.path.join(out_dir, name)
    return media, media + ".json"


def _local_ass(compilation: dict, cue: dict,
               styles: dict[str, dict], directory: str) -> str:
    descriptor, path = tempfile.mkstemp(
        prefix=".caption-shard.", suffix=".ass", dir=directory)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(build_local_cue_ass(compilation, cue, styles))
        handle.flush()
        os.fsync(handle.fileno())
    return path


def _render_command(ass_path: str, compilation: dict,
                    frames: int, output: str) -> list[str]:
    _, token = _rate(compilation)
    destination = compilation["destination"]
    fonts = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "assets", "fonts"))
    subtitles = (
        f"subtitles=filename='{_filter_quote(ass_path)}':"
        f"fontsdir='{_filter_quote(fonts)}':alpha=1"
    )
    source = (
        f"color=c=black@0.0:s={destination['width']}x"
        f"{destination['height']}:r={token},format=rgba"
    )
    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", source, "-vf", subtitles,
        "-frames:v", str(frames), "-an", "-c:v", "png",
        "-pix_fmt", "rgba", "-r", token, "-fps_mode", "cfr", output,
    ]


def _remove_render_paths(paths: tuple[str, ...]) -> None:
    for temporary in paths:
        if os.path.exists(temporary):
            os.remove(temporary)


def _render_media(path: str, compilation: dict, cue: dict,
                  styles: dict[str, dict]) -> dict:
    directory = os.path.dirname(path)
    descriptor, staged = tempfile.mkstemp(
        prefix=".caption-shard.", suffix=".mov", dir=directory)
    os.close(descriptor)
    os.remove(staged)
    ass_path = _local_ass(compilation, cue, styles, directory)
    frames = cue["endFrameExclusive"] - cue["startFrame"]
    try:
        process = subprocess.run(
            _render_command(ass_path, compilation, frames, staged),
            capture_output=True, text=True)
        if process.returncode or not os.path.isfile(staged):
            raise RuntimeError(
                "caption alpha shard render failed: " + process.stderr[-500:])
        proof = prove_caption_shard_media(staged, compilation, frames)
        os.replace(staged, path)
        return proof
    finally:
        _remove_render_paths((ass_path, staged))


def _receipt_payload(media_key: str, cue: dict, compilation: dict,
                     proof: dict) -> dict:
    return {
        "schemaVersion": 1, "kind": "caption-alpha-shard-authority",
        "mediaKey": media_key, "cueId": cue["cueId"],
        "placedShardKey": cue["placedShardKey"],
        "contentAssetKey": cue["contentAssetKey"],
        "startFrame": cue["startFrame"],
        "endFrameExclusive": cue["endFrameExclusive"],
        "fps": compilation["fps"], "destination": compilation["destination"],
        "rendererHash": proof["rendererHash"],
        "fontClosureHash": proof["fontClosureHash"],
        "proof": {key: value for key, value in proof.items()
                  if key not in {"rendererHash", "fontClosureHash"}},
    }


def _write_receipt(path: str, payload: dict, media_path: str) -> dict:
    payload = {
        **payload,
        "media": {
            "name": os.path.basename(media_path),
            "sha256": file_sha256(media_path),
        },
    }
    receipt = {
        **payload,
        "authorityHash": canonical_digest(
            "sniper-caption-alpha-shard-authority-v1", payload),
    }
    write_json_atomic(path, receipt, indent=2)
    return receipt


def _load_current(media_path: str, receipt_path: str,
                  expected: dict) -> dict | None:
    try:
        with open(receipt_path, encoding="utf-8") as handle:
            receipt = json.load(handle)
        payload = {key: value for key, value in receipt.items()
                   if key != "authorityHash"}
        current = receipt.get("authorityHash") == canonical_digest(
            "sniper-caption-alpha-shard-authority-v1", payload)
        current = current and all(
            receipt.get(key) == value for key, value in expected.items())
        current = current and receipt.get("media") == {
            "name": os.path.basename(media_path),
            "sha256": file_sha256(media_path),
        }
    except (OSError, ValueError, json.JSONDecodeError, AttributeError):
        return None
    return receipt if current else None


def _entry(receipt: dict) -> dict:
    return {
        key: receipt[key] for key in (
            "cueId", "mediaKey", "placedShardKey", "contentAssetKey",
            "startFrame", "endFrameExclusive", "fps", "destination", "media",
            "rendererHash", "fontClosureHash", "proof",
        )
    }


def _cue_render_contexts(compilation: dict,
                         styles: dict) -> tuple[list[dict], dict]:
    resolver = CaptionFontResolver.create()
    tools = _render_tools()
    rows = []
    for cue in compilation.get("cues") or []:
        local = {**compilation, "cues": [cue]}
        closure = resolver.resolve(local, styles)
        rows.append({
            "cue": cue, "fontClosure": closure,
            "rendererHash": _renderer_hash(closure, tools),
        })
    return rows, merge_caption_font_closures([
        row["fontClosure"] for row in rows])


def _materialize_one(context: dict, compilation: dict,
                     styles: dict, out_dir: str) -> tuple[dict, bool]:
    cue = context["cue"]
    renderer_hash = context["rendererHash"]
    media_key = _media_key(cue, renderer_hash)
    media_path, receipt_path = _asset_paths(out_dir, media_key)
    expected = {
        "mediaKey": media_key, "cueId": cue["cueId"],
        "placedShardKey": cue["placedShardKey"],
        "contentAssetKey": cue["contentAssetKey"],
        "startFrame": cue["startFrame"],
        "endFrameExclusive": cue["endFrameExclusive"],
        "fps": compilation["fps"],
        "destination": compilation["destination"],
        "rendererHash": renderer_hash,
        "fontClosureHash": context["fontClosure"]["authorityHash"],
    }
    receipt = _load_current(media_path, receipt_path, expected)
    rendered = receipt is None
    if rendered:
        proof = {
            **_render_media(media_path, compilation, cue, styles),
            "rendererHash": renderer_hash,
            "fontClosureHash": context["fontClosure"]["authorityHash"],
        }
        receipt = _write_receipt(
            receipt_path,
            _receipt_payload(media_key, cue, compilation, proof),
            media_path)
    else:
        prove_caption_shard_media(
            media_path, compilation,
            cue["endFrameExclusive"] - cue["startFrame"])
    return _entry(receipt), rendered


def materialize_caption_shards(plan: dict, compilation: dict,
                               out_dir: str) -> CaptionShardSet:
    """Render or reuse every independently bounded cue alpha asset."""
    os.makedirs(out_dir, exist_ok=True)
    styles = caption_styles(plan, plan["captionsTrack"])
    contexts, font_closure = _cue_render_contexts(compilation, styles)
    entries, hits, rendered = [], 0, 0
    for context in contexts:
        entry, was_rendered = _materialize_one(
            context, compilation, styles, out_dir)
        entries.append(entry)
        if was_rendered:
            rendered += 1
        else:
            hits += 1
    payload = {
        "schemaVersion": 1, "kind": "caption-alpha-shard-manifest",
        "fps": compilation["fps"], "destination": compilation["destination"],
        "rendererHash": canonical_digest(
            "sniper-caption-alpha-renderer-set-v1",
            [row["rendererHash"] for row in entries]),
        "fontClosure": font_closure,
        "entries": entries,
    }
    manifest = {
        **payload, "authorityHash": canonical_digest(
            "sniper-caption-alpha-shard-manifest-v1", payload),
    }
    return CaptionShardSet(manifest, hits, rendered)
