"""Join selected presenter metadata to a caller's already verified source set.

This pure adapter does not read files, rehash snapshots, decode media, establish
rights or grant execution. The owner must retain the original plan, manifest,
source-set authority and work clock. Canvas/geometry remain declarations until
the separate picture and selected-asset observers establish media eligibility.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import ClassVar

from graphics.presenter_layout_contract import (
    PresenterCanvas, PresenterGeometry, closed, integer, presenter_identifier,
)
from graphics.presenter_layout_geometry import compile_presenter_geometry

_WINDOW_KEYS = frozenset({"operationIndex", "startFrame", "endFrameExclusive", "layout"})
_ENTRY_KEYS = frozenset({"lane", "mediaKind", "originalPath", "snapshotPath", "sha256",
                         "sizeBytes", "admissionReceiptPath", "admissionReceiptSha256"})
_MAX_SAFE_INTEGER = 9_007_199_254_740_991
PRESENTER_ASSET_SCOPE = "selected-presentation-metadata-not-media-rights-or-quality-approval"


@dataclass(frozen=True)
class PresenterAssetAdmission:
    """Immutable matched metadata, not independently acquired receipt authority."""
    asset_id: str
    lane: str
    media_kind: str
    original_path: str
    snapshot_path: str
    source_sha256: str
    source_size_bytes: int
    receipt_path: str
    receipt_sha256: str


@dataclass(frozen=True)
class SelectedPresenterAsset:
    """One original operation occurrence; repeated assets are not coalesced."""
    operation_index: int
    geometry: PresenterGeometry
    admission: PresenterAssetAdmission
    scope: ClassVar[str] = PRESENTER_ASSET_SCOPE
    executable: ClassVar[bool] = False
    media_eligibility_verified: ClassVar[bool] = False
    rights_verified: ClassVar[bool] = False


def _sha(value: object) -> str:
    """Require canonical lowercase SHA256 metadata, without hashing any bytes."""
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("Presenter admission identity requires a canonical SHA256")
    return value


def _absolute(value: object) -> str:
    """Check POSIX path spelling only; never resolve or attest filesystem state."""
    if type(value) is not str or not 1 <= len(value) <= 4096:
        raise ValueError("Presenter asset path requires bounded absolute text")
    path = PurePosixPath(value)
    if (not value.startswith("/") or value.startswith("//") or str(path) != value
            or len(path.parts) < 2 or ".." in path.parts
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValueError("Presenter asset path must have exact canonical absolute spelling")
    return value


def _catalog(manifest: dict) -> dict[str, dict]:
    """Validate every bounded broll ID, but defer unselected media/reference fields."""
    if type(manifest) is not dict:
        raise ValueError("Presenter manifest must be an object")
    rows = manifest.get("broll", [])
    if type(rows) is not list or len(rows) > 128:
        raise ValueError("Presenter broll catalog requires at most 128 rows")
    catalog = {}
    for row in rows:
        if type(row) is not dict or presenter_identifier(row.get("id")) in catalog:
            raise ValueError("Presenter broll catalog has malformed or duplicate IDs")
        catalog[row["id"]] = row
    return catalog


def _windows(rows: object, canvas: PresenterCanvas) -> tuple[tuple[int, PresenterGeometry], ...]:
    """Keep chronological half-open windows and unique original proposal indices."""
    if type(rows) is not list or not 1 <= len(rows) <= 32:
        raise ValueError("Present presenterLayouts requires 1–32 windows")
    if type(canvas) is not PresenterCanvas:
        raise ValueError("Presenter selection requires the explicit canvas contract")
    canvas.__post_init__()
    result, indices, previous_end = [], set(), 0
    for raw in rows:
        row = closed(raw, _WINDOW_KEYS, "presenter window")
        index = integer(row["operationIndex"], "presenter operation index", 127)
        geometry = compile_presenter_geometry(row["layout"], canvas,
            (row["startFrame"], row["endFrameExclusive"]))
        if index in indices or geometry.timing.start_frame < previous_end:
            raise ValueError("Presenter windows require unique indices and chronological nonoverlap")
        indices.add(index)
        previous_end = geometry.timing.end_frame_exclusive
        result.append((index, geometry))
    return tuple(result)


def _entry_index(entries: list[dict]) -> dict[str, dict | None]:
    """Index supplied verified entries once; ambiguous selected originals fail later."""
    if type(entries) is not list:
        raise ValueError("Presenter requires already verified source-set entries")
    result = {}
    for row in entries:
        if type(row) is not dict or type(row.get("originalPath")) is not str:
            raise ValueError("Presenter source-set entry cannot be indexed by original path")
        original = row["originalPath"]
        result[original] = None if original in result else row
    return result


def _expected(row: dict) -> dict:
    """Project only selected admitted references, including the otherwise omitted size."""
    kind, size = row.get("kind"), row.get("sourceSizeBytes")
    if type(kind) is not str or kind not in ("image", "video"):
        raise ValueError("Presenter selected broll kind must be image or video")
    if type(size) is not int or not 1 <= size <= _MAX_SAFE_INTEGER:
        raise ValueError("Presenter selected source size must be a positive canonical safe integer")
    source_sha, receipt_sha = _sha(row.get("sourceSha256")), _sha(row.get("admissionReceiptSha256"))
    original, snapshot = _absolute(row.get("originalPath")), _absolute(row.get("path"))
    expected_receipt = f".sniper-external-media/receipts/{receipt_sha}.json"
    path = PurePosixPath(snapshot)
    if path.parent.name != ".sniper-external-media" or path.name != f"{source_sha}.media":
        raise ValueError("Presenter snapshot path differs from the admitted source hash")
    if type(row.get("admissionReceiptPath")) is not str or row["admissionReceiptPath"] != expected_receipt:
        raise ValueError("Presenter admission receipt path must retain its exact relative binding")
    return {"mediaKind": "still-image" if kind == "image" else "timed-media",
            "originalPath": original, "snapshotPath": snapshot, "sha256": source_sha,
            "sizeBytes": size, "admissionReceiptPath": expected_receipt,
            "admissionReceiptSha256": receipt_sha}


def _admission(row: dict, entries: dict[str, dict | None]) -> PresenterAssetAdmission:
    """Match all eight closed fields; source/broll admission cannot become music."""
    expected = _expected(row)
    actual = closed(entries.get(expected["originalPath"]), _ENTRY_KEYS, "selected presenter admission")
    lane = actual["lane"]
    if type(lane) is not str or lane not in ("source", "broll"):
        raise ValueError("Presenter selected admission must be source or broll, never music")
    expected["lane"] = lane
    if any(type(actual[key]) is not type(value) or actual[key] != value for key, value in expected.items()):
        raise ValueError("Presenter selection differs from the verified lane/kind/path/bytes/receipt")
    return PresenterAssetAdmission(row["id"], lane, actual["mediaKind"], actual["originalPath"],
        actual["snapshotPath"], actual["sha256"], actual["sizeBytes"],
        actual["admissionReceiptPath"], actual["admissionReceiptSha256"])


def select_presenter_assets(plan: dict, manifest: dict, verified_entries: list[dict],
                            canvas: PresenterCanvas) -> tuple[SelectedPresenterAsset, ...]:
    """Join selected V8 occurrences without rediscovering source-set authority.

    An absent field is a legacy no-op; an explicitly empty/null field is invalid.
    This is not a V8 proposal/evidence validator or a media-eligibility receipt.
    The owner must independently rederive the selected track from the held V8
    request and retain that authority before using these immutable metadata rows.
    """
    if type(plan) is not dict:
        raise ValueError("Presenter plan must be an object")
    if "presenterLayouts" not in plan:
        return ()
    catalog, windows = _catalog(manifest), _windows(plan["presenterLayouts"], canvas)
    entries, selected = _entry_index(verified_entries), []
    for index, geometry in windows:
        asset_id = geometry.declaration.asset_id
        if asset_id not in catalog:
            raise ValueError("Presenter assetId is absent from the exact broll catalog")
        selected.append(SelectedPresenterAsset(index, geometry, _admission(catalog[asset_id], entries)))
    return tuple(selected)
