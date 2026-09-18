"""Deterministic Audit B for a Palmier graph and its exact candidate export."""
from __future__ import annotations

import os
from dataclasses import asdict

from audit.audio_quality import check_audio_quality
from audit.audit_checks import FAIL, PASS, WARN, check_loudness
from audit.audit_frames import check_frame_extraction, extract_review_frames
from audit.audit_glitch import check_glitch_screens
from audit.audit_motion import check_smoothness
from audit.audit_probe import ffprobe_json, first_stream, fps_from_stream
from fingerprints import file_sha256
from palmier.editable_parity_contract import receipt_path as parity_path
from palmier.editable_parity_contract import run_parity
from palmier.master import authority_hash as master_authority_hash
from palmier.mcp_client import PalmierError
from palmier.native_qc_contract import (audit_path, now, stable_hash,
                                        validate_export)
from palmier.native_qc_frames import clip_start, review_frames
from palmier.timeline_authority import TimelineSnapshot, atomic_write_record

# Back-compatible private import used by the existing QC contract tests.
_review_frames = review_frames


def _check(name: str, ok: bool, measured: str, detail: str = "") -> dict:
    return {"name": name, "status": PASS if ok else FAIL,
            "measured": measured, "detail": detail}


def _positive(value: object) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and float(value) > 0)


def _track_checks(timeline: dict) -> list[dict]:
    tracks, total = timeline.get("tracks"), timeline.get("totalFrames")
    checks: list[dict] = []
    if not isinstance(tracks, list):
        return [_check("graph_tracks", False, "missing", "tracks must be an array")]
    ids: list[str] = []
    invalid_ranges = 0
    for track in tracks:
        if not isinstance(track, dict):
            invalid_ranges += 1
            continue
        if isinstance(track.get("id"), str):
            ids.append(f"track:{track['id']}")
        clips = track.get("clips") or []
        if not isinstance(clips, list):
            invalid_ranges += 1
            continue
        for clip in clips:
            if not isinstance(clip, dict):
                invalid_ranges += 1
                continue
            if isinstance(clip.get("id"), str):
                ids.append(f"clip:{clip['id']}")
            frames = clip.get("frames")
            valid = (isinstance(frames, list) and len(frames) == 2
                     and all(isinstance(item, int) and not isinstance(item, bool)
                             for item in frames)
                     and 0 <= frames[0] < frames[1]
                     and isinstance(total, int) and frames[1] <= total)
            invalid_ranges += 0 if valid else 1
    checks.append(_check("graph_structural_ids", len(ids) == len(set(ids)),
                         f"{len(ids)} ids", "track/clip ids must be unique"))
    checks.append(_check("graph_clip_ranges", invalid_ranges == 0,
                         f"{invalid_ranges} invalid", "0 <= start < end <= totalFrames"))
    return checks


def structural_proof(found: TimelineSnapshot) -> dict:
    """Deterministically validate fresh readback completeness and graph bounds."""
    timeline = found.timeline
    checks = [
        _check("readback_complete", found.coverage.get("complete") is True,
               str(found.coverage.get("complete")), "full MCP readback required"),
        _check("graph_total_frames", _positive(timeline.get("totalFrames")),
               str(timeline.get("totalFrames")), "positive totalFrames required"),
        _check("graph_fps", _positive(timeline.get("fps")),
               str(timeline.get("fps")), "positive fps required"),
        _check("graph_canvas", _positive(timeline.get("width"))
               and _positive(timeline.get("height")),
               f"{timeline.get('width')}x{timeline.get('height')}",
               "positive canvas dimensions required"),
        *_track_checks(timeline),
    ]
    content = {"schemaVersion": 1, "timelineId": found.timeline_id,
               "fingerprint": found.fingerprint, "checks": checks}
    return {**content, "status": FAIL if any(
        row["status"] == FAIL for row in checks) else PASS,
        "digest": stable_hash(content)}


def _motion_plan(receipt: dict, found: TimelineSnapshot, fps: float) -> dict:
    authority = receipt.get("authority") or {}
    if isinstance(authority.get("editPlan"), dict):
        return authority["editPlan"]
    native = authority.get("nativePlan") or {}
    parent = authority.get("nativeParent") or {}
    windows = []
    for operation in native.get("operations") or []:
        args = operation.get("args") or {}
        rows = args.get("keyframes") or []
        if operation.get("tool") != "set_keyframes" or len(rows) < 2 \
                or args.get("property") not in {
                    "opacity", "rotation", "position", "scale", "crop"}:
            continue
        start = clip_start(parent.get("timeline") or {}, found.timeline,
                           args.get("clipId"))
        windows.append({"role": "aliveness",
                        "outStart": (start + rows[0][0]) / fps,
                        "outEnd": (start + rows[-1][0]) / fps})
    return {"target": {"treatment": "produced"}, "punchIns": windows}


