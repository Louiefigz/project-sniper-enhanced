"""Additive rescans retain verified primary, reclassified and external media."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ingest_admission import AdmittedMedia, IngressCandidate
from ingest_admitted_scan import _proof_fields


@dataclass(frozen=True)
class RetainedIngest:
    """Prior manifest plus source-set entries already verified by the rescan owner."""

    manifest: dict
    entries: list[dict]


def retained_primary_files(retained: RetainedIngest) -> list[Path]:
    """Keep primary ingress order, including recordings referenced in place."""
    files = []
    for row in retained.manifest["sources"]:
        original = row.get("originalPath")
        if not isinstance(original, str) or not Path(original).is_absolute():
            raise RuntimeError("Transcript-preserving rescan needs original source ingress paths")
        files.append(Path(original))
    return files


def include_retained_ingress(
    candidates: list[IngressCandidate], retained: RetainedIngest | None,
) -> list[IngressCandidate]:
    """Re-admit old non-primary inputs too; never silently drop a missing file."""
    if retained is None:
        return candidates
    current = {str(row.original_path): row.lane for row in candidates}
    result = list(candidates)
    for entry in retained.entries:
        original, lane = entry["originalPath"], entry["lane"]
        if original in current and current[original] != lane:
            raise RuntimeError("Rescan changed an existing media ingress lane")
        if original not in current:
            result.append(IngressCandidate(Path(original), lane))
    return result


def _asset_key(row: dict) -> str:
    return row.get("originalPath") or row["path"]


def _retained_row(row: dict, mapping: dict[str, AdmittedMedia]) -> dict:
    original = row.get("originalPath")
    if original is None:
        return dict(row)  # Existing trusted builtin music was verified before rescan.
    media = mapping.get(original)
    if media is None or media.sha256 != row.get("sourceSha256"):
        raise RuntimeError("Existing supporting media changed or lost admission during rescan")
    return {**row, "path": media.snapshot_path, **_proof_fields(media)}


def merge_retained_lane(
    current: list[dict], previous: list[dict],
    mapping: dict[str, AdmittedMedia], prefix: str,
) -> list[dict]:
    """Keep prior media/IDs and append new rows with noncolliding identities."""
    rows = [_retained_row(row, mapping) for row in previous]
    seen = {_asset_key(row) for row in rows}
    used = {row["id"] for row in rows}
    next_id = 1
    for row in current:
        key = _asset_key(row)
        if key in seen:
            continue
        while f"{prefix}-{next_id}" in used:
            next_id += 1
        value = {**row, "id": f"{prefix}-{next_id}"}
        rows.append(value)
        seen.add(key)
        used.add(value["id"])
    return rows
