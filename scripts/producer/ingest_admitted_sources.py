"""Raw-source manifest rows over immutable sandbox-admitted snapshots."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ingest_admission import AdmittedMedia
from ingest_admitted_scan import _proof_fields
from ingest_probe import (
    IMAGE_EXTS,
    MediaProbe,
    content_hash,
    probe_media,
    status,
    warn,
)
from ingest_scan import broll_fields


@dataclass(frozen=True)
class SourceBuildContext:
    """Opaque transcription state and the owning ingest callback."""

    transcribe_context: object
    transcribe: Callable[[Path, str, object], str | None]


def _probe(path: Path) -> MediaProbe:
    try:
        return probe_media(str(path))
    except (RuntimeError, ValueError) as exc:
        raise RuntimeError(
            f"admitted source could not be reprobed: {path}: {exc}") from exc


def _source_entry(media: AdmittedMedia, source_id: str,
                  probe: MediaProbe, chash: str) -> dict:
    return {
        "id": source_id,
        "path": media.snapshot_path,
        "duration": probe.duration,
        "fps": probe.fps,
        "frameRate": probe.frame_rate,
        "vfr": probe.vfr,
        "resolution": [probe.width, probe.height],
        "rotation": probe.rotation,
        "audio": {
            "present": probe.audio_present,
            "channels": probe.audio_channels,
            "sampleRate": probe.audio_sample_rate,
        },
        "contentHash": chash,
        "transcriptPath": None,
        "role": "primary" if source_id == "raw-1" else "secondary",
        **_proof_fields(media),
    }


def _extra_broll(original: Path, media: AdmittedMedia,
                 probe: MediaProbe) -> dict:
    row = broll_fields(original, probe, category=None)
    row.update(path=media.snapshot_path, **_proof_fields(media))
    return row


def build_admitted_sources(
    raw_files: list[Path],
    context: SourceBuildContext,
    admitted: dict[str, AdmittedMedia],
) -> tuple[list[dict], list[dict]]:
    """Build source/b-roll rows, consuming only admitted snapshot paths."""
    sources, extra_broll = [], []
    seen: dict[str, str] = {}
    for original in raw_files:
        media = admitted.get(str(original.absolute()))
        if media is None:
            raise RuntimeError(f"source was not sandbox-admitted: {original}")
        snapshot = Path(media.snapshot_path)
        probe = _probe(snapshot)
        if original.suffix.lower() in IMAGE_EXTS or not probe.audio_present:
            extra_broll.append(_extra_broll(original, media, probe))
            reason = ("image_reclassified_to_broll"
                      if original.suffix.lower() in IMAGE_EXTS
                      else "no_audio_reclassified_to_broll")
            status(status=reason, path=str(original))
            continue
        chash = content_hash(media.snapshot_path)
        if chash in seen:
            warn(f"duplicate of {seen[chash]} skipped: {original}")
            status(status="duplicate_skipped", path=str(original),
                   duplicate_of=seen[chash])
            continue
        source_id = f"raw-{len(sources) + 1}"
        seen[chash] = source_id
        entry = _source_entry(media, source_id, probe, chash)
        entry["transcriptPath"] = context.transcribe(
            snapshot, source_id, context.transcribe_context)
        sources.append(entry)
        status(status="source_added", id=source_id,
               duration=probe.duration, vfr=probe.vfr)
    return sources, extra_broll
