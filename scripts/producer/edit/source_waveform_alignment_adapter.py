#!/usr/bin/env python3
"""Deterministically locate an exact source span in a candidate waveform."""
from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import os
import re
import sys
import wave
from dataclasses import dataclass

_HASH = re.compile(r"^[0-9a-f]{64}$")
_JSON_LIMIT = 1024 * 1024


class AlignmentError(ValueError):
    """Pinned source-waveform inputs cannot produce bounded evidence."""


@dataclass(frozen=True)
class Policy:
    """Closed deterministic matching policy."""

    frame_samples: int
    hop_samples: int
    minimum_score_ppm: int
    peak_separation_ratio_ppm: int
    maximum_observation_samples: int


def _sha256(path: str, label: str) -> str:
    if os.path.abspath(path) != path or os.path.realpath(path) != path \
            or os.path.islink(path) or not os.path.isfile(path):
        raise AlignmentError(f"{label} path is not a canonical regular file")
    hasher = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _json(path: str, label: str) -> dict:
    if os.path.getsize(path) > _JSON_LIMIT:
        raise AlignmentError(f"{label} exceeds its size bound")
    with open(path, encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise AlignmentError(f"{label} is not an object")
    return value


def _integer(value: object, label: str, minimum: int) -> int:
    if type(value) is not int or value < minimum:
        raise AlignmentError(f"{label} is outside its integer bound")
    return value


def _policy(path: str) -> Policy:
    value = _json(path, "alignment policy")
    keys = {
        "schemaVersion", "kind", "frameSamples", "hopSamples",
        "minimumScorePpm", "peakSeparationRatioPpm",
        "maximumObservationSamples",
    }
    if set(value) != keys or value.get("schemaVersion") != 1 \
            or value.get("kind") != \
            "cut-repair-source-waveform-alignment-policy":
        raise AlignmentError("alignment policy contract is unsupported")
    frame = _integer(value["frameSamples"], "frameSamples", 64)
    hop = _integer(value["hopSamples"], "hopSamples", 1)
    score = _integer(value["minimumScorePpm"], "minimumScorePpm", 500_000)
    ratio = _integer(
        value["peakSeparationRatioPpm"], "peakSeparationRatioPpm", 100_000)
    limit = _integer(
        value["maximumObservationSamples"],
        "maximumObservationSamples", 48_000)
    released = (480, 240, 850_000, 500_000, 1_440_000)
    if (frame, hop, score, ratio, limit) != released:
        raise AlignmentError("alignment policy is not the released policy")
    return Policy(frame, hop, score, ratio, limit)


def _target(path: str) -> dict:
    value = _json(path, "alignment target")
    keys = {
        "schemaVersion", "kind", "protocol", "operationHash",
        "candidateSha256", "candidateWaveSha256", "referenceWaveSha256",
        "targetWordIds", "sourceId", "sourceMediaSha256",
        "sourceSampleRange", "sourceSampleRate", "projectSampleRate",
    }
    if set(value) != keys or value.get("schemaVersion") != 1 \
            or value.get("kind") != "cut-repair-alignment-target" \
            or value.get("protocol") != "deterministic-source-waveform-v1":
        raise AlignmentError("alignment target contract is unsupported")
    hashes = (
        value.get("operationHash"), value.get("candidateSha256"),
        value.get("candidateWaveSha256"), value.get("referenceWaveSha256"),
        value.get("sourceMediaSha256"),
    )
    if any(not isinstance(row, str) or not _HASH.fullmatch(row)
           for row in hashes):
        raise AlignmentError("alignment target hash binding is malformed")
    words = value.get("targetWordIds")
    if not isinstance(words, list) or not words \
            or any(not isinstance(row, str) or not row for row in words):
        raise AlignmentError("alignment target word binding is malformed")
    return value


def _wave_payload(path: str, rate: int, limit: int) -> bytes:
    with wave.open(path, "rb") as stream:
        shape = (
            stream.getnchannels(), stream.getsampwidth(),
            stream.getframerate(), stream.getcomptype())
        if shape != (1, 2, rate, "NONE"):
            raise AlignmentError("alignment WAV shape is unsupported")
        count = stream.getnframes()
        if count <= 0 or count > limit:
            raise AlignmentError("alignment WAV exceeds its sample bound")
        return stream.readframes(count)


def _wave(path: str, rate: int, limit: int) -> array.array:
    try:
        payload = _wave_payload(path, rate, limit)
    except (OSError, wave.Error) as exc:
        raise AlignmentError("alignment WAV is unreadable") from exc
    result = array.array("h")
    result.frombytes(payload)
    if sys.byteorder != "little":
        result.byteswap()
    return result


def _feature(samples: array.array, start: int, width: int) -> tuple[float, ...]:
    frame = samples[start:start + width]
    energy = sum(int(value) ** 2 for value in frame) / len(frame)
    differences = [
        int(frame[index]) - int(frame[index - 1])
        for index in range(1, len(frame))
    ]
    diff_energy = sum(value ** 2 for value in differences) / len(differences)
    crossings = sum(
        (frame[index] < 0) != (frame[index - 1] < 0)
        for index in range(1, len(frame)))
    return (
        math.log1p(math.sqrt(energy)),
        math.log1p(math.sqrt(diff_energy)),
        crossings / max(1, len(frame) - 1),
    )


def _features(samples: array.array, policy: Policy) -> list[tuple[float, ...]]:
    if len(samples) < policy.frame_samples:
        raise AlignmentError("reference span is too short for alignment")
    return [
        _feature(samples, start, policy.frame_samples)
        for start in range(
            0, len(samples) - policy.frame_samples + 1,
            policy.hop_samples)
    ]


def _scales(reference: list[tuple[float, ...]]) -> tuple[float, ...]:
    result = []
    for dimension in range(3):
        values = [row[dimension] for row in reference]
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        result.append(max(math.sqrt(variance), (0.01, 0.01, 0.002)[dimension]))
    return tuple(result)


def _score(
    reference: list[tuple[float, ...]],
    candidate: list[tuple[float, ...]],
    start: int,
    scales: tuple[float, ...],
) -> int:
    total = 0.0
    for index, expected in enumerate(reference):
        observed = candidate[start + index]
        total += sum(
            ((observed[dimension] - expected[dimension])
             / scales[dimension]) ** 2
            for dimension in range(3))
    error = total / (len(reference) * 3)
    return round(1_000_000 / (1.0 + error))


def _matches(
    reference: list[tuple[float, ...]],
    candidate: list[tuple[float, ...]],
    policy: Policy,
) -> tuple[list[tuple[int, int]], int]:
    if len(candidate) < len(reference):
        return [], 0
    scales = _scales(reference)
    scores = [
        (_score(reference, candidate, start, scales), start)
        for start in range(len(candidate) - len(reference) + 1)
    ]
    best = max((row[0] for row in scores), default=0)
    qualified = sorted(
        (row for row in scores if row[0] >= policy.minimum_score_ppm),
        reverse=True)
    separation = max(
        1, len(reference) * policy.peak_separation_ratio_ppm // 1_000_000)
    selected: list[tuple[int, int]] = []
    for row in qualified:
        if all(abs(row[1] - kept[1]) >= separation for kept in selected):
            selected.append(row)
    return sorted(selected, key=lambda row: row[1]), best


def _result(paths: argparse.Namespace) -> dict:
    policy = _policy(paths.policy)
    target = _target(paths.target)
    if _sha256(paths.audio, "candidate WAV") \
            != target["candidateWaveSha256"] \
            or _sha256(paths.reference, "reference WAV") \
            != target["referenceWaveSha256"]:
        raise AlignmentError("alignment WAV bytes do not match target authority")
    rate = _integer(
        target["projectSampleRate"], "projectSampleRate", 1)
    candidate = _wave(
        paths.audio, rate, policy.maximum_observation_samples)
    reference = _wave(
        paths.reference, rate, policy.maximum_observation_samples)
    matches, best = _matches(
        _features(reference, policy), _features(candidate, policy), policy)
    best_match = max(matches, default=None)
    return {
        "schemaVersion": 1,
        "kind": "cut-repair-independent-alignment-observation",
        "alignmentProtocol": "deterministic-source-waveform-v1",
        "evidenceSemantics":
            "transcript-bound-source-waveform-presence-not-audibility",
        "operationHash": target["operationHash"],
        "candidateSha256": target["candidateSha256"],
        "candidateWaveSha256": target["candidateWaveSha256"],
        "sourceMediaSha256": target["sourceMediaSha256"],
        "referenceWaveSha256": target["referenceWaveSha256"],
        "targetWordIds": target["targetWordIds"],
        "observedOccurrenceCount": len(matches),
        "sourceSpanBoundaryMatch": len(matches) == 1,
        "bestScorePpm": best,
        "minimumScorePpm": policy.minimum_score_ppm,
        "matchStartSampleInCandidateWindow":
            None if best_match is None else best_match[1] * policy.hop_samples,
        "boundaryToleranceSamples": policy.hop_samples,
        "referenceSampleCount": len(reference),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", required=True)
    parser.add_argument("--audio", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        value = _result(args)
        with open(args.output, "x", encoding="utf-8") as stream:
            json.dump(
                value, stream, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
