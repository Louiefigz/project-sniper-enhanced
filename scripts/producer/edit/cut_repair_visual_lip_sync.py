"""Deterministic selected-source A/V mapping oracle for visible speech."""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Sequence, TypeVar

from edit.cut_repair_context_sources import (
    digest,
    require_hash,
    require_keys,
    stable_file_digest,
    stable_json,
)
from edit.cut_repair_visual_lip_sync_media import decode_evidence
from edit.cut_repair_visual_lip_sync_receipt import build_visual_receipt
from edit.cut_repair_visual_lip_sync_types import (
    DecodedEvidence,
    OracleRequest,
    RationalRate,
    VISUAL_IMPLEMENTATION_NONCLAIMS,
    VISUAL_IMPLEMENTATION_ROLES,
    VISUAL_IMPLEMENTATION_SCOPE,
    VisualLipSyncBlocker,
)

_POLICY_KEYS = {
    "schemaVersion", "kind", "protocol", "analysisAudioRate",
    "analysisFrameWidth", "analysisFrameHeight", "maximumSearchOffsetFrames",
    "maximumMappingOffsetFrames", "maximumAvOffsetFrames",
    "minimumComparedFrames", "minimumVisualDynamicPpm",
    "minimumVisualScorePpm", "minimumAudioScorePpm",
    "minimumVisualPeakSeparationPpm", "minimumAudioPeakSeparationPpm",
}
_T = TypeVar("_T")
@dataclass(frozen=True)
class _Peak:
    """One unique best mapping lag."""

    offset: int
    score_ppm: int
    separation_ppm: int
    compared: int


def _policy(request: OracleRequest) -> dict:
    value, raw_hash = stable_json(
        request.tools.policy_path, "visual lip-sync policy")
    require_keys(value, _POLICY_KEYS, _POLICY_KEYS, "visual lip-sync policy")
    integers = [value[key] for key in _POLICY_KEYS if key not in {
        "kind", "protocol"}]
    if raw_hash != request.tools.policy_sha256 \
            or value.get("schemaVersion") != 1 \
            or value.get("kind") != "cut-repair-visual-lip-sync-policy" \
            or value.get("protocol") \
            != "deterministic-selected-source-av-offset-v1" \
            or any(type(item) is not int or item <= 0 for item in integers):
        raise VisualLipSyncBlocker(
            "VISUAL_ORACLE_POLICY_REJECTED",
            "visual lip-sync policy is stale or malformed")
    return value


def _reobserve(request: OracleRequest) -> None:
    files = (
        (request.selection.source_path, request.selection.source_sha256),
        (request.candidate.path, request.candidate.sha256),
        (request.tools.ffmpeg_path, request.tools.ffmpeg_sha256),
        (request.tools.runtime_path, request.tools.runtime_sha256),
        (request.tools.implementation_path,
         request.tools.implementation_sha256),
        (request.tools.policy_path, request.tools.policy_sha256),
    ) + tuple(
        (path, value_hash) for _, path, value_hash
        in request.tools.implementation_files)
    for path, expected in files:
        if os.path.realpath(path) != path or os.path.islink(path) \
                or stable_file_digest(path, "visual oracle input") != expected:
            raise VisualLipSyncBlocker(
                "VISUAL_ORACLE_INPUT_DRIFT",
                "visual lip-sync input or tool bytes changed")


def _require_tool_closure(request: OracleRequest) -> None:
    rows = [
        {"role": role, "path": path, "sha256": value_hash}
        for role, path, value_hash in request.tools.implementation_files]
    observed_roles = tuple(row["role"] for row in rows)
    controller = rows[0] if rows else {}
    expected = (
        request.tools.implementation_path,
        request.tools.implementation_sha256)
    actual = (controller.get("path"), controller.get("sha256"))
    if observed_roles != VISUAL_IMPLEMENTATION_ROLES or actual != expected \
            or request.tools.implementation_scope \
            != VISUAL_IMPLEMENTATION_SCOPE \
            or request.tools.implementation_nonclaims \
            != VISUAL_IMPLEMENTATION_NONCLAIMS \
            or digest(rows) != request.tools.implementation_closure_hash:
        raise VisualLipSyncBlocker(
            "VISUAL_ORACLE_TOOL_CLOSURE_REJECTED",
            "visual oracle implementation closure is stale or incomplete")


def _paired(
    source: Sequence[_T],
    candidate: Sequence[_T],
    offset: int,
) -> tuple[Sequence[_T], Sequence[_T]]:
    if offset >= 0:
        end = min(len(source), len(candidate) - offset)
        return source[:max(0, end)], candidate[offset:offset + max(0, end)]
    start = -offset
    end = min(len(source) - start, len(candidate))
    return source[start:start + max(0, end)], candidate[:max(0, end)]


def _visual_score(
    source: Sequence[bytes],
    candidate: Sequence[bytes],
    offset: int,
) -> tuple[int, int]:
    left, right = _paired(source, candidate, offset)
    if not left:
        return -1, 0
    difference = sum(
        abs(a - b)
        for source_frame, candidate_frame in zip(left, right)
        for a, b in zip(source_frame, candidate_frame))
    pixels = sum(len(frame) for frame in left)
    score = 1_000_000 - difference * 1_000_000 // (255 * pixels)
    return score, len(left)


