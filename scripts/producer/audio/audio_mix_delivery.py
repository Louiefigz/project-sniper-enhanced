"""Qualify encoded music candidates before replacing a public delivery file."""
from __future__ import annotations

import math
import os
import json
import subprocess
import tempfile
from typing import Callable

from producer_config import AUDIO
from palmier.process_deadline import process_timeout
from fingerprint_io import file_sha256

AUDIO_DELIVERY_POLICY_VERSION = 2


def _finite(value: object) -> float | None:
    """Missing/non-finite measurements cannot qualify a delivery."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _observe_final_audio(path: str, prefix: str | None = None) -> tuple[dict | None, int, str]:
    """Decode the entire selected audio stream; partial statistics never pass."""
    audio_filter = (f"loudnorm=I={AUDIO['lufs_target']}:TP={AUDIO['loudnorm_tp_param']}"
                    f":LRA={AUDIO['lra']}:print_format=json")
    if prefix:
        audio_filter = f"{prefix},{audio_filter}"
    try:
        result = subprocess.run([
            "ffmpeg", "-hide_banner", "-nostats", "-xerror", "-err_detect", "explode",
            "-i", path, "-map", "0:a:0", "-af", audio_filter, "-f", "null", "-",
        ], capture_output=True, text=True, check=False, timeout=process_timeout())
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, -1, f"complete audio decode failed: {exc}"
    if result.returncode:
        return None, result.returncode, result.stderr[-1200:]
    try:
        measurement, _ = json.JSONDecoder().raw_decode(
            result.stderr[result.stderr.rfind("{"):])
    except (ValueError, json.JSONDecodeError):
        return None, 0, "complete audio decode returned no loudness measurement"
    return (measurement if isinstance(measurement, dict) else None), 0, ""


def measure_delivery(path: str) -> dict[str, object]:
    """Use shared master targets on the complete final AAC decode."""
    observed, exit_code, error = _observe_final_audio(path)
    measured = (observed or {}) if exit_code == 0 else {}
    integrated = _finite(measured.get("input_i"))
    peak = _finite(measured.get("input_tp"))
    residual = None if integrated is None else integrated - AUDIO["lufs_target"]
    loudness_ok = residual is not None and abs(residual) <= AUDIO["lufs_tolerance"]
    peak_ok = peak is not None and peak <= AUDIO["true_peak_dbtp"]
    return {
        "policyVersion": AUDIO_DELIVERY_POLICY_VERSION,
        "integratedLufs": integrated, "truePeakDbtp": peak,
        "lufsTarget": AUDIO["lufs_target"], "lufsTolerance": AUDIO["lufs_tolerance"],
        "truePeakCeilingDbtp": AUDIO["true_peak_dbtp"], "lufsResidual": residual,
        "truePeakExcessDb": None if peak is None else max(0, peak - AUDIO["true_peak_dbtp"]),
        "lufsWithinTolerance": loudness_ok, "truePeakWithinCeiling": peak_ok,
        "audioDecodeSucceeded": exit_code == 0, "audioDecodeExitCode": exit_code,
        "audioDecodeError": error,
        "qualified": exit_code == 0 and loudness_ok and peak_ok,
    }


def render_qualified_mix(out_path: str, render: Callable[[str], dict]) -> dict:
    """Keep rejected candidates isolated; atomically promote qualified bytes."""
    destination = os.path.abspath(out_path)
    directory = os.path.dirname(destination)
    os.makedirs(directory, exist_ok=True)
    candidate_dir = tempfile.mkdtemp(prefix=".audio-mix-candidate-", dir=directory)
    candidate = os.path.join(candidate_dir, os.path.basename(destination))
    result = render(candidate)
    before = file_sha256(candidate) if result["ok"] else None
    comparison_required = "expectedCandidateSha256" in result
    comparison_bound = (not comparison_required
                        or result["expectedCandidateSha256"] == before)
    evidence = measure_delivery(candidate) if result["ok"] and comparison_bound else None
    try:
        stable = before is not None and file_sha256(candidate) == before
    except OSError:
        stable = False
    if not result["ok"] or not comparison_bound or not stable or not evidence["qualified"]:
        detail = (result["stderr"] if evidence is None else
                  f"music delivery policy failed: LUFS residual {evidence['lufsResidual']}, "
                  f"true-peak excess {evidence['truePeakExcessDb']} dB")
        if result["ok"] and not comparison_bound:
            detail = "local signal comparison does not bind current candidate bytes"
        if result["ok"] and comparison_bound and not stable:
            detail = "audio delivery candidate bytes changed during whole-output qualification"
        retained = candidate if os.path.isfile(candidate) else None
        if not os.listdir(candidate_dir):
            os.rmdir(candidate_dir)
        return {**result, "ok": False, "stderr": detail, "published": False,
                "unapprovedCandidate": retained, "delivery": evidence,
                "comparisonBindingRequired": comparison_required,
                "comparisonCandidateBound": comparison_bound if comparison_required else None,
                "candidateStable": stable, "measuredCandidateSha256": before}
    with open(candidate, "rb") as handle:
        os.fsync(handle.fileno())
    os.replace(candidate, destination)
    os.rmdir(candidate_dir)
    return {**result, "published": True, "delivery": evidence,
            "comparisonBindingRequired": comparison_required,
            "comparisonCandidateBound": comparison_bound if comparison_required else None,
            "candidateStable": True, "measuredCandidateSha256": before}
