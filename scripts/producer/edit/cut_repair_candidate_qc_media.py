"""Bounded speech observers for full-plan cut-repair QC."""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

from edit.cut_repair_candidate_qc_types import (
    CandidateAuthority,
    CandidateQcContractError,
    QcTools,
)
from edit.cut_repair_context_sources import (
    digest,
    require_keys,
    stable_file_digest,
    stable_json,
)

_MAX_OBSERVATION_BYTES = 5 * 1024 * 1024


class CandidateQcLaneBlocker(ValueError):
    """One QC lane cannot issue a passing receipt."""

    def __init__(self, lane: str, code: str, message: str) -> None:
        super().__init__(message)
        self.lane = lane
        self.code = code
        self.message = message


@dataclass(frozen=True)
class TranscriptionObservation:
    """Bounded Whisper phrase observation."""

    occurrence_count: int
    word_order_preserved: bool
    target_phrase_hash: str


@dataclass(frozen=True)
class AlignmentObservation:
    """Independent transcript-bound source-waveform observation."""

    occurrence_count: int
    source_span_boundary_match: bool
    best_score_ppm: int
    minimum_score_ppm: int
    match_start_sample: int | None
    boundary_tolerance_samples: int
    reference_sample_count: int
    candidate_wave_sha256: str
    reference_wave_sha256: str


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


def _tokens(value: object) -> list[str]:
    result: list[str] = []
    current: list[str] = []
    for character in str(value).casefold():
        if character.isalnum():
            current.append(character)
            continue
        if current:
            result.append("".join(current))
            current = []
    return result + (["".join(current)] if current else [])


def _occurrences(haystack: list[str], needle: list[str]) -> int:
    if not needle:
        return 0
    return sum(
        haystack[index:index + len(needle)] == needle
        for index in range(0, len(haystack) - len(needle) + 1))


def _whisper_text(output_path: str) -> str:
    if os.path.getsize(output_path) > _MAX_OBSERVATION_BYTES:
        raise CandidateQcContractError("Whisper observation exceeds size bound")
    document, _ = stable_json(output_path, "bounded Whisper observation")
    rows = document.get("transcription")
    if not isinstance(rows, list) or any(
            not isinstance(row, dict) or not isinstance(row.get("text"), str)
            for row in rows):
        raise CandidateQcContractError("Whisper observation is malformed")
    return " ".join(row["text"] for row in rows)


def transcribe(
    wave_path: str,
    output_prefix: str,
    authority: CandidateAuthority,
    tools: QcTools,
) -> TranscriptionObservation:
    """Run CPU-only pinned Whisper on the bounded dirty-window WAV."""
    command = [
        tools.whisper.path, "-ng", "-m", tools.whisper_model.path,
        "-f", wave_path, "-l", "en", "-ojf", "-of", output_prefix,
        "-np", "-t", "4", "-tp", "0", "-nf",
    ]
    _run(command, "bounded Whisper retranscription", 600)
    observed = _tokens(_whisper_text(f"{output_prefix}.json"))
    target = _tokens(authority.target_phrase)
    count = _occurrences(observed, target)
    return TranscriptionObservation(
        count, count == 1,
        digest({
            "schemaVersion": 1, "kind": "cut-repair-target-phrase",
            "tokens": target,
        }),
    )


def _alignment_command(
    paths: tuple[str, str, str, str],
    tools: QcTools,
) -> list[str]:
    wave_path, reference_path, target_path, output_path = paths
    assert tools.aligner is not None
    return [
        tools.aligner.runtime.path, tools.aligner.implementation.path,
        "--policy", tools.aligner.policy.path, "--audio", wave_path,
        "--reference", reference_path,
        "--target", target_path, "--output", output_path,
    ]


