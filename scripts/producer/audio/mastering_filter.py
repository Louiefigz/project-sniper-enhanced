"""Shared linear/static/dynamic mastering DSP with explicit immutable settings."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

from audio.mastering_profile import LEGACY_MASTERING_PROFILE, MasteringProfile
from producer_config import AUDIO

STATIC_MIN_I = -50.0
STATIC_TRIM_TOL_LU = 0.10


@dataclass(frozen=True)
class MasterFilterInput:
    """Source measurement, prefix and exact-program dry-run callback for one filter."""

    prefix: str | None
    measured: dict | None
    measure_chain: Callable[[str], float | None]
    profile: MasteringProfile = LEGACY_MASTERING_PROFILE


@dataclass(frozen=True)
class MasterFilterSelection:
    """Actual DSP choice and observations; never delivery or listening approval."""

    chain: str
    note: str | None
    evidence: dict


def _decision(source: MasterFilterInput, branch: str, chain: str, details: dict) -> dict:
    """Retain machine-readable choices without another measurement or DSP pass."""
    return {"schemaVersion": 1, "kind": "mastering-decision",
            "scope": "processing-observation-not-delivery-approval", "branch": branch,
            "filter": chain, "profile": source.profile.receipt(),
            "inputStatistics": _parse_stats(source.measured),
            "targetIntegratedLufs": AUDIO["lufs_target"],
            "staticTrimToleranceLu": STATIC_TRIM_TOL_LU, "gainDb": None,
            "dryRuns": [], "convergence": "not-applicable", **details}


def with_prefix(prefix: str | None, afilter: str) -> str:
    """Prepend an optional caller-owned channel filter without changing it."""
    return f"{prefix},{afilter}" if prefix else afilter


def _finite(value: object) -> float | None:
    """Parse a finite loudnorm measurement, rejecting silent/degenerate statistics."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _parse_stats(measured: dict | None) -> dict | None:
    """Convert complete pass-one statistics into loudnorm measured options."""
    if measured is None:
        return None
    stats = {"measured_I": _finite(measured.get("input_i")),
        "measured_TP": _finite(measured.get("input_tp")),
        "measured_LRA": _finite(measured.get("input_lra")),
        "measured_thresh": _finite(measured.get("input_thresh")),
        "offset": _finite(measured.get("target_offset"))}
    return None if any(value is None for value in stats.values()) else stats


def _loudnorm_stats_in_range(stats: dict) -> bool:
    """Finite float headroom can exceed loudnorm's measured-option domains."""
    bounds = {"measured_I": (-99, 0), "measured_TP": (-99, 99),
        "measured_LRA": (0, 99), "measured_thresh": (-99, 0), "offset": (-99, 99)}
    return all(low <= stats[key] <= high for key, (low, high) in bounds.items())


def _linear_eligible(stats: dict, profile: MasteringProfile) -> bool:
    """Avoid loudnorm's silent linear-to-dynamic fallback for peaks, LRA or sentinel stats."""
    if not _loudnorm_stats_in_range(stats):
        return False
    projected_tp = stats["measured_TP"] + (AUDIO["lufs_target"] - stats["measured_I"])
    sentinel = (stats["measured_thresh"] <= -70.0 or stats["measured_TP"] >= 99.0
                or stats["measured_LRA"] == 0.0 or stats["measured_I"] == 0.0)
    return (not sentinel and projected_tp <= profile.internal_true_peak_dbtp
            and stats["measured_LRA"] <= AUDIO["lra"])


def _tp_limiter(profile: MasteringProfile) -> str:
    """Retain the existing oversampled, latency-compensated limiter without auto-level gain."""
    limit = 10.0 ** (profile.internal_true_peak_dbtp / 20.0)
    return (f"aresample=192000,alimiter=limit={limit:.6f}"
            f":attack=5:release=100:level=false:latency=true")


def _static_chain(prefix: str | None, gain_db: float, profile: MasteringProfile) -> str:
    """Use the same fixed-gain and peak-limiter chain for every delivery profile."""
    return with_prefix(prefix, f"volume={gain_db:.2f}dB,{_tp_limiter(profile)}")


def _static_gain_filter(source: MasterFilterInput, measured_i: float) -> tuple[str, float, dict]:
    """Trim fixed gain against the exact program within the explicit bounded dry-run budget."""
    gain = AUDIO["lufs_target"] - measured_i
    chain = _static_chain(source.prefix, gain, source.profile)
    runs: list[dict] = []
    convergence = "budget-exhausted"
    for _ in range(source.profile.maximum_static_dry_runs):
        got = source.measure_chain(chain)
        runs.append({"filter": chain, "gainDb": round(gain, 2), "integratedLufs": got})
        if got is None:
            convergence = "measurement-unavailable"
            break
        if abs(AUDIO["lufs_target"] - got) <= STATIC_TRIM_TOL_LU:
            convergence = "converged"
            break
        gain += AUDIO["lufs_target"] - got
        chain = _static_chain(source.prefix, gain, source.profile)
    details = {"gainDb": round(gain, 2), "dryRuns": runs, "convergence": convergence,
               "selectedFilterMeasured": bool(runs and runs[-1]["filter"] == chain
                                               and runs[-1]["integratedLufs"] is not None)}
    return chain, round(gain, 2), details


def select_master_filter(source: MasterFilterInput) -> MasterFilterSelection:
    """Keep existing DSP exact while recording its selected branch and measured gain."""
    peak = source.profile.internal_true_peak_dbtp
    base = f"loudnorm=I={AUDIO['lufs_target']}:TP={peak}:LRA={AUDIO['lra']}"
    stats = _parse_stats(source.measured)
    if stats is None or stats["measured_I"] < STATIC_MIN_I:
        chain = with_prefix(source.prefix, f"{base}:print_format=summary")
        note = ("loudnorm fell back to dynamic (input stats non-finite or "
                "near-silent; e.g. synthetic audio)")
        return MasterFilterSelection(chain, note, _decision(source, "dynamic", chain, {}))
    if _linear_eligible(stats, source.profile):
        part = ":".join(f"{key}={value}" for key, value in stats.items())
        chain = with_prefix(source.prefix, f"{base}:{part}:linear=true:print_format=summary")
        return MasterFilterSelection(chain, None, _decision(source, "linear", chain, {}))
    chain, gain, details = _static_gain_filter(source, stats["measured_I"])
    projected_tp = stats["measured_TP"] + (AUDIO["lufs_target"] - stats["measured_I"])
    note = (f"loudnorm linear ineligible (stats/range or projected TP "
            f"{projected_tp:+.1f}; ceiling {peak}) — static "
            f"gain {gain:+.1f} dB + true-peak limiter (LRA preserved)")
    return MasterFilterSelection(chain, note, _decision(source, "static", chain, details))


def build_master_filter(source: MasterFilterInput) -> tuple[str, str | None]:
    """Preserve the public tuple API for callers that only need the DSP filter."""
    selected = select_master_filter(source)
    return selected.chain, selected.note
