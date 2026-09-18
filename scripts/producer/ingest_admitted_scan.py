"""B-roll and music cataloging over sandbox-admitted immutable snapshots."""
from __future__ import annotations

from pathlib import Path

from ingest_admission import AdmittedMedia
from ingest_probe import AUDIO_EXTS, MEDIA_EXTS, probe_media, reject_unsupported_ingest_media, status
from ingest_scan import (
    BROLL_CATALOG_NAME,
    _category_tag,
    _load_broll_cache,
    _vibe_tags,
    _write_broll_cache,
    broll_fields,
)

_VISION_FIELDS = (
    "hasBurnedText", "description", "descriptionSource",
    "frames", "tags", "cataloged", "id",
)


def _admitted(path: Path, mapping: dict[str, AdmittedMedia]) -> AdmittedMedia:
    key = str(Path(path).absolute())
    try:
        return mapping[key]
    except KeyError as exc:
        raise RuntimeError(f"external media was not sandbox-admitted: {path}") from exc


def _proof_fields(media: AdmittedMedia) -> dict:
    return {
        "originalPath": media.original_path,
        "sourceSha256": media.sha256,
        "sourceSizeBytes": media.size_bytes,
        "admissionReceiptPath": media.receipt_path,
        "admissionReceiptSha256": media.receipt_sha256,
    }


def _broll_paths(broll_dir: Path) -> list[Path]:
    return sorted(
        path for path in broll_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in MEDIA_EXTS
        and not any(part.startswith(".")
                    for part in path.relative_to(broll_dir).parts))


def _catalog_row(
    original: Path,
    broll_dir: Path,
    media: AdmittedMedia,
    cached: dict | None,
) -> tuple[dict, dict]:
    reject_unsupported_ingest_media(original, media.media_kind)
    reject_unsupported_ingest_media(media.snapshot_path, media.media_kind)
    probe = probe_media(media.snapshot_path)
    manifest = broll_fields(original, probe, _category_tag(original, broll_dir))
    vision = cached or {}
    manifest.update({
        key: vision[key] for key in _VISION_FIELDS if key in vision
    })
    cache = {
        **manifest,
        "path": str(original),
        "snapshotPath": media.snapshot_path,
        **_proof_fields(media),
        "mtime": original.stat().st_mtime,
    }
    manifest.update(path=media.snapshot_path, **_proof_fields(media))
    return manifest, cache


def catalog_admitted_broll(
    broll_dir: Path | None,
    extra: list[dict],
    mapping: dict[str, AdmittedMedia],
) -> list[dict]:
    """Build b-roll manifest rows whose executable path is the snapshot."""
    fields = list(extra)
    for row in fields:
        reject_unsupported_ingest_media(row.get("originalPath", row["path"]))
        reject_unsupported_ingest_media(row["path"])
    if broll_dir and broll_dir.is_dir():
        cache_path = broll_dir / BROLL_CATALOG_NAME
        cached = _load_broll_cache(cache_path)
        cache_rows = []
        for original in _broll_paths(broll_dir):
            media = _admitted(original, mapping)
            row, cache = _catalog_row(
                original, broll_dir, media, cached.get(str(original)))
            fields.append(row)
            cache_rows.append(cache)
            status(status="broll_admitted", path=str(original),
                   snapshot=media.snapshot_path)
        _write_broll_cache(cache_path, cache_rows)
    fields.sort(key=lambda row: row.get("originalPath", row["path"]))
    return [{"id": f"broll-{index}", **row}
            for index, row in enumerate(fields, start=1)]


def scan_admitted_music(
    music_dir: Path | None,
    mapping: dict[str, AdmittedMedia],
) -> list[dict]:
    """Catalog project music only after sandbox full-decode admission."""
    if not music_dir or not music_dir.is_dir():
        return []
    originals = sorted(
        path for path in music_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in AUDIO_EXTS)
    entries = []
    for original in originals:
        media = _admitted(original, mapping)
        probe = probe_media(media.snapshot_path)
        if not probe.audio_present:
            raise RuntimeError(f"admitted music has no audio stream: {original}")
        entry = {
            "id": f"music-{len(entries) + 1}",
            "path": media.snapshot_path,
            "duration": probe.duration,
            "vibe": _vibe_tags(original, music_dir),
            "bpm": None,
            "licensed": None,
            "source": "library",
            **_proof_fields(media),
        }
        entries.append(entry)
        status(status="music_admitted", id=entry["id"], path=str(original))
    return entries