def _assert_alignment_binding(
    observation: dict,
    paths: tuple[str, str, str, str],
    authority: CandidateAuthority,
) -> None:
    wave_path, reference_path, _, _ = paths
    expected = (
        1, "cut-repair-independent-alignment-observation",
        "deterministic-source-waveform-v1",
        "transcript-bound-source-waveform-presence-not-audibility",
        authority.descriptor["operationHash"], authority.candidate_sha256,
        stable_file_digest(wave_path, "candidate alignment WAV"),
        authority.source_media_sha256,
        stable_file_digest(reference_path, "reference alignment WAV"),
        list(authority.target_word_ids))
    observed = (
        observation.get("schemaVersion"), observation.get("kind"),
        observation.get("alignmentProtocol"),
        observation.get("evidenceSemantics"),
        observation.get("operationHash"), observation.get("candidateSha256"),
        observation.get("candidateWaveSha256"),
        observation.get("sourceMediaSha256"),
        observation.get("referenceWaveSha256"),
        observation.get("targetWordIds"))
    if observed != expected:
        raise CandidateQcContractError(
            "independent alignment observation is stale")


def _assert_alignment_verdict(observation: dict) -> None:
    occurrence = observation.get("observedOccurrenceCount")
    integers = (
        observation.get("bestScorePpm"),
        observation.get("minimumScorePpm"),
        observation.get("boundaryToleranceSamples"),
        observation.get("referenceSampleCount"),
    )
    match_start = observation.get("matchStartSampleInCandidateWindow")
    malformed = (
        type(occurrence) is not int or occurrence < 0
        or any(type(value) is not int or value < 0 for value in integers)
        or (match_start is not None
            and (type(match_start) is not int or match_start < 0))
        or type(observation.get("sourceSpanBoundaryMatch")) is not bool)
    if malformed:
        raise CandidateQcContractError(
            "independent alignment verdict is malformed")


def align(
    paths: tuple[str, str, str, str],
    authority: CandidateAuthority,
    tools: QcTools,
) -> AlignmentObservation:
    """Invoke the separately pinned source-waveform alignment adapter."""
    if tools.aligner is None:
        raise CandidateQcLaneBlocker(
            "alignment", "INDEPENDENT_ALIGNMENT_TOOL_UNAVAILABLE",
            "No separately pinned source-waveform adapter is configured; "
            "Whisper is not accepted as independent alignment evidence.")
    _, _, _, output_path = paths
    _run(
        _alignment_command(paths, tools),
        "independent source-waveform alignment", 600)
    observation, _ = stable_json(output_path, "alignment observation")
    keys = {
        "schemaVersion", "kind", "alignmentProtocol", "evidenceSemantics",
        "operationHash", "candidateSha256", "candidateWaveSha256",
        "sourceMediaSha256", "referenceWaveSha256", "targetWordIds",
        "observedOccurrenceCount", "sourceSpanBoundaryMatch",
        "bestScorePpm", "minimumScorePpm",
        "matchStartSampleInCandidateWindow", "boundaryToleranceSamples",
        "referenceSampleCount",
    }
    require_keys(observation, keys, keys, "alignment observation")
    _assert_alignment_binding(observation, paths, authority)
    _assert_alignment_verdict(observation)
    return AlignmentObservation(
        observation["observedOccurrenceCount"],
        observation["sourceSpanBoundaryMatch"],
        observation["bestScorePpm"],
        observation["minimumScorePpm"],
        observation["matchStartSampleInCandidateWindow"],
        observation["boundaryToleranceSamples"],
        observation["referenceSampleCount"],
        observation["candidateWaveSha256"],
        observation["referenceWaveSha256"],
    )


def target_document(
    authority: CandidateAuthority,
    wave_hashes: tuple[str, str],
) -> dict:
    """Closed target input passed to the independent aligner adapter."""
    return {
        "schemaVersion": 1,
        "kind": "cut-repair-alignment-target",
        "protocol": "deterministic-source-waveform-v1",
        "operationHash": authority.descriptor["operationHash"],
        "candidateSha256": authority.candidate_sha256,
        "candidateWaveSha256": wave_hashes[0],
        "referenceWaveSha256": wave_hashes[1],
        "targetWordIds": list(authority.target_word_ids),
        "sourceId": authority.source_id,
        "sourceMediaSha256": authority.source_media_sha256,
        "sourceSampleRange": {
            "startSample": authority.source_start_sample,
            "endSampleExclusive": authority.source_end_sample_exclusive,
        },
        "sourceSampleRate": authority.source_sample_rate,
        "projectSampleRate": authority.window.sample_rate,
    }
