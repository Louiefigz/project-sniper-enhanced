"""Bind native AAC options to encoding and reuse without changing shared DSP.

Perceptual noise substitution failed a local first-channel fidelity gate on a
retained master. Disabling it passed repeated exact-master comparisons while
leaving mid/side stereo at the pinned encoder's default. Ordinary long-form
callers retain their existing options until separately qualified.
"""
from __future__ import annotations

from audio.mastering_profile import MasteringProfile


def native_aac_encoding_policy(profile: MasteringProfile) -> dict:
    """Return fresh explicit arguments; the owner separately pins the FFmpeg binary.

    Only encoding behavior belongs here. Source sample filters, mastering,
    container clocks and independent output gates remain with their owners.
    """
    if not isinstance(profile, MasteringProfile):
        raise ValueError("Native AAC encoding requires a validated mastering profile")
    return {"schemaVersion": 1, "kind": "native-aac-encoding",
        "unspecifiedOptions": "pinned-ffmpeg-defaults",
        "arguments": ["-c:a", "aac", "-b:a", profile.audio_bitrate,
            "-ar", "48000", "-ac", "2", "-aac_pns", "0"]}


def native_aac_arguments(profile: MasteringProfile, receipt: dict) -> list[str]:
    """Record the exact option vector consumed by this encoder invocation.

    The caller records attempted and completed encodes separately, so a failed
    invocation cannot masquerade as a completed candidate from this policy.
    """
    policy = native_aac_encoding_policy(profile)
    receipt["aacEncodingPolicy"] = policy
    return list(policy["arguments"])


def _require_matching_policy(actual: object, expected: dict) -> None:
    """Reject absent, stale or malformed policy instead of inferring encoder defaults."""
    if not isinstance(actual, dict) or type(actual.get("schemaVersion")) is not int \
            or actual != expected:
        raise RuntimeError("Native dialogue reuse lacks the exact AAC encoding policy; encode fresh audio")


def require_native_aac_policy(receipt: dict, profile: MasteringProfile) -> dict:
    """Bind donor and candidate history to the actual required encoder arguments.

    This complements effective-profile, source hash, packet and delivery checks;
    an option record alone cannot establish encoded fidelity or source truth.
    Historical donors missing this policy must be freshly encoded.
    """
    expected = native_aac_encoding_policy(profile)
    _require_matching_policy(receipt.get("aacEncodingPolicy"), expected)
    if "aacCandidatePolicy" not in receipt:
        return expected
    candidates = receipt.get("aacCandidates")
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 3:
        raise RuntimeError("Native dialogue reuse AAC encoding history is invalid")
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise RuntimeError("Native dialogue reuse AAC encoding candidate is malformed")
        _require_matching_policy(candidate.get("aacEncodingPolicy"), expected)
    return expected
