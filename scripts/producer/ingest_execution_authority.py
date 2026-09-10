"""Bind executable manifest media and music selections to ingest authority."""
from __future__ import annotations

import os
from pathlib import Path

from ingest_admission_contract import (
    STORE_NAME,
    verify_manifest_source_set_if_present,
)
from ingest_media_observation import SourceVerificationCapture

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUILTIN_MUSIC_ROOT = PROJECT_ROOT / "assets" / "music"


def _absolute(value: object) -> str | None:
    if type(value) is not str or not os.path.isabs(value):
        return None
    return os.path.abspath(value)


def _inside(path: str, root: Path) -> bool:
    try:
        resolved_root = root.resolve(strict=True)
        resolved_path = Path(path).resolve(strict=True)
        return (resolved_path == Path(path)
                and os.path.commonpath(
                    [str(resolved_path), str(resolved_root)])
                == str(resolved_root))
    except (OSError, ValueError):
        return False


def _entry_by_original(entries: list[dict]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for entry in entries:
        original = entry["originalPath"]
        if original in result:
            raise RuntimeError("source-set repeats an original ingress path")
        result[original] = entry
    return result


def _verify_admitted_row(
    row: object,
    lanes: set[str],
    entries: dict[str, dict],
    label: str,
) -> str:
    if type(row) is not dict:
        raise RuntimeError(f"{label} manifest row is malformed")
    original = _absolute(row.get("originalPath"))
    path = _absolute(row.get("path"))
    if original is None or path is None:
        raise RuntimeError(f"{label} manifest row lacks admitted path authority")
    entry = entries.get(original)
    if entry is None or entry["lane"] not in lanes:
        raise RuntimeError(f"{label} manifest row is absent from its source set")
    expected = {
        "path": entry["snapshotPath"],
        "sourceSha256": entry["sha256"],
        "admissionReceiptPath": entry["admissionReceiptPath"],
        "admissionReceiptSha256": entry["admissionReceiptSha256"],
    }
    if any(row.get(key) != value for key, value in expected.items()):
        raise RuntimeError(f"{label} manifest row disagrees with admission authority")
    return path


def _verify_builtin_music(row: object) -> str:
    if type(row) is not dict or row.get("source") != "builtin":
        raise RuntimeError("music manifest row lacks admitted or trusted authority")
    path = _absolute(row.get("path"))
    if path is None or not _inside(path, BUILTIN_MUSIC_ROOT):
        raise RuntimeError("builtin music escaped the trusted project library")
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise RuntimeError("builtin music is not a regular project asset")
    return path


def _record_asset_id(row: dict, seen: set[str], label: str) -> str:
    asset_id = row.get("id")
    if type(asset_id) is not str or not asset_id:
        raise RuntimeError(f"{label} has no stable asset id")
    if asset_id in seen:
        raise RuntimeError(f"{label} repeats an asset id")
    seen.add(asset_id)
    return asset_id


def _record_projection(row: dict, seen: set[str], label: str) -> None:
    original = _absolute(row.get("originalPath"))
    if original is None:
        return
    if original in seen:
        raise RuntimeError(f"{label} repeats an admitted ingress projection")
    seen.add(original)


def _verify_manifest_projection(
    manifest: dict,
    entries: list[dict],
) -> dict[str, str]:
    authority = _entry_by_original(entries)
    accepted_music: dict[str, str] = {}
    projected: set[str] = set()
    source_ids: set[str] = set()
    broll_ids: set[str] = set()
    music_ids: set[str] = set()
    for index, row in enumerate(manifest.get("sources") or []):
        label = f"sources[{index}]"
        _verify_admitted_row(row, {"source"}, authority, label)
        _record_asset_id(row, source_ids, label)
        _record_projection(row, projected, label)
    for index, row in enumerate(manifest.get("broll") or []):
        label = f"broll[{index}]"
        _verify_admitted_row(
            row, {"source", "broll"}, authority, label)
        _record_asset_id(row, broll_ids, label)
        _record_projection(row, projected, label)
    for index, row in enumerate(manifest.get("music") or []):
        if type(row) is not dict:
            raise RuntimeError(f"music[{index}] manifest row is malformed")
        label = f"music[{index}]"
        if row.get("originalPath") is not None:
            path = _verify_admitted_row(
                row, {"music"}, authority, label)
            _record_projection(row, projected, label)
        else:
            path = _verify_builtin_music(row)
        asset_id = _record_asset_id(row, music_ids, label)
        accepted_music[asset_id] = path
    return accepted_music


def _verify_music_selection(plan: dict, accepted: dict[str, str]) -> None:
    music = plan.get("music")
    if type(music) is not dict or not music.get("enabled"):
        return
    asset_id, raw_path = music.get("assetId"), music.get("path")
    direct = _absolute(raw_path)
    if raw_path is not None and direct is None:
        raise RuntimeError("music.path must be an absolute admitted asset")
    if asset_id is not None:
        if type(asset_id) is not str or asset_id not in accepted:
            raise RuntimeError("selected music asset is absent from admitted manifest")
        if direct is not None and direct != accepted[asset_id]:
            raise RuntimeError("music path and asset id resolve to different bytes")
        return
    if direct is None or direct not in accepted.values():
        raise RuntimeError(
            "direct music.path must resolve to an admitted manifest asset")


def execution_media_authority_entries(
    plan: dict,
    manifest: dict,
    manifest_path: str,
    capture: SourceVerificationCapture | None = None,
) -> list[dict] | None:
    """Return verified entries after checking every executable projection."""
    if capture is None:
        return _execution_entries(plan, manifest, manifest_path, None)
    try:
        return _execution_entries(plan, manifest, manifest_path, capture)
    except BaseException:
        capture.abort()
        raise


def _execution_entries(plan: dict, manifest: dict, manifest_path: str,
                        capture: SourceVerificationCapture | None) -> list[dict] | None:
    """Keep the original admission/projection path, with optional same-pass capture."""
    if type(plan) is not dict or type(manifest) is not dict:
        raise RuntimeError("plan and manifest media authority must be JSON objects")
    entries = verify_manifest_source_set_if_present(manifest, manifest_path) if capture is None \
        else verify_manifest_source_set_if_present(manifest, manifest_path, capture)
    if entries is None:
        return None
    manifest_dir = Path(os.path.abspath(manifest_path)).parent
    accepted_music = _verify_manifest_projection(manifest, entries)
    _verify_music_selection(plan, accepted_music)
    store = manifest_dir / STORE_NAME
    if not store.is_dir() or store.is_symlink():
        raise RuntimeError("external-media snapshot store is unavailable")
    return entries


def verify_execution_media_authority(
    plan: dict,
    manifest: dict,
    manifest_path: str,
) -> bool:
    """Reverify source bytes and reject executable paths outside their receipt."""
    return execution_media_authority_entries(
        plan, manifest, manifest_path) is not None
