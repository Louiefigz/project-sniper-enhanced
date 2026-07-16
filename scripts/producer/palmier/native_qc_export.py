"""Explicit-timeline Palmier candidate export without stale Sniper audio."""
from __future__ import annotations

import os
from typing import Any

from audit.audit_probe import ffprobe_json, first_stream
from fingerprints import file_sha256
from palmier.export import verify_export, wait_for_export
from palmier.mcp_client import PalmierError
from palmier.native_qc_contract import EXPORT_TEMP_NAME, export_path
from palmier.timeline_authority import TimelineSnapshot


def _safe_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _stable_hash(path: str) -> tuple[str, os.stat_result]:
    before = os.stat(path)
    digest = file_sha256(path)
    after = os.stat(path)
    signature = lambda value: (value.st_dev, value.st_ino, value.st_size,
                               value.st_mtime_ns, value.st_ctime_ns)
    if signature(before) != signature(after) or after.st_size <= 0:
        raise PalmierError("Palmier candidate export changed while it was hashed")
    return digest, after


def export_candidate(client: Any, out_dir: str,
                     candidate: TimelineSnapshot,
                     timing: dict | None = None) -> dict:
    """Export the explicit candidate id and preserve its own program audio."""
    settings = timing or {}
    temp_path = os.path.join(out_dir, EXPORT_TEMP_NAME)
    final_path = export_path(out_dir)
    _safe_unlink(temp_path)
    try:
        result = client.call("export_project", {
            "timelineId": candidate.timeline_id, "outputPath": temp_path})
        wait_for_export(temp_path, None, float(settings.get("timeoutS", 600.0)),
                        float(settings.get("pollS", 2.0)))
        total_frames = candidate.timeline.get("totalFrames")
        fps = candidate.timeline.get("fps")
        if isinstance(total_frames, bool) or not isinstance(total_frames, int) \
                or not isinstance(fps, (int, float)):
            raise PalmierError("Palmier candidate has no valid frame duration")
        probe = verify_export(temp_path, total_frames, float(fps))
        media = ffprobe_json(temp_path)
        if first_stream(media, "video") is None:
            raise PalmierError("Palmier candidate export has no video stream")
        if first_stream(media, "audio") is None:
            raise PalmierError(
                "Palmier candidate export has no audio; stale Sniper audio was not substituted")
        digest, stat = _stable_hash(temp_path)
        os.replace(temp_path, final_path)
        final_hash, final_stat = _stable_hash(final_path)
        if final_hash != digest or final_stat.st_size != stat.st_size:
            raise PalmierError("Palmier candidate export changed during atomic publication")
        return {"path": final_path, "hash": final_hash,
                "bytes": final_stat.st_size, "durationSeconds": probe.duration_s,
                "frameError": probe.frame_error,
                "audioPresent": True, "timelineId": candidate.timeline_id,
                "mcpResult": str(result)[:200]}
    except BaseException:
        _safe_unlink(temp_path)
        raise