def _rounded_samples(offset: int, rate: RationalRate, sample_rate: int) -> int:
    numerator = abs(offset) * sample_rate * rate.denominator
    value = (numerator + rate.numerator // 2) // rate.numerator
    return value if offset >= 0 else -value


def _correlation(source: Sequence[int], candidate: Sequence[int]) -> int:
    if len(source) < 2 or len(source) != len(candidate):
        return -1
    step = max(1, len(source) // 30_000)
    left = source[::step]
    right = candidate[::step]
    left_mean = math.fsum(left) / len(left)
    right_mean = math.fsum(right) / len(right)
    covariance = math.fsum(
        (a - left_mean) * (b - right_mean)
        for a, b in zip(left, right))
    left_energy = math.fsum((item - left_mean) ** 2 for item in left)
    right_energy = math.fsum((item - right_mean) ** 2 for item in right)
    if left_energy <= 0 or right_energy <= 0:
        return -1
    value = covariance / math.sqrt(left_energy * right_energy)
    return round(max(-1.0, min(1.0, value)) * 1_000_000)


def _audio_score(
    evidence: DecodedEvidence,
    offset: int,
    rate: RationalRate,
    sample_rate: int,
) -> tuple[int, int]:
    shifted = _rounded_samples(offset, rate, sample_rate)
    left, right = _paired(
        evidence.source_pcm, evidence.candidate_pcm, shifted)
    return _correlation(left, right), len(left)


def _peak(
    rows: list[tuple[int, int, int]],
    minimum_score: int,
    minimum_separation: int,
    code: str,
) -> _Peak:
    ranked = sorted(rows, key=lambda row: (row[1], -abs(row[0])), reverse=True)
    if len(ranked) < 2 or ranked[0][1] < minimum_score:
        raise VisualLipSyncBlocker(
            code, "selected-source mapping was not measurable")
    separation = ranked[0][1] - ranked[1][1]
    if separation < minimum_separation:
        raise VisualLipSyncBlocker(
            "VISUAL_ORACLE_AMBIGUOUS_MAPPING",
            "selected-source mapping has no unique offset")
    return _Peak(ranked[0][0], ranked[0][1], separation, ranked[0][2])


def _visual_dynamic_ppm(frames: Sequence[bytes]) -> int:
    if len(frames) < 2:
        return 0
    difference = sum(
        abs(a - b)
        for left, right in zip(frames, frames[1:])
        for a, b in zip(left, right))
    pixels = (len(frames) - 1) * len(frames[0])
    return difference * 1_000_000 // (255 * pixels)


def _measure(
    evidence: DecodedEvidence,
    policy: dict,
    rate: RationalRate,
) -> tuple[_Peak, _Peak, int]:
    search = range(
        -policy["maximumSearchOffsetFrames"],
        policy["maximumSearchOffsetFrames"] + 1)
    visual_rows = [
        (offset, *_visual_score(
            evidence.source_frames, evidence.candidate_frames, offset))
        for offset in search]
    audio_rows = [
        (offset, *_audio_score(
            evidence, offset, rate, policy["analysisAudioRate"]))
        for offset in search]
    visual = _peak(
        visual_rows, policy["minimumVisualScorePpm"],
        policy["minimumVisualPeakSeparationPpm"],
        "VISUAL_SPEECH_OCCLUDED_OR_SUBSTITUTED")
    audio = _peak(
        audio_rows, policy["minimumAudioScorePpm"],
        policy["minimumAudioPeakSeparationPpm"],
        "SELECTED_SPEECH_AUDIO_UNMEASURABLE")
    return visual, audio, audio.offset - visual.offset


def _require_pass(
    visual: _Peak,
    audio: _Peak,
    av_offset: int,
    policy: dict,
) -> None:
    if visual.compared < policy["minimumComparedFrames"]:
        raise VisualLipSyncBlocker(
            "VISUAL_ORACLE_UNMEASURABLE",
            "too few uncovered selected-source frames were compared")
    if abs(av_offset) > policy["maximumAvOffsetFrames"]:
        raise VisualLipSyncBlocker(
            "VISIBLE_SPEECH_AV_OFFSET",
            "selected-source audio and visible speech have different offsets")
    mapping = policy["maximumMappingOffsetFrames"]
    if abs(visual.offset) > mapping or abs(audio.offset) > mapping:
        raise VisualLipSyncBlocker(
            "SELECTED_RANGE_MAPPING_DRIFT",
            "selected source did not land at the authorized output range")


def qualify_visual_lip_sync(request: OracleRequest) -> dict:
    """Issue a pass only for unique, uncovered selected-source A/V mapping."""
    require_hash(request.tool_manifest_hash, "visual oracle tool manifest")
    require_hash(
        request.tools.implementation_closure_hash,
        "visual oracle implementation closure")
    _require_tool_closure(request)
    _reobserve(request)
    policy = _policy(request)
    evidence = decode_evidence(request, policy)
    dynamic = _visual_dynamic_ppm(evidence.source_frames)
    if dynamic < policy["minimumVisualDynamicPpm"]:
        raise VisualLipSyncBlocker(
            "VISUAL_ORACLE_UNMEASURABLE",
            "selected visible-speech region has insufficient motion")
    visual, audio, av_offset = _measure(
        evidence, policy, request.selection.output_rate)
    _require_pass(visual, audio, av_offset, policy)
    _reobserve(request)
    measurements = {
        "visibleUncoveredFrameCount": visual.compared,
        "visualDynamicPpm": dynamic,
        "visualScorePpm": visual.score_ppm,
        "visualPeakSeparationPpm": visual.separation_ppm,
        "audioScorePpm": audio.score_ppm,
        "audioPeakSeparationPpm": audio.separation_ppm,
        "visualMappingOffsetFrames": visual.offset,
        "audioMappingOffsetFrames": audio.offset,
        "avOffsetFrames": av_offset,
    }
    return build_visual_receipt(request, evidence, policy, measurements)