def _declared_windows(receipt: dict, flag: str) -> list[tuple[float, float]]:
    plan = (receipt.get("authority") or {}).get("editPlan") or {}
    return [(float(row["outStart"]), float(row["outEnd"]))
            for row in plan.get("graphicsTrack") or []
            if isinstance(row, dict) and row.get(flag) is True]


def _native_glitch_checks(path: str, duration: float,
                          receipt: dict) -> list[dict]:
    rows = []
    for result in check_glitch_screens(
            path, duration,
            allow_black=_declared_windows(receipt, "allowDarkEntry"),
            allow_freeze=_declared_windows(receipt, "allowStaticHold")):
        row = asdict(result)
        if row["name"] in ("glitch_freeze", "glitch_flash") \
                and row["status"] == WARN:
            row["status"] = FAIL
            row["detail"] = (row.get("detail") or "") \
                + "; native candidate QC fails closed on visible freeze/flash evidence"
        rows.append(row)
    return rows


def _export_checks(receipt: dict, found: TimelineSnapshot) -> tuple[list[dict],
                                                                    list[dict]]:
    export = validate_export(receipt)
    probe = ffprobe_json(export["path"])
    video, audio = first_stream(probe, "video"), first_stream(probe, "audio")
    checks = [
        _check("export_video", video is not None, "present" if video else "missing"),
        _check("export_audio_preserved", audio is not None,
               "present" if audio else "missing", "candidate audio must remain native"),
    ]
    if video:
        expected = (found.timeline.get("width"), found.timeline.get("height"))
        actual = (video.get("width"), video.get("height"))
        measured_fps = fps_from_stream(video)
        expected_fps = float(found.timeline.get("fps") or 0.0)
        checks.extend([
            _check("export_canvas", actual == expected, f"{actual[0]}x{actual[1]}",
                   f"expected {expected[0]}x{expected[1]}"),
            _check("export_fps", measured_fps is not None
                   and abs(measured_fps - expected_fps) <= 0.01,
                   str(video.get("r_frame_rate")), f"expected {expected_fps:.6f} fps"),
            _check("export_duration", float(export.get("frameError", 999.0)) <= 2.0001,
                   f"{export.get('durationSeconds')}s / {export.get('frameError')}f error",
                   "duration must match candidate totalFrames within two frames"),
        ])
    checks.extend(asdict(row) for row in check_loudness(export["path"], True))
    checks.extend(asdict(row) for row in check_audio_quality(export["path"], {}))
    duration = float(export["durationSeconds"])
    checks.extend(_native_glitch_checks(export["path"], duration, receipt))
    checks.extend(asdict(row) for row in check_smoothness(
        export["path"], _motion_plan(
            receipt, found, float(found.timeline["fps"]))))
    frames_dir = os.path.join(receipt["outDir"], "palmier-native-qc")
    os.makedirs(frames_dir, exist_ok=True)
    refs = extract_review_frames(
        export["path"], frames_dir,
        review_frames(receipt, found, duration))
    checks.append(asdict(check_frame_extraction(refs)))
    frames = [{**asdict(ref), "hash": file_sha256(ref.path)}
              for ref in refs if ref.path]
    return checks, frames


def run_native_audit(out_dir: str, receipt: dict,
                     found: TimelineSnapshot) -> dict:
    """Build a deterministic audit artifact; caller rechecks drift before authority."""
    graph = structural_proof(found)
    checks, frames = _export_checks(receipt, found)
    if (receipt.get("authority") or {}).get("kind") in {
            "live-build", "desktop-build"}:
        authority = receipt["authority"]
        master_hash = master_authority_hash(out_dir, authority["planHash"])
        parity = run_parity(
            out_dir, receipt["export"]["path"], master_hash)
        blocked = ", ".join(parity["blockedMetricIds"]) or "none"
        checks.append({
            "name": "editable_master_parity",
            "status": PASS if parity["verdict"] == "pass" else FAIL,
            "measured": parity["digest"],
            "detail": f"blocked metrics: {blocked}",
            "evidence": {"path": parity_path(out_dir),
                         "hash": file_sha256(parity_path(out_dir))},
        })
    checks = [*graph["checks"], *checks]
    content = {"schemaVersion": 1, "stage": "palmier-native-audit",
               "candidateFingerprint": found.fingerprint,
               "exportHash": receipt["export"]["hash"],
               "inputAuthorityDigest": receipt["authority"]["inputDigest"],
               "checks": checks, "frames": frames}
    audit = {**content, "status": FAIL if any(
        row["status"] == FAIL for row in checks) else PASS,
        "digest": stable_hash(content)}
    atomic_write_record(audit_path(out_dir), audit)
    if audit["status"] != PASS:
        raise PalmierError("Palmier candidate failed deterministic native Audit B")
    return {**audit, "auditPath": audit_path(out_dir),
            "auditHash": file_sha256(audit_path(out_dir)), "auditedAt": now()}
