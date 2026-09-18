#!/usr/bin/env python3
"""Verified, transactional exports for Palmier shadow timelines.

Palmier renders in the background, so an accepted MCP call is not evidence of
a usable file. This module waits for a newly-written, stable-size temporary
MP4, verifies its video duration with ffprobe, and only then atomically
promotes the video and its plan-hash metadata.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Protocol

from audit.audio_quality import check_audio_quality
from audit.audit_checks import FAIL
from palmier.audio_finish import (FinishReport, FinishSpec,
                                  finish_authoritative_audio)
from palmier.mcp_client import PalmierError, emit
from palmier.process_deadline import process_timeout

FINAL_NAME = "final.palmier.mp4"
TEMP_NAME = "final.palmier.tmp.mp4"
AUDIO_TEMP_NAME = "final.palmier.audio.tmp.mp4"
META_NAME = "final.palmier.meta.json"


class ExportClient(Protocol):
    """The small Palmier client surface required by this module."""

    def call(self, tool: str, arguments: dict | None = None) -> str:
        """Invoke one Palmier MCP tool."""
        ...


@dataclass(frozen=True)
class ExportRequest:
    """Inputs for one timeline; fps is Palmier's rounded project timebase."""

    out_dir: str
    timeline_id: str
    expected_end_frame: int
    fps: float
    plan_hash: str
    music_enabled: bool = False
    authority_hash: str | None = None
    timeout_s: float = 600.0
    poll_s: float = 2.0


@dataclass(frozen=True)
class ExportProbe:
    """Verified facts read from the exported MP4."""

    duration_s: float
    frame_error: float


@dataclass(frozen=True)
class ExportResult:
    """Paths and measurements for a successfully promoted export."""

    output_path: str
    metadata_path: str
    bytes: int
    duration_s: float


def _mtime_ns(path: str) -> int | None:
    """Return a file's nanosecond mtime, or None when it is absent."""
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return None


def _safe_unlink(path: str | None) -> None:
    """Best-effort cleanup for staging artifacts."""
    if not path:
        return
    try:
        os.unlink(path)
    except OSError:
        pass


def wait_for_export(path: str, previous_mtime_ns: int | None,
                    timeout_s: float = 600.0,
                    poll_s: float = 2.0) -> os.stat_result:
    """Wait for a new, non-empty export whose size is stable for two polls."""
    if timeout_s <= 0 or poll_s < 0:
        raise PalmierError("export wait requires timeout > 0 and poll >= 0")
    deadline = time.monotonic() + timeout_s
    last_size: int | None = None
    while time.monotonic() < deadline:
        time.sleep(poll_s)
        try:
            stat = os.stat(path)
        except OSError:
            continue
        is_new = (previous_mtime_ns is None
                  or stat.st_mtime_ns > previous_mtime_ns)
        if not is_new or stat.st_size <= 0:
            last_size = None
            continue
        if stat.st_size == last_size:
            return stat
        last_size = stat.st_size
    raise PalmierError(
        f"export did not stabilize within {timeout_s:.0f}s: {path}")


