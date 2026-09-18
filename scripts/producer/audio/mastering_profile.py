"""Immutable audio settings and receipt identity for shared mastering and AAC delivery."""
from __future__ import annotations

import math
from dataclasses import dataclass

from producer_config import AUDIO, ENCODE, MASTERING_POLICY_VERSION


@dataclass(frozen=True)
class MasteringProfile:
    """Explicit processing settings; final delivery gates remain independent and unchanged."""

    identity: str
    internal_true_peak_dbtp: float
    maximum_static_dry_runs: int
    audio_bitrate: str

    def __post_init__(self) -> None:
        """Keep profiles finite, bounded and within the supported AAC settings."""
        peak = self.internal_true_peak_dbtp
        if not isinstance(self.identity, str) or not self.identity:
            raise ValueError("Mastering profile requires an identity")
        if type(peak) not in {int, float} or not math.isfinite(peak) or not -9 <= peak <= -1.5:
            raise ValueError("Mastering profile requires supported internal peak headroom")
        if type(self.maximum_static_dry_runs) is not int or not 1 <= self.maximum_static_dry_runs <= 6:
            raise ValueError("Mastering profile dry-run budget must be between one and six")
        if self.audio_bitrate not in {"256k", "320k"}:
            raise ValueError("Mastering profile AAC bitrate is unsupported")

    def receipt(self) -> dict:
        """Bind both named identity and complete consumed settings in an audio receipt."""
        return {"identity": self.identity, "internalTruePeakDbtp": self.internal_true_peak_dbtp,
            "maximumStaticDryRuns": self.maximum_static_dry_runs, "audioBitrate": self.audio_bitrate}


LEGACY_MASTERING_PROFILE = MasteringProfile(
    "default-v3", AUDIO["loudnorm_tp_param"], 2, ENCODE["audio_bitrate"])
NATIVE_SHORT_MASTERING_PROFILE = MasteringProfile("native-short-v1", -2.5, 6, "320k")
MASTERING_PROFILE_IDENTITIES = (NATIVE_SHORT_MASTERING_PROFILE.identity, LEGACY_MASTERING_PROFILE.identity)


def resolve_mastering_profile(identity: str) -> MasteringProfile:
    """Resolve only the two explicit supported profiles; never infer settings from a donor."""
    for profile in (NATIVE_SHORT_MASTERING_PROFILE, LEGACY_MASTERING_PROFILE):
        if identity == profile.identity:
            return profile
    raise ValueError("Unknown audio mastering profile")


def require_matching_profile(receipt: dict, requested: MasteringProfile) -> None:
    """Legacy receipts may serve only the old default, never silently inherit native settings."""
    if "masteringProfile" not in receipt:
        if requested == LEGACY_MASTERING_PROFILE \
                and receipt.get("masteringPolicyVersion") == MASTERING_POLICY_VERSION:
            return
        raise RuntimeError("Native dialogue reuse lacks the requested mastering profile")
    if receipt["masteringProfile"] != requested.receipt():
        raise RuntimeError("Native dialogue reuse mastering profile differs from the request")
