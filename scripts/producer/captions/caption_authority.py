#!/usr/bin/env python3
"""Persist and verify render-consumed CaptionTrackV1 projection artifacts."""
from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass

from captions.caption_ass_projection import build_compiled_ass
from captions.caption_fingerprints import (
    canonical_digest,
    caption_compiler_hash,
    caption_track_hash,
    correction_ledger_hash,
)
from captions.caption_outputs import (
    PalmierCaptionCapabilities,
    assert_srt_burned_parity,
    build_semantic_chapters,
    build_srt,
    project_captions_to_palmier,
)
from captions.caption_plan_pipeline import (
    PROJECTION_TOOLCHAIN,
    caption_styles,
    validate_plan_caption_authority,
)
from captions.caption_shard_contract import validate_caption_shard_manifest
from fingerprints import file_sha256, write_json_atomic
from edit_scope import caption_burn_enabled
from producer_config import ENCODE

AUTHORITY_NAME = "caption_authority.json"
COMPILATION_NAME = "caption_compilation.json"
ASS_NAME = "captions.ass"
SRT_NAME = "captions.srt"
PALMIER_NAME = "caption_palmier.json"
CHAPTERS_JSON_NAME = "caption_chapters.json"
CHAPTERS_TEXT_NAME = "chapters.txt"
SHARDS_NAME = "caption_shards.json"


@dataclass(frozen=True)
class CaptionArtifactSet:
    """Paths and immutable receipt for one projected caption generation."""

    compilation: str
    ass: str
    srt: str
    palmier: str
    authority: str
    receipt: dict
    chapters_json: str | None = None
    chapters_text: str | None = None
    shards: str | None = None


def _text_atomic(path: str, value: str) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    descriptor, staged = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, path)
    finally:
        if os.path.exists(staged):
            os.remove(staged)


def _paths(out_dir: str) -> dict[str, str]:
    return {
        "compilation": os.path.join(out_dir, COMPILATION_NAME),
        "ass": os.path.join(out_dir, ASS_NAME),
        "srt": os.path.join(out_dir, SRT_NAME),
        "palmier": os.path.join(out_dir, PALMIER_NAME),
        "chaptersJson": os.path.join(out_dir, CHAPTERS_JSON_NAME),
        "chaptersText": os.path.join(out_dir, CHAPTERS_TEXT_NAME),
        "shards": os.path.join(out_dir, SHARDS_NAME),
        "authority": os.path.join(out_dir, AUTHORITY_NAME),
    }


def _receipt(plan: dict, compilation: dict, paths: dict[str, str],
             options: dict) -> dict:
    authority = validate_plan_caption_authority(plan)
    if authority is None:
        raise ValueError("explicit caption authority disappeared")
    track, ledger = authority
    names = ["compilation", "ass", "srt", "palmier"]
    if isinstance(compilation.get("chapterProjection"), dict):
        names.extend(("chaptersJson", "chaptersText"))
    shards = options.get("shards")
    if isinstance(shards, dict):
        names.append("shards")
    files = {
        name: {"name": os.path.basename(paths[name]),
               "sha256": file_sha256(paths[name])}
        for name in names
    }
    for row in (shards or {}).get("entries") or []:
        files[f"shard:{row['cueId']}"] = dict(row["media"])
    payload = {
        "schemaVersion": 1, "kind": "caption-render-authority",
        "captionTrackHash": caption_track_hash(track),
        "correctionLedgerHash": correction_ledger_hash(ledger),
        "compilationHash": canonical_digest(
            "sniper-caption-compilation-v1", compilation),
        "timelineMapHash": compilation["timelineMapHash"],
        "compilerHash": compilation["compilerHash"],
        "destination": compilation["destination"],
        "coverage": compilation["coverage"],
        "cueFingerprints": {
            row["cueId"]: row["captionCueFingerprint"]
            for row in compilation["cues"]
        },
        "burnExpected": options["burn"], "files": files,
    }
    if isinstance(shards, dict):
        payload["alphaShardManifestHash"] = shards["authorityHash"]
    chapters = compilation.get("chapterProjection")
    if isinstance(chapters, dict):
        chapter_hash = canonical_digest(
            "sniper-caption-bound-chapters-v1", {
                "fps": chapters.get("fps"),
                "chapters": chapters.get("chapters"),
            })
        if chapters.get("digest") != chapter_hash:
            raise ValueError("caption chapter projection digest is stale")
        payload["chapterProjectionHash"] = chapter_hash
    return {**payload, "authorityHash": canonical_digest(
        "sniper-caption-render-authority-v1", payload)}


def _bind_alpha_media(palmier: dict, shards: dict, out_dir: str) -> dict:
    if palmier.get("kind") != "regenerable-alpha-captions":
        return palmier
    by_cue = {row["cueId"]: row for row in shards["entries"]}
    if set(by_cue) != {
            row.get("elementId") for row in palmier.get("entries") or []}:
        raise ValueError("Palmier caption bindings do not match alpha shards")
    entries = []
    for row in palmier["entries"]:
        media = by_cue[row["elementId"]]
        entries.append({
            **row, "mediaKey": media["mediaKey"],
            "mediaPath": os.path.abspath(
                os.path.join(out_dir, media["media"]["name"])),
            "mediaSha256": media["media"]["sha256"],
            "alphaMode": "straight",
        })
    return {**palmier, "entries": entries}


