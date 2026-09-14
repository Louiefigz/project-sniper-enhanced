"""Rescan supporting media while preserving exact, verified source transcripts."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from headless.safe_source_files import read_stable_owned_file
from ingest_execution_authority import execution_media_authority_entries
from ingest_retained_inventory import RetainedIngest, retained_primary_files
from transcript_source_authority import verify_result
from transcript_timing_quality import require_timing_quality

SOURCE_FIELDS = (
    "id", "path", "originalPath", "sourceSha256", "sourceSizeBytes", "duration",
    "fps", "frameRate", "vfr", "resolution", "rotation", "audio", "contentHash",
    "role",
)


@dataclass(frozen=True)
class RetainedTranscript:
    """Exact prior source and transcript bytes; no generated replacement."""

    source: dict
    path: Path
    payload: bytes


def _object(payload: bytes, label: str) -> dict:
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} must be a JSON object")
    return value


def _sources(manifest: dict) -> list[dict]:
    rows = manifest.get("sources")
    if not isinstance(rows, list) or not 0 < len(rows) <= 64:
        raise RuntimeError("Transcript reuse requires existing primary sources")
    if any(not isinstance(row, dict) for row in rows):
        raise RuntimeError("Transcript reuse source row is malformed")
    ids = [row.get("id") for row in rows]
    if any(not isinstance(value, str) for value in ids) or len(set(ids)) != len(ids):
        raise RuntimeError("Transcript reuse source IDs must be unique")
    return rows


def _retained(row: dict, directory: Path) -> RetainedTranscript:
    name = row.get("transcriptPath")
    if not isinstance(name, str) or not name:
        raise RuntimeError("Analyze missing speech before rescanning with transcript reuse")
    file = directory / name
    if file.resolve() != file.absolute() or not file.is_relative_to(directory):
        raise RuntimeError("Reused transcript must remain inside its canonical source directory")
    payload = read_stable_owned_file(str(file), "retained transcript")
    result = _object(payload, "retained transcript")
    error = verify_result(result, row, str(file))
    if error:
        raise RuntimeError(f"Cannot reuse transcript: {error}")
    require_timing_quality(result)
    return RetainedTranscript(dict(row), file, payload)


def _restore(rows: list[dict], retained: list[RetainedTranscript]) -> None:
    if len(rows) != len(retained):
        raise RuntimeError("Rescan changed primary sources; prepare a new source edit")
    for row, saved in zip(rows, retained):
        if any(row.get(key) != saved.source.get(key) for key in SOURCE_FIELDS):
            raise RuntimeError("Rescan changed source identity, order or timing; transcript reuse refused")
        if read_stable_owned_file(str(saved.path), "retained transcript") != saved.payload:
            raise RuntimeError("Transcript changed during supporting-media rescan")
        error = verify_result(_object(saved.payload, "transcript"), row, str(saved.path))
        if error:
            raise RuntimeError(f"Rescanned source cannot reuse transcript: {error}")
        row["transcriptPath"] = saved.source["transcriptPath"]


def rescan_with_transcripts(
    input_path: Path,
    manifest_path: Path,
    build: Callable[[Path, Path, bool, RetainedIngest], dict],
) -> dict:
    """Re-admit media locally; publish nothing if prior source/transcript state drifts.

    Args:
        input_path: Existing source folder being rescanned.
        manifest_path: Existing admitted manifest that the caller may replace.
        build: Shared ingest builder; ASR disabled and prior primary ingress retained.

    Returns:
        Newly admitted manifest retaining the unchanged transcript paths.
    """
    directory = manifest_path.parent
    if directory.resolve() != directory or input_path.resolve() != directory:
        raise RuntimeError("Transcript-preserving rescan requires the existing canonical source folder")
    before = read_stable_owned_file(str(manifest_path), "prior ingest manifest")
    previous = _object(before, "prior ingest manifest")
    entries = execution_media_authority_entries({}, previous, str(manifest_path))
    if entries is None:
        raise RuntimeError("Transcript reuse requires admitted source-set authority")
    retained = [_retained(row, directory) for row in _sources(previous)]
    inventory = RetainedIngest(previous, entries)
    retained_primary_files(inventory)  # Reject missing ingress before invoking the builder.
    current = build(input_path, directory, True, inventory)
    if execution_media_authority_entries({}, current, str(manifest_path)) is None:
        raise RuntimeError("Rescanned media lost source-set admission")
    _restore(_sources(current), retained)
    if read_stable_owned_file(str(manifest_path), "prior ingest manifest") != before:
        raise RuntimeError("Manifest changed during supporting-media rescan")
    return current
