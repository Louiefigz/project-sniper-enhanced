"""Bound codec peak corrections using measured AAC, without relaxing delivery gates."""
from __future__ import annotations

import math
from dataclasses import replace

from audio.mastering_profile import MasteringProfile, require_matching_profile
from producer_config import AUDIO

AAC_PEAK_CANDIDATE_POLICY = {
    "schemaVersion": 1, "maximumCandidates": 3, "correctionMarginDb": 0.25,
    "minimumInternalTruePeakDbtp": -9.0, "source": "unchanged-lossless-premaster",
    "trigger": "fully-decoded-loudness-qualified-true-peak-only-AAC-failure",
}


def _finite(value: object) -> float:
    """Reject absent, boolean and nonfinite evidence instead of guessing peak headroom."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise RuntimeError("AAC peak correction requires finite numeric delivery evidence")
    return float(value)


def corrected_peak_profile(profile: MasteringProfile, delivery: dict,
                           completed_candidates: int) -> MasteringProfile:
    """Only a true-peak-only failure can consume one of the two bounded corrections."""
    if type(completed_candidates) is not int or not 1 <= completed_candidates < 3:
        raise RuntimeError("AAC peak candidate budget exhausted")
    if not isinstance(delivery, dict) or delivery.get("qualified") is not False \
            or delivery.get("audioDecodeSucceeded") is not True \
            or type(delivery.get("audioDecodeExitCode")) is not int \
            or delivery.get("audioDecodeExitCode") != 0 \
            or delivery.get("lufsWithinTolerance") is not True \
            or delivery.get("truePeakWithinCeiling") is not False:
        raise RuntimeError("AAC correction requires a true-peak-only delivery failure")
    integrated, peak = _finite(delivery.get("integratedLufs")), _finite(delivery.get("truePeakDbtp"))
    if abs(integrated - AUDIO["lufs_target"]) > AUDIO["lufs_tolerance"] \
            or peak <= AUDIO["true_peak_dbtp"]:
        raise RuntimeError("AAC peak correction evidence disagrees with shared delivery gates")
    excess = peak - AUDIO["true_peak_dbtp"]
    next_peak = round(profile.internal_true_peak_dbtp - excess
                      - AAC_PEAK_CANDIDATE_POLICY["correctionMarginDb"], 2)
    if next_peak < AAC_PEAK_CANDIDATE_POLICY["minimumInternalTruePeakDbtp"]:
        raise RuntimeError("AAC peak correction exceeds supported internal headroom")
    return replace(profile, internal_true_peak_dbtp=next_peak)


def _rejected_candidate_profile(profile: MasteringProfile, candidate: dict, index: int) -> MasteringProfile:
    """Require a completed rejected encode before interpreting its peak correction evidence."""
    if candidate.get("status") != "failed" or type(candidate.get("aacEncodesCompleted")) is not int \
            or candidate.get("aacEncodesCompleted") != 1:
        raise RuntimeError("Native dialogue reuse correction lacks a completed rejected AAC")
    return corrected_peak_profile(profile, candidate.get("delivery"), index)


def effective_reuse_profile(receipt: dict, requested: MasteringProfile) -> MasteringProfile:
    """Rebuild effective settings from exact candidate evidence, never from a profile label."""
    if "aacCandidatePolicy" not in receipt:
        if receipt.get("requestedMasteringProfile", requested.receipt()) != requested.receipt():
            raise RuntimeError("Native dialogue reuse requested mastering profile differs")
        require_matching_profile(receipt, requested)
        return requested
    if receipt.get("requestedMasteringProfile") != requested.receipt():
        raise RuntimeError("Native dialogue reuse requested mastering profile differs")
    if receipt.get("aacCandidatePolicy") != AAC_PEAK_CANDIDATE_POLICY:
        raise RuntimeError("Native dialogue reuse lacks the exact AAC candidate policy")
    candidates = receipt.get("aacCandidates")
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 3:
        raise RuntimeError("Native dialogue reuse candidate inventory is invalid")
    profile = requested
    for index, candidate in enumerate(candidates, 1):
        if not isinstance(candidate, dict) or type(candidate.get("candidateIndex")) is not int \
                or candidate.get("candidateIndex") != index \
                or candidate.get("inputPremasterSha256") != receipt.get("inputPremasterSha256") \
                or candidate.get("masteringProfile") != profile.receipt():
            raise RuntimeError("Native dialogue reuse effective candidate profile differs")
        if index < len(candidates):
            profile = _rejected_candidate_profile(profile, candidate, index)
    selected = candidates[-1]
    encoded_hash = receipt.get("encodingCandidateSha256")
    if receipt.get("aacCandidateOrigin") == "current-run" and encoded_hash != receipt.get("candidateSha256"):
        raise RuntimeError("Native dialogue reuse original encoded candidate binding differs")
    if receipt.get("aacCandidateOrigin") == "reused-qualified-audio" \
            and receipt.get("aacPacketsReused") is not True:
        raise RuntimeError("Native dialogue reuse has no exact AAC packet reuse proof")
    if receipt.get("aacCandidateOrigin") not in {"current-run", "reused-qualified-audio"}:
        raise RuntimeError("Native dialogue reuse candidate origin is unknown")
    if selected.get("status") != "audio-qualified" or selected.get("aacEncodesCompleted") != 1 \
            or selected.get("masterSha256") != receipt.get("masterSha256") \
            or selected.get("candidateSha256") != encoded_hash \
            or receipt.get("masteringProfile") != profile.receipt():
        raise RuntimeError("Native dialogue reuse selected candidate binding differs")
    return profile