def _probe_json(path: str) -> dict:
    """Run one ffprobe call and return its parsed JSON result."""
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=codec_type,duration:format=duration",
           "-of", "json", path]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, check=False,
            timeout=process_timeout())
    except OSError as exc:
        raise PalmierError(f"could not run ffprobe: {exc}") from exc
    if proc.returncode != 0:
        raise PalmierError(
            f"ffprobe failed for {path}: {proc.stderr.strip()[-300:]}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise PalmierError(f"ffprobe returned invalid JSON for {path}") from exc


def _positive_float(value: object) -> float | None:
    """Parse a finite positive ffprobe number, otherwise return None."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def verify_export(path: str, expected_end_frame: int,
                  fps: float) -> ExportProbe:
    """Require video and duration within two frames of the expected end."""
    if expected_end_frame <= 0 or not math.isfinite(fps) or fps <= 0:
        raise PalmierError("export verification requires positive end/fps")
    data = _probe_json(path)
    videos = [s for s in data.get("streams", [])
              if s.get("codec_type") == "video"]
    if not videos:
        raise PalmierError(f"export has no video stream: {path}")
    duration = (_positive_float(videos[0].get("duration"))
                or _positive_float(data.get("format", {}).get("duration")))
    if duration is None:
        raise PalmierError(f"export has no positive video duration: {path}")
    frame_error = abs(duration * fps - expected_end_frame)
    if frame_error > 2.0001:
        expected_s = expected_end_frame / fps
        raise PalmierError(
            f"export duration mismatch: got {duration:.6f}s, expected "
            f"{expected_s:.6f}s (error {frame_error:.3f} frames)")
    return ExportProbe(duration_s=duration, frame_error=frame_error)


def _stage_metadata(path: str, payload: dict[str, object]) -> str:
    """Write and fsync metadata beside its destination without replacing it."""
    directory = os.path.dirname(path)
    prefix = f".{os.path.basename(path)}."
    fd, staged = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        _safe_unlink(staged)
        raise
    return staged


def _backup_final(path: str) -> str | None:
    """Hard-link the old final so a later metadata failure can roll back."""
    if not os.path.exists(path):
        return None
    backup = f"{path}.rollback-{os.getpid()}-{time.time_ns()}"
    os.link(path, backup)
    return backup


def _restore_final(final_path: str, backup: str | None) -> None:
    """Restore the prior final, or remove the newly-created final."""
    if backup:
        os.replace(backup, final_path)
        return
    _safe_unlink(final_path)


def _promote(temp_path: str, final_path: str, meta_path: str,
             metadata: dict[str, object]) -> None:
    """Atomically promote video+metadata, rolling video back on failure."""
    staged_meta = _stage_metadata(meta_path, metadata)
    backup: str | None = None
    final_replaced = False
    try:
        backup = _backup_final(final_path)
        os.replace(temp_path, final_path)
        final_replaced = True
        os.replace(staged_meta, meta_path)
    except Exception as exc:
        if final_replaced:
            try:
                _restore_final(final_path, backup)
                backup = None
            except OSError as rollback_exc:
                preserved_backup = backup
                backup = None
                raise PalmierError(
                    f"export promotion failed and rollback failed: "
                    f"{rollback_exc}; prior final remains at "
                    f"{preserved_backup}") from exc
        raise
    finally:
        _safe_unlink(staged_meta)
        _safe_unlink(backup)


def _metadata(plan_hash: str, authority_hash: str | None,
              audio: FinishReport, checks: list) -> dict[str, object]:
    """Build the sidecar written only for a verified export."""
    pushed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    finish = asdict(audio)
    finish["output_path"] = FINAL_NAME
    return {"planHash": plan_hash, "authorityHash": authority_hash,
            "pushedAt": pushed_at,
            "exportVerified": True, "audioVerified": True,
            "audioQc": {"finish": finish,
                        "checks": [asdict(check) for check in checks]}}


def export_timeline(client: ExportClient,
                    request: ExportRequest) -> ExportResult:
    """Export one timeline to tmp, verify it, then transactionally publish."""
    os.makedirs(request.out_dir, exist_ok=True)
    temp_path = os.path.join(request.out_dir, TEMP_NAME)
    audio_path = os.path.join(request.out_dir, AUDIO_TEMP_NAME)
    master_path = os.path.join(request.out_dir, "final.mp4")
    final_path = os.path.join(request.out_dir, FINAL_NAME)
    meta_path = os.path.join(request.out_dir, META_NAME)
    previous_mtime_ns = _mtime_ns(temp_path)
    _safe_unlink(temp_path)
    _safe_unlink(audio_path)
    try:
        result = client.call("export_project", {
            "timelineId": request.timeline_id, "outputPath": temp_path})
        emit(status="export_started", timelineId=request.timeline_id,
             outputPath=temp_path, result=result[:200])
        stat = wait_for_export(temp_path, previous_mtime_ns,
                               request.timeout_s, request.poll_s)
        probe = verify_export(temp_path, request.expected_end_frame,
                              request.fps)
        audio = finish_authoritative_audio(FinishSpec(
            temp_path, master_path, audio_path))
        checks = check_audio_quality(
            audio_path, {"music": {"enabled": request.music_enabled}})
        failures = [check for check in checks if check.status == FAIL]
        if failures:
            detail = "; ".join(f"{c.name}: {c.measured}" for c in failures)
            raise PalmierError(f"Palmier delivery audio QC failed: {detail}")
        _safe_unlink(temp_path)
        stat = os.stat(audio_path)
        _promote(audio_path, final_path, meta_path,
                 _metadata(request.plan_hash, request.authority_hash,
                           audio, checks))
        emit(status="exported", outputPath=final_path, bytes=stat.st_size,
             durationSeconds=probe.duration_s, exportVerified=True,
             audioVerified=True, lufs=audio.integrated_lufs,
             truePeakDbtp=audio.true_peak_dbtp)
        return ExportResult(final_path, meta_path, stat.st_size,
                            probe.duration_s)
    except PalmierError:
        _safe_unlink(temp_path)
        _safe_unlink(audio_path)
        raise
    except Exception as exc:
        _safe_unlink(temp_path)
        _safe_unlink(audio_path)
        raise PalmierError(f"verified export failed: {exc}") from exc
