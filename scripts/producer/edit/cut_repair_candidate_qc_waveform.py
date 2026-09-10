"""Bounded FFmpeg extraction and deterministic program-waveform QC."""
from __future__ import annotations

import array
import math
import os
import statistics
import subprocess
import sys
import wave
from dataclasses import dataclass

from edit.cut_repair_candidate_qc_types import (
    CandidateAuthority,
    CandidateQcContractError,
    QcTools,
)
from edit.cut_repair_context_sources import digest, stable_file_digest

_BIN_S = 0.01
_GAP_S = 0.15
_SEAM_S = 0.02


@dataclass(frozen=True)
class WaveformObservation:
    """Program-waveform continuity and seam measurements."""

    unintended_gap_count: int
    click_free: bool
    duplicate_free: bool
    room_tone_continuous: bool
    runtime_sha256: str


def _run(command: list[str], label: str, timeout: int) -> None:
    try:
        result = subprocess.run(
            command, stdin=subprocess.DEVNULL, capture_output=True,
            text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CandidateQcContractError(f"{label} failed to execute") from exc
    if result.returncode != 0:
        detail = result.stderr.strip()[-1000:]
        raise CandidateQcContractError(
            f"{label} failed ({result.returncode}): {detail}")


def extract_dirty_wave(
    authority: CandidateAuthority,
    tools: QcTools,
    output_path: str,
) -> None:
    """Decode only the dirty interval plus its fixed one-second handles."""
    window = authority.window
    start = f"{window.start_sample / window.sample_rate:.9f}"
    duration = (
        window.end_sample_exclusive - window.start_sample
    ) / window.sample_rate
    command = [
        tools.ffmpeg.path, "-nostdin", "-hide_banner", "-loglevel", "error",
        "-i", authority.candidate_path, "-ss", start,
        "-t", f"{duration:.9f}", "-map", "0:a:0", "-vn", "-ac", "1",
        "-ar", str(window.sample_rate), "-c:a", "pcm_s16le",
        "-bitexact", "-y", output_path,
    ]
    _run(command, "bounded FFmpeg QC extraction", 120)


def extract_source_target_wave(
    authority: CandidateAuthority,
    tools: QcTools,
    output_path: str,
) -> None:
    """Decode the exact admitted transcript-bound source sample span."""
    if stable_file_digest(
            authority.source_media_path, "alignment source media") \
            != authority.source_media_sha256:
        raise CandidateQcContractError(
            "alignment source media bytes are stale")
    audio_filter = (
        f"atrim=start_sample={authority.source_start_sample}:"
        f"end_sample={authority.source_end_sample_exclusive},"
        f"asetpts=PTS-STARTPTS,aresample={authority.window.sample_rate}"
    )
    command = [
        tools.ffmpeg.path, "-nostdin", "-hide_banner", "-loglevel", "error",
        "-i", authority.source_media_path, "-map", "0:a:0", "-vn",
        "-af", audio_filter, "-ac", "1",
        "-ar", str(authority.window.sample_rate), "-c:a", "pcm_s16le",
        "-bitexact", "-y", output_path,
    ]
    _run(command, "exact source-waveform extraction", 120)
    if stable_file_digest(
            authority.source_media_path, "alignment source media") \
            != authority.source_media_sha256:
        raise CandidateQcContractError(
            "alignment source media changed during extraction")


def _wave_payload(path: str, expected_rate: int) -> bytes:
    with wave.open(path, "rb") as stream:
        observed = (
            stream.getnchannels(), stream.getsampwidth(),
            stream.getframerate(), stream.getcomptype())
        if observed != (1, 2, expected_rate, "NONE"):
            raise CandidateQcContractError(
                "FFmpeg QC extraction is not mono PCM16 at project rate")
        return stream.readframes(stream.getnframes())


def _wave_samples(path: str, expected_rate: int) -> array.array:
    try:
        payload = _wave_payload(path, expected_rate)
    except (OSError, wave.Error) as exc:
        raise CandidateQcContractError(
            "FFmpeg QC extraction is unreadable") from exc
    samples = array.array("h")
    samples.frombytes(payload)
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        raise CandidateQcContractError("FFmpeg QC extraction is empty")
    return samples


def _rms(values: array.array | list[int]) -> float:
    if not values:
        return 0.0
    return math.sqrt(sum(int(value) ** 2 for value in values) / len(values))


def _gap_count(samples: array.array, rate: int) -> int:
    width = max(1, round(rate * _BIN_S))
    energies = [_rms(samples[offset:offset + width])
                for offset in range(0, len(samples), width)]
    threshold = max(48.0, max(energies) * 0.015)
    minimum = max(1, round(_GAP_S / _BIN_S))
    gaps, run = 0, 0
    for energy in energies[10:-10]:
        if energy < threshold:
            run += 1
        else:
            gaps += int(run >= minimum)
            run = 0
    return gaps + int(run >= minimum)


def _row_seams(row: dict, authority: CandidateAuthority) -> list[int]:
    window = authority.window
    positions = []
    for key in ("startFrame", "endFrameExclusive"):
        if row[key] <= 0 or row[key] >= authority.total_frames:
            continue
        absolute = (
            row[key] * window.fps_denominator * window.sample_rate
            // window.fps_numerator
        )
        relative = absolute - window.start_sample
        if 0 < relative < (
                window.end_sample_exclusive - window.start_sample):
            positions.append(relative)
    return positions


def _seam_samples(authority: CandidateAuthority) -> list[int]:
    rows = authority.operation["audioDirtyWindows"]
    positions: set[int] = set()
    for row in rows:
        positions.update(_row_seams(row, authority))
    return sorted(positions)


def _local_threshold(samples: array.array, position: int, width: int) -> float:
    start = max(1, position - width)
    end = min(len(samples), position + width)
    differences = [
        abs(samples[index] - samples[index - 1])
        for index in range(start, end)
    ]
    return max(2048.0, statistics.median(differences or [0]) * 12.0)


def _click_free(samples: array.array, seams: list[int], rate: int) -> bool:
    width = max(1, round(rate * _SEAM_S))
    return all(
        abs(samples[position] - samples[position - 1])
        <= _local_threshold(samples, position, width)
        for position in seams if 0 < position < len(samples))


def _duplicate_free(samples: array.array, seams: list[int], rate: int) -> bool:
    width = max(1, round(rate * _SEAM_S))
    for position in seams:
        before = samples[max(0, position - width):position]
        after = samples[position:min(len(samples), position + width)]
        paired = min(len(before), len(after))
        if paired == width and before[-paired:] == after[:paired] \
                and _rms(before) >= 64:
            return False
    return True


def _room_tone(samples: array.array, seams: list[int], rate: int) -> bool:
    width = max(1, round(rate * 0.04))
    for position in seams:
        if position <= 0 or position >= len(samples):
            continue
        before = _rms(samples[max(0, position - width):position])
        after = _rms(samples[position:min(len(samples), position + width)])
        quiet, loud = min(before, after), max(before, after)
        if loud >= 128 and (quiet < 1 or loud / quiet > 6):
            return False
    return True


def _runtime_hash(tools: QcTools) -> str:
    implementation = stable_file_digest(
        os.path.realpath(__file__), "candidate QC waveform implementation")
    return digest({
        "kind": "cut-repair-program-waveform-runtime-v1",
        "implementationSha256": implementation,
        "ffmpegSha256": tools.ffmpeg.sha256,
        "binSeconds": _BIN_S,
        "gapSeconds": _GAP_S,
        "seamSeconds": _SEAM_S,
    })


def waveform_observation(
    path: str,
    authority: CandidateAuthority,
    tools: QcTools,
) -> WaveformObservation:
    """Measure deterministic continuity/click/duplication bounds."""
    samples = _wave_samples(path, authority.window.sample_rate)
    seams = _seam_samples(authority)
    return WaveformObservation(
        _gap_count(samples, authority.window.sample_rate),
        _click_free(samples, seams, authority.window.sample_rate),
        _duplicate_free(samples, seams, authority.window.sample_rate),
        _room_tone(samples, seams, authority.window.sample_rate),
        _runtime_hash(tools),
    )
