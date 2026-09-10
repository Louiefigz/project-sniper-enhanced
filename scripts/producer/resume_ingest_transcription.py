#!/usr/bin/env python3
"""Retry transcription from an already admitted Producer manifest."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from ingest import (
    PROJECT_ROOT,
    TranscribeCtx,
    _python_interpreter,
    _transcribe_source,
    load_deepgram_key,
)
from ingest_execution_authority import verify_execution_media_authority
from ingest_probe import status
from ingest_scan import atomic_write_json
from local_whisper import DEEPGRAM_PROVIDER, LOCAL_PROVIDER, transcription_provider
from asr_policy import add_asr_arguments, invocation_from_options, use_asr_invocation
from transcript_source_authority import verify_result
from transcript_timing_quality import timing_quality_report

MAX_MANIFEST_BYTES = 64 * 1024 * 1024


def _manifest(path: Path) -> dict:
    absolute = Path(os.path.abspath(path))
    if absolute.is_symlink() or not absolute.is_file():
        raise RuntimeError("ingest manifest must be a regular non-symlink file")
    if not 0 < absolute.stat().st_size <= MAX_MANIFEST_BYTES:
        raise RuntimeError("ingest manifest exceeds its read bound")
    try:
        value = json.loads(absolute.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"ingest manifest is unreadable: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("ingest manifest must contain one JSON object")
    return value


def _source_authority(manifest: dict) -> dict[str, tuple[str, int]]:
    result = {}
    for row in manifest.get("sources") or []:
        path, digest = row.get("path"), row.get("sourceSha256")
        size = row.get("sourceSizeBytes")
        if size is None and isinstance(path, str) and Path(path).is_file():
            size = Path(path).stat().st_size
        if not isinstance(path, str):
            raise RuntimeError("manifest source path is missing")
        result[str(Path(path).absolute())] = (digest, size)
    return result


def _context(manifest_dir: Path, manifest: dict) -> TranscribeCtx:
    provider = transcription_provider()
    key = load_deepgram_key(PROJECT_ROOT) if provider == DEEPGRAM_PROVIDER else None
    if provider not in {DEEPGRAM_PROVIDER, LOCAL_PROVIDER}:
        raise RuntimeError("transcription provider is unsupported")
    if provider == DEEPGRAM_PROVIDER and key is None:
        raise RuntimeError("Deepgram retry requires DEEPGRAM_API_KEY")
    return TranscribeCtx(
        True, key, manifest_dir, _python_interpreter(),
        _source_authority(manifest))


def _has_current_authority(
    row: dict,
    transcript_path: Path,
) -> bool:
    if row.get("sourceSha256") is None:
        return True
    if transcript_path.is_symlink() or not transcript_path.is_file():
        return False
    if not 0 < transcript_path.stat().st_size <= MAX_MANIFEST_BYTES:
        return False
    try:
        payload = json.loads(transcript_path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    authority_ok = verify_result(payload, row, str(transcript_path)) is None
    return authority_ok and timing_quality_report(payload)["status"] == "pass"


def _pending_sources(manifest: dict, manifest_dir: Path) -> list[dict]:
    rows = manifest.get("sources")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("ingest manifest has no source rows")
    pending = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise RuntimeError(f"sources[{index}] is malformed")
        expected = f"{row['id']}.transcript.json"
        transcript = row.get("transcriptPath")
        if transcript is None:
            pending.append(row)
        elif transcript != expected:
            raise RuntimeError(
                f"sources[{index}] has stale transcript authority")
        elif not _has_current_authority(row, manifest_dir / expected):
            pending.append(row)
    return pending


def resume(manifest_path: Path) -> dict:
    """Reverify admission, transcribe only missing rows, and persist each result."""
    path = Path(os.path.abspath(manifest_path))
    manifest = _manifest(path)
    if verify_execution_media_authority({}, manifest, str(path)) is not True:
        raise RuntimeError(
            "transcription retry requires admitted source-set authority")
    pending = _pending_sources(manifest, path.parent)
    context = _context(path.parent, manifest)
    completed = []
    for row in pending:
        source = row.get("path")
        if not isinstance(source, str):
            raise RuntimeError(f"{row['id']} has no admitted media path")
        transcript = _transcribe_source(Path(source), row["id"], context)
        if transcript is None:
            raise RuntimeError(f"transcription retry failed for {row['id']}")
        row["transcriptPath"] = transcript
        atomic_write_json(path, manifest)
        completed.append(row["id"])
    result = {
        "status": "done", "manifest": str(path),
        "transcribed": completed, "alreadyComplete": len(pending) == 0,
    }
    status(**result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Retry transcription without repeating media admission")
    parser.add_argument("manifest_path")
    add_asr_arguments(parser)
    args = parser.parse_args()
    try:
        with use_asr_invocation(invocation_from_options(args)):
            resume(Path(args.manifest_path))
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