def _validate_shards(shards: object, compilation: dict,
                     out_dir: str) -> dict | None:
    if shards is None:
        return None
    shards = validate_caption_shard_manifest(shards, out_dir)
    entries = shards.get("entries")
    if not isinstance(entries, list) or {
            row.get("cueId") for row in entries} != {
            row.get("cueId") for row in compilation["cues"]}:
        raise ValueError("caption alpha shards do not cover compiled cues")
    return shards


def write_caption_artifacts(plan: dict, compilation: dict,
                            out_dir: str,
                            shards: dict | None = None) -> CaptionArtifactSet:
    """Write ASS/SRT/Palmier from one compiler and bind every byte in a receipt."""
    os.makedirs(out_dir, exist_ok=True)
    paths = _paths(out_dir)
    authority = validate_plan_caption_authority(plan)
    if authority is None:
        raise ValueError("caption artifacts require CaptionTrackV1")
    track, _ = authority
    styles = caption_styles(plan, track)
    if compilation.get("compilerHash") != caption_compiler_hash(
            PROJECTION_TOOLCHAIN):
        raise ValueError(
            "caption artifacts require the current render compiler closure")
    assert_srt_burned_parity(compilation)
    shards = _validate_shards(shards, compilation, out_dir)
    write_json_atomic(paths["compilation"], compilation, indent=2)
    _text_atomic(paths["ass"], build_compiled_ass(compilation, styles))
    _text_atomic(paths["srt"], build_srt(compilation))
    palmier = project_captions_to_palmier(
        compilation, PalmierCaptionCapabilities(False, False, False))
    if shards is not None:
        palmier = _bind_alpha_media(palmier, shards, out_dir)
        write_json_atomic(paths["shards"], shards, indent=2)
    write_json_atomic(paths["palmier"], palmier, indent=2)
    chapters = compilation.get("chapterProjection")
    if isinstance(chapters, dict):
        write_json_atomic(paths["chaptersJson"], chapters, indent=2)
        _text_atomic(paths["chaptersText"], build_semantic_chapters(chapters))
    burn = caption_burn_enabled(plan)
    receipt = _receipt(plan, compilation, paths, {
        "burn": burn, "shards": shards,
    })
    write_json_atomic(paths["authority"], receipt, indent=2)
    return CaptionArtifactSet(
        compilation=paths["compilation"], ass=paths["ass"], srt=paths["srt"],
        palmier=paths["palmier"], authority=paths["authority"],
        receipt=receipt,
        chapters_json=(paths["chaptersJson"]
                       if isinstance(chapters, dict) else None),
        chapters_text=(paths["chaptersText"]
                       if isinstance(chapters, dict) else None),
        shards=paths["shards"] if shards is not None else None)


def _video_options(fps: str) -> list[str]:
    return [
        "-c:v", ENCODE["vcodec"], "-crf", str(ENCODE["mezzanine_crf"]),
        "-preset", ENCODE["mezzanine_preset"], "-pix_fmt", "yuv420p",
        "-r", fps, "-fps_mode", "cfr", "-movflags", "+faststart",
    ]


def burn_caption_artifact(video_path: str, ass_path: str) -> None:
    """Burn a proved ASS projection without touching the mastered audio bus."""
    from audio.master import _subtitles_filter
    from media_probe import probe_video
    probe = probe_video(video_path)
    fps = str(probe.get("r_frame_rate") or "")
    if not fps or fps == "0/0":
        raise RuntimeError("caption burn cannot resolve exact video fps")
    directory = os.path.dirname(os.path.abspath(video_path))
    suffix = os.path.splitext(video_path)[1] or ".mp4"
    descriptor, staged = tempfile.mkstemp(
        prefix=".caption-burn.", suffix=suffix, dir=directory)
    os.close(descriptor)
    try:
        command = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", video_path, "-map", "0:v:0", "-map", "0:a?",
            "-vf", _subtitles_filter(ass_path),
            *_video_options(fps), "-c:a", "copy", staged,
        ]
        process = subprocess.run(command, capture_output=True, text=True)
        if process.returncode != 0 or not os.path.isfile(staged):
            raise RuntimeError(
                "caption burn failed: " + process.stderr.strip()[-500:])
        os.replace(staged, video_path)
    finally:
        if os.path.exists(staged):
            os.remove(staged)


def expected_caption_hashes(plan: dict) -> tuple[str, str] | None:
    """Return strict track/ledger hashes used by Audit B."""
    authority = validate_plan_caption_authority(plan)
    if authority is None:
        return None
    return caption_track_hash(authority[0]), correction_ledger_hash(authority[1])
