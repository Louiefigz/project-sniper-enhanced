"""Explicit-timeline Palmier candidate export without stale Sniper audio."""
from __future__ import annotations

import os
from typing import Any

from audit.audit_probe import ffprobe_json, run_ff
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


def _stream_count(media: dict, kind: str) -> int:
    streams = media.get("streams")
    if not isinstance(streams, list):
        return 0
    return sum(
        1 for row in streams
        if isinstance(row, dict) and row.get("codec_type") == kind)


def _full_decode(path: str) -> None:
    result = run_ff([
        "ffmpeg", "-v", "error", "-xerror", "-i", path,
        "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-",
    ])
    if result.returncode != 0:
        raise PalmierError(
            "Palmier candidate export failed full A/V decode: "
            + result.stderr.strip()[-500:])


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
        timeout = float(settings.get("timeoutS", 600.0))
        deadline = getattr(client, "deadline", None)
        if deadline is not None:
            timeout = min(timeout, deadline.remaining())
        wait_for_export(temp_path, None, timeout,
                        min(float(settings.get("pollS", 2.0)), timeout))
        if deadline is not None:
            deadline.check()
        total_frames = candidate.timeline.get("totalFrames")
        fps = candidate.timeline.get("fps")
        if isinstance(total_frames, bool) or not isinstance(total_frames, int) \
                or not isinstance(fps, (int, float)):
            raise PalmierError("Palmier candidate has no valid frame duration")
        probe = verify_export(temp_path, total_frames, float(fps))
        media = ffprobe_json(temp_path)
        video_count = _stream_count(media, "video")
        audio_count = _stream_count(media, "audio")
        if video_count != 1:
            raise PalmierError(
                "Palmier candidate export requires exactly one video stream")
        if audio_count != 1:
            raise PalmierError(
                "Palmier candidate export requires exactly one encoded audio "
                "stream; audible-route authority is validated separately")
        _full_decode(temp_path)
        digest, stat = _stable_hash(temp_path)
        os.replace(temp_path, final_path)
        final_hash, final_stat = _stable_hash(final_path)
        if final_hash != digest or final_stat.st_size != stat.st_size:
            raise PalmierError("Palmier candidate export changed during atomic publication")
        return {"path": final_path, "hash": final_hash,
                "bytes": final_stat.st_size, "durationSeconds": probe.duration_s,
                "frameError": probe.frame_error,
                "audioPresent": True, "audioStreamCount": audio_count,
                "videoStreamCount": video_count,
                "fullDecode": "ffmpeg-xerror-av-v1",
                "timelineId": candidate.timeline_id,
                "mcpResult": str(result)[:200]}
    except BaseException:
        _safe_unlink(temp_path)
        raise
