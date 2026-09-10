#!/usr/bin/env python3
"""audit_checks — the deterministic Audit B checks (pass / fail / warn).

Each check consumes measurements from :mod:`audit_probe` and returns one or more
:class:`CheckResult` with a measured value. Thresholds come from
``producer_config`` so QC and the renderer share one source of truth. See
docs/producer/PRODUCER_PLAN.md §5 (Audit B) and §4.5 (render spec).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audit.audit_probe import (  # noqa: E402
    fps_from_stream, image_size, is_faststart, mean_luma,
    same_frame_rate, video_frame_count,
)
from audio.audio_mix_delivery import measure_delivery  # noqa: E402
from compile_timeline import TimelineMap  # noqa: E402
from producer_config import AUDIO, CANVAS, ENCODE  # noqa: E402

PASS = "pass"
FAIL = "fail"
WARN = "warn"

# A near-black cover (mean luma below this, 0-255) is the de-facto thumbnail
# failing — flags edge C9. Real settled frames sit well above; only a truly
# black frame 0 trips it.
COVER_MIN_MEAN_LUMA = 16.0
# Longform is a 16:9 passthrough; allow a hair of rounding on the ratio.
ASPECT_16_9 = 16.0 / 9.0
ASPECT_TOLERANCE = 0.02


@dataclass
class CheckResult:
    """One audit finding: a named check, its verdict, and what was measured."""

    name: str
    status: str          # PASS | FAIL | WARN
    measured: str        # human-readable measured value
    detail: str = ""     # expected value / threshold context


def _result(name: str, ok: bool, measured: str, detail: str = "") -> CheckResult:
    """Build a CheckResult, choosing PASS/FAIL from ``ok`` (WARN cases build
    CheckResult directly — only the true-peak grade needs a third verdict)."""
    return CheckResult(name, PASS if ok else FAIL, measured, detail)


def check_duration(final_path: str, video: dict, tmap: TimelineMap) -> CheckResult:
    """Video-timeline duration (frame_count / fps) vs the compiler's predicted
    outputDuration, with the renderer's own tolerance (1.0 + 0.5*n_segments
    frames). Container duration is deliberately NOT used (edge X8)."""
    n_segments = len(tmap.segments)
    expected_s = tmap.output_duration
    frames = video_frame_count(final_path)
    fps = fps_from_stream(video)
    if frames is None or fps is None:
        return CheckResult("duration", FAIL, "unreadable",
                           f"expected {expected_s:.3f}s")
    video_s = frames / fps
    drift = abs(frames - expected_s * fps)
    tol = 1.0 + 0.5 * n_segments
    measured = f"{video_s:.3f}s ({frames}f) vs {expected_s:.3f}s"
    detail = f"drift {drift:.2f}f, tol {tol:.1f}f over {n_segments} segments"
    return _result("duration", drift <= tol, measured, detail)


def check_loudness(final_path: str, has_audio: bool,
                   observation: dict | None = None) -> list[CheckResult]:
    """Require complete audio decode and the shared delivery LUFS/TP policy."""
    observed = observation if observation is not None else measure_delivery(final_path)
    lufs, peak = observed["integratedLufs"], observed["truePeakDbtp"]
    target, tol = AUDIO["lufs_target"], AUDIO["lufs_tolerance"]
    decoded = has_audio and observed["audioDecodeSucceeded"]
    decode_res = _result(
        "audio_decode_complete", decoded,
        "complete" if decoded else "failed",
        str(observed["audioDecodeError"]) or "selected audio decoded to EOF")
    lufs_ok = decoded and observed["lufsWithinTolerance"]
    lufs_res = _result(
        "loudness_integrated", lufs_ok,
        "unmeasured" if lufs is None else f"{lufs:.1f} LUFS",
        f"target {target} +/-{tol}")
    return [decode_res, lufs_res, _true_peak_result(peak if decoded else None)]


def _true_peak_result(peak: Optional[float]) -> CheckResult:
    """The delivery ceiling is a hard gate, never a relaxed warning band."""
    ceil = AUDIO["true_peak_dbtp"]
    detail = f"ceiling {ceil} dBTP"
    if peak is None:
        return CheckResult("loudness_true_peak", FAIL, "unmeasured", detail)
    measured = f"{peak:.1f} dBTP"
    return _result("loudness_true_peak", peak <= ceil, measured, detail)


def _resolution_result(video: dict, mode: str) -> CheckResult:
    """1080x1920 for short masters; a 16:9 passthrough for longform."""
    width, height = int(video.get("width", 0)), int(video.get("height", 0))
    measured = f"{width}x{height}"
    if mode == "short":
        ok = width == CANVAS["width"] and height == CANVAS["height"]
        return _result("format_resolution", ok, measured,
                       f"expected {CANVAS['width']}x{CANVAS['height']}")
    ratio = width / height if height else 0.0
    ok = abs(ratio - ASPECT_16_9) <= ASPECT_TOLERANCE
    return _result("format_resolution", ok, f"{measured} ({ratio:.3f})",
                   "expected 16:9 passthrough")


def check_format(final_path: str, video: dict,
                 audio: Optional[dict], mode: str) -> list[CheckResult]:
    """Codec / container conformance: resolution, H.264 High, yuv420p, CFR,
    faststart, AAC 48k stereo. Every property is its own row so the human table
    shows exactly what conformed."""
    faststart = is_faststart(final_path)
    r_rate, avg_rate = video.get("r_frame_rate"), video.get("avg_frame_rate")
    results = [
        _resolution_result(video, mode),
        _result("format_vcodec", video.get("codec_name") == "h264",
                str(video.get("codec_name")), "expected h264"),
        _result("format_profile", video.get("profile") == "High",
                str(video.get("profile")), "expected High"),
        _result("format_pix_fmt", video.get("pix_fmt") == CANVAS["pix_fmt"],
                str(video.get("pix_fmt")), f"expected {CANVAS['pix_fmt']}"),
        _result("format_cfr", same_frame_rate(r_rate, avg_rate),
                f"r={r_rate} avg={avg_rate}", "CFR: r_frame_rate == avg"),
        _result("format_faststart", faststart is True,
                "moov<mdat" if faststart else str(faststart),
                "moov before mdat"),
    ]
    results.extend(_audio_format_results(audio))
    return results


def _audio_format_results(audio: Optional[dict]) -> list[CheckResult]:
    """AAC / 48kHz / stereo rows (or one failure row when audio is absent)."""
    if audio is None:
        return [CheckResult("format_audio", FAIL, "no audio stream",
                            "expected aac 48k stereo")]
    rate = _safe_int(audio.get("sample_rate"))
    channels = _safe_int(audio.get("channels"))
    return [
        _result("format_acodec", audio.get("codec_name") == ENCODE["acodec"],
                str(audio.get("codec_name")), f"expected {ENCODE['acodec']}"),
        _result("format_arate", rate == ENCODE["audio_rate"],
                f"{rate} Hz", f"expected {ENCODE['audio_rate']}"),
        _result("format_achannels", channels == ENCODE["audio_channels"],
                f"{channels}ch", f"expected {ENCODE['audio_channels']}"),
    ]


def _safe_int(value: object) -> Optional[int]:
    """Best-effort int (ffprobe returns numbers as strings), else None."""
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def check_file_budget(final_path: str, mode: str = "short") -> CheckResult:
    """File size at/under the TikTok in-app cap (MiB, matching master.py).

    Shorts-only (edge X18): the 287MB cap is TikTok's in-app upload limit;
    long-form masters are routinely far larger and upload fine to YouTube —
    reported informationally, never failed.
    """
    try:
        size_mb = os.path.getsize(final_path) / (1024 * 1024)
    except OSError:
        return CheckResult("file_budget", FAIL, "unreadable",
                           f"cap {ENCODE['max_file_mb']}MB")
    cap = ENCODE["max_file_mb"]
    if mode == "longform":
        return CheckResult("file_budget", PASS, f"{size_mb:.1f}MB",
                           "no cap in longform mode (X18)")
    return _result("file_budget", size_mb <= cap, f"{size_mb:.1f}MB",
                   f"cap {cap}MB")


def check_cover(out_dir: str, video: dict) -> CheckResult:
    """Cover exists, matches the video dims, and is not near-black (edge C9)."""
    cover = os.path.join(out_dir, "cover.png")
    if not os.path.exists(cover):
        return CheckResult("cover", FAIL, "missing",
                           "cover.png is the de-facto thumbnail")
    dims = image_size(cover)
    want = (int(video.get("width", 0)), int(video.get("height", 0)))
    if dims != want:
        return CheckResult("cover", FAIL,
                           f"{dims[0]}x{dims[1]}" if dims else "unreadable",
                           f"expected {want[0]}x{want[1]}")
    luma = mean_luma(cover)
    if luma is None:
        return CheckResult("cover", FAIL, "unreadable luma", "")
    ok = luma > COVER_MIN_MEAN_LUMA
    return _result("cover", ok, f"{want[0]}x{want[1]}, luma {luma:.0f}",
                   f"luma floor {COVER_MIN_MEAN_LUMA:.0f} (near-black check)")


def worst_status(results: list[CheckResult]) -> str:
    """Roll up a list of results: FAIL beats WARN beats PASS."""
    statuses = {r.status for r in results}
    if FAIL in statuses:
        return FAIL
    if WARN in statuses:
        return WARN
    return PASS


def has_audio_stream(audio: Optional[dict]) -> bool:
    """True when an audio stream dict was probed."""
    return audio is not None
