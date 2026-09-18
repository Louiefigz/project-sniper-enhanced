#!/usr/bin/env python3
"""Catalog Producer b-roll/music and atomically publish manifest artifacts.
Metadata is cached by path/mtime; music tags come from folders.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Callable, Optional

from ingest_probe import (
    AUDIO_EXTS,
    IMAGE_EXTS,
    MEDIA_EXTS,
    MediaProbe,
    probe_media,
    status,
    warn,
)

BROLL_CATALOG_NAME = "broll_catalog.json"
# Committed catalog paths are repo-relative; readers anchor them here.
_REPO_ROOT = Path(__file__).resolve().parents[2]


def atomic_write_json(destination: Path, value: object,
                      guard: Callable[[], None] | None = None) -> None:
    """Replace JSON in one rename so readers never observe a partial file."""
    if guard:
        guard()
    descriptor, staged = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if guard:
            guard()
        os.replace(staged, destination)
        directory = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            os.unlink(staged)
        except FileNotFoundError:
            pass


def _resolve_catalog_path(raw: str) -> Path:
    """Absolute catalog paths pass through; relative ones anchor at repo root."""
    path = Path(raw)
    return path if path.is_absolute() else _REPO_ROOT / path


def _relative_catalog_path(raw: str) -> str:
    """Repo-root-relative form for files inside the repo; others stay as-is."""
    path = Path(raw)
    if path.is_absolute() and path.is_relative_to(_REPO_ROOT):
        return str(path.relative_to(_REPO_ROOT))
    return raw


def _orientation(width: Optional[int], height: Optional[int]) -> Optional[str]:
    """landscape / portrait / square from width vs height (None if unknown)."""
    if not width or not height:
        return None
    if width > height:
        return "landscape"
    if height > width:
        return "portrait"
    return "square"


def _category_tag(path: Path, broll_dir: Path) -> Optional[str]:
    """Immediate sub-folder under ``broll/`` (coarse category); None if top-level."""
    parts = path.relative_to(broll_dir).parts
    return parts[0] if len(parts) > 1 else None


def broll_fields(path: Path, probe: MediaProbe, category: Optional[str]) -> dict:
    """Stable catalog fields for one b-roll asset (no id — assigned later).

    Args:
        path: Absolute path to the asset.
        probe: Its ``MediaProbe``.
        category: Folder-derived category tag, or None.

    Returns:
        A dict of manifest b-roll fields with vision entries left ``pending``.
    """
    is_image = path.suffix.lower() in IMAGE_EXTS
    # hasSpeech heuristic: no audio stream -> definitely false; audio present on
    # a video -> unknown (null) until transcription/vision confirms speech.
    has_speech = False if (is_image or not probe.audio_present) else None
    return {
        "path": str(path),
        "kind": "image" if is_image else "video",
        "duration": None if is_image else probe.duration,
        "resolution": [probe.width, probe.height],
        "orientation": _orientation(probe.width, probe.height),
        "category": category,
        "hasSpeech": has_speech,
        "hasBurnedText": None,          # vision (Phase 2) fills this
        "description": None,            # vision (Phase 2) fills this
        "descriptionSource": "pending",
    }


def _load_broll_cache(cache_path: Path) -> dict:
    """Read ``broll_catalog.json`` into a path -> record map (empty if absent).

    Relative entry paths resolve against the repo root; entries whose file is
    missing on disk are skipped with a warning (a stale row must never crash a
    downstream probe). Keys and record paths are the resolved absolute form.
    """
    if not cache_path.exists():
        return {}
    try:
        data = json.loads(cache_path.read_text())
    except (OSError, json.JSONDecodeError):
        warn(f"unreadable broll cache {cache_path}; rebuilding")
        return {}
    records: dict = {}
    seen: set[str] = set()
    for r in data:
        if not (isinstance(r, dict) and "path" in r):
            continue
        key = _resolve_catalog_path(r.get("originalPath", r["path"]))
        identity = str(key)
        if identity in seen:
            raise RuntimeError("broll catalog repeats an originalPath identity")
        seen.add(identity)
        executable = _resolve_catalog_path(r["path"])
        if not executable.exists():
            warn(f"broll catalog entry missing on disk, skipping: {r['path']}")
            continue
        row = {**r, "path": str(executable)}
        if "originalPath" in row:
            row["originalPath"] = str(key)
        records[identity] = row
    return records


def _write_broll_cache(cache_path: Path, records: list[dict]) -> None:
    """Persist catalog records (fields + mtime) for free re-runs."""
    rows = [{**r, "path": _relative_catalog_path(r["path"])} for r in records]
    try:
        atomic_write_json(cache_path, rows)
    except OSError as exc:
        warn(f"could not write broll cache {cache_path}: {exc}")


def _broll_record_for(path: Path, broll_dir: Path, cached: Optional[dict]) -> Optional[dict]:
    """Catalog fields for one b-roll ``path``.

    A fresh cache hit is passed as ``cached`` (its mtime already matched);
    otherwise the file is probed. Returns None when the probe fails and the
    file must be skipped.
    """
    if cached is not None:
        status(status="broll_cached", path=str(path))
        return {k: v for k, v in cached.items() if k != "mtime"}
    try:
        probe = probe_media(str(path))
    except (RuntimeError, ValueError) as exc:
        warn(f"broll probe failed, skipping {path}: {exc}")
        status(status="broll_probe_failed", path=str(path))
        return None
    fields = broll_fields(path, probe, _category_tag(path, broll_dir))
    status(status="broll_cataloged", path=str(path), kind=fields["kind"])
    return fields


def _scan_broll_dir(broll_dir: Path) -> list[dict]:
    """Catalog every media file under ``broll/`` (recursive), using the cache."""
    cache_path = broll_dir / BROLL_CATALOG_NAME
    cache = _load_broll_cache(cache_path)
    records: list[dict] = []
    fields_out: list[dict] = []
    # Dot-dirs are pool machinery (broll_pool's .frames thumbnails), not b-roll.
    files = sorted(p for p in broll_dir.rglob("*")
                   if p.is_file() and p.suffix.lower() in MEDIA_EXTS
                   and not any(part.startswith(".")
                               for part in p.relative_to(broll_dir).parts))
    for path in files:
        mtime = path.stat().st_mtime
        cached = cache.get(str(path))
        fresh = cached if (cached and cached.get("mtime") == mtime) else None
        fields = _broll_record_for(path, broll_dir, fresh)
        if fields is None:
            continue
        fields_out.append(fields)
        records.append({**fields, "mtime": mtime})
    _write_broll_cache(cache_path, records)
    return fields_out


def catalog_broll(broll_dir: Optional[Path], extra: list[dict]) -> list[dict]:
    """Assemble the manifest ``broll`` list: folder scan + reclassified extras.

    ``extra`` holds top-level no-audio / image files promoted to b-roll by the
    source classifier. Everything is sorted by path, then given ``broll-N`` ids.
    """
    fields_list = list(extra)
    if broll_dir and broll_dir.is_dir():
        fields_list.extend(_scan_broll_dir(broll_dir))
    fields_list.sort(key=lambda f: f["path"])
    return [{"id": f"broll-{i}", **f} for i, f in enumerate(fields_list, start=1)]


def _vibe_tags(path: Path, music_dir: Path) -> list[str]:
    """Vibe tag = the ``music/<vibe>/`` folder; empty for tracks in music/ root."""
    parts = path.relative_to(music_dir).parts
    return [parts[0]] if len(parts) > 1 else []


def scan_music(music_dir: Optional[Path]) -> list[dict]:
    """Catalog actual audio tracks under the explicit project ``music/`` dir."""
    if not music_dir or not music_dir.is_dir():
        return []
    files = sorted(p for p in music_dir.rglob("*")
                   if p.is_file() and p.suffix.lower() in AUDIO_EXTS)
    entries: list[dict] = []
    for path in files:
        try:
            probe = probe_media(str(path))
        except (RuntimeError, ValueError) as exc:
            warn(f"music probe failed, skipping {path}: {exc}")
            status(status="music_probe_failed", path=str(path))
            continue
        if not probe.audio_present:
            warn(f"music candidate has no audio stream, skipping {path}")
            status(status="music_probe_failed", path=str(path), reason="no_audio_stream")
            continue
        vibe = _vibe_tags(path, music_dir)
        mid = f"music-{len(entries) + 1}"
        entries.append({
            "id": mid,
            "path": str(path),
            "duration": probe.duration,
            "vibe": vibe,
            "bpm": None,
            "licensed": None,
            "source": "library",
        })
        status(status="music_detected", id=mid, vibe=vibe, source="project")
    return entries


def scan_builtin_music(builtin_dir: Optional[Path],
                       existing: list[dict]) -> list[dict]:
    """Catalog repo-bundled starter beds (``PROJECT_SNIPER/assets/music/*``).

    Registered AFTER the project's own ``music/`` scan so ``plan.music.assetId``
    resolves out of the box on a project with no music folder (PUNCH_STYLE.md
    §6 M1: 6/6 reels carry a bed — the §11 reproduction shipped bed-less
    because the manifest had no music entry). Additive: ids continue the
    ``music-N`` sequence over ``existing``; a path already cataloged (the
    project's music dir IS the assets dir) is skipped. ``licensed: True`` —
    the bundled beds are synthesized in-repo (no third-party rights);
    ``source: "builtin"`` tells the brain it is a fallback, not the
    operator's pick.
    """
    if not builtin_dir or not builtin_dir.is_dir():
        return []
    seen = {e["path"] for e in existing}
    files = sorted(p for p in builtin_dir.rglob("*")
                   if p.is_file() and p.suffix.lower() in AUDIO_EXTS)
    entries: list[dict] = []
    for path in files:
        if str(path) in seen:
            continue
        try:
            probe = probe_media(str(path))
        except (RuntimeError, ValueError) as exc:
            warn(f"builtin music probe failed, skipping {path}: {exc}")
            status(status="music_probe_failed", path=str(path))
            continue
        mid = f"music-{len(existing) + len(entries) + 1}"
        entries.append({
            "id": mid,
            "path": str(path),
            "duration": probe.duration,
            "vibe": _vibe_tags(path, builtin_dir),
            "bpm": None,
            "licensed": True,           # synthesized in-repo (assets/music)
            "source": "builtin",
        })
        status(status="music_available", id=mid, vibe=entries[-1]["vibe"],
               source="builtin")
    return entries
