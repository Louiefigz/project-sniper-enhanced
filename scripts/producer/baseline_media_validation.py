#!/usr/bin/env python3
"""Validate per-run decoded media, exact PCM, QC, and execution state."""
from __future__ import annotations

from fractions import Fraction
from typing import Any

from baseline_validation_common import (
    SHA256,
    document_sha256,
    valid_media_tools,
)


def _complete(runs: list[dict[str, Any]]) -> bool:
    return all(
        output.get("status") == "present"
        for run in runs for output in run.get("outputs", [])
    )


def _audit_passes(fixture: dict[str, Any], value: object) -> bool:
    if not isinstance(value, dict):
        return False
    document = value.get("document")
    if not isinstance(document, dict):
        return False
    checks = document.get("checks")
    counts = document.get("counts")
    if not isinstance(checks, list) or not checks or not isinstance(counts, dict):
        return False
    observed = {
        status: sum(
            isinstance(row, dict) and row.get("status") == status
            for row in checks
        )
        for status in ("pass", "warn", "fail")
    }
    return (
        SHA256.fullmatch(str(value.get("sha256"))) is not None
        and value.get("documentSha256") == document_sha256(document)
        and counts == observed
        and observed["fail"] == 0
        and document.get("exitCode") == 0
        and document.get("overall") in {"pass", "warn"}
        and document.get("mode") == fixture["mode"]
    )


def _qc_matches_fixture(
    fixture: dict[str, Any],
    output: dict[str, Any],
    media: dict,
) -> bool:
    qc = media.get("qc")
    if not isinstance(qc, dict):
        return False
    assembled = qc.get("assembledAuthority")
    plan = qc.get("renderPlan")
    timeline = qc.get("timelineMap")
    if not all(isinstance(row, dict) for row in (assembled, plan, timeline)):
        return False
    record = assembled.get("record")
    if not isinstance(record, dict):
        return False
    authority = fixture.get("inputAuthority") or {}
    expected_duration = Fraction(
        fixture["durationFrames"] * int(fixture["fps"]["denominator"]),
        int(fixture["fps"]["numerator"]),
    )
    try:
        duration_matches = abs(
            float(timeline["outputDuration"]) - float(expected_duration)
        ) <= 1e-6
    except (KeyError, TypeError, ValueError):
        return False
    return (
        qc.get("finalSha256") == output.get("sha256")
        and record.get("authorityHash") == output.get("sha256")
        and assembled.get("recordSha256") == document_sha256(record)
        and SHA256.fullmatch(str(assembled.get("sha256"))) is not None
        and plan.get("sha256") == authority.get("planSha256")
        and SHA256.fullmatch(str(plan.get("contentHash"))) is not None
        and record.get("planHash") == plan.get("contentHash")
        and SHA256.fullmatch(str(timeline.get("sha256"))) is not None
        and duration_matches
        and _audit_passes(fixture, qc.get("auditReport"))
    )


def _media_matches_fixture(
    fixture: dict[str, Any],
    output: dict[str, Any],
) -> bool:
    media = output.get("media")
    video = media.get("video") if isinstance(media, dict) else None
    audio = media.get("audio") if isinstance(media, dict) else None
    decoded = media.get("fullDecode") if isinstance(media, dict) else None
    if not all(isinstance(row, dict) for row in (video, audio, decoded)):
        return False
    expected = Fraction(
        int(fixture["fps"]["numerator"]),
        int(fixture["fps"]["denominator"]),
    )
    dimensions = (1080, 1920) if fixture["mode"] == "short" else (1920, 1080)
    try:
        rates_match = (
            Fraction(video["rFrameRate"]) == expected
            and Fraction(video["avgFrameRate"]) == expected
        )
        audio_duration = float(audio["duration"])
        pcm_bytes = int(decoded["audioPcmBytes"])
        samples = int(decoded["audioSamplesPerChannel"])
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return False
    hashes = (
        decoded.get("videoSha256"),
        decoded.get("audioPcmS16le48000StereoSha256"),
    )
    return (
        (video.get("width"), video.get("height")) == dimensions
        and video.get("decodedFrames") == fixture["durationFrames"]
        and rates_match
        and audio.get("sampleRate") == 48000
        and audio.get("channels") == 2
        and audio_duration > 0
        and pcm_bytes > 0
        and pcm_bytes == samples * 4
        and all(isinstance(value, str) and SHA256.fullmatch(value)
                for value in hashes)
        and valid_media_tools(media.get("tools"))
        and _qc_matches_fixture(fixture, output, media)
    )


def _current_media_state(
    fixture: dict[str, Any],
    runs: list[dict[str, Any]],
) -> str | None:
    observations = []
    for run in runs:
        outputs = run.get("outputs")
        if not isinstance(outputs, list) or len(outputs) != 1:
            return "media-proof-unproved"
        if not _media_matches_fixture(fixture, outputs[0]):
            return "media-proof-unproved"
        media = outputs[0]["media"]
        observations.append({
            key: media[key]
            for key in ("video", "audio", "fullDecode", "tools")
        })
    if observations[0]["tools"] != observations[1]["tools"]:
        return "media-tool-mismatch"
    comparable = []
    for row in observations:
        decoded = {
            key: value for key, value in row["fullDecode"].items()
            if key != "videoSha256"
        }
        comparable.append({
            "video": row["video"], "audio": row["audio"],
            "decodedAudio": decoded,
        })
    return None if comparable[0] == comparable[1] \
        else "decoded-output-mismatch"


def classify_execution(fixture: dict[str, Any],
                       runs: list[dict[str, Any]]) -> str:
    """Classify execution/QC separately from repeat-picture equivalence."""
    if len(runs) != 2:
        return "failed"
    if not all(run.get("exitCode") == 0 for run in runs) or not _complete(runs):
        return "failed"
    if [run.get("cacheState") for run in runs] != ["cold", "warm"]:
        return "cache-state-unproved"
    if fixture["evidenceClass"] == "current-full-path-baseline":
        media_state = _current_media_state(fixture, runs)
        if media_state is not None:
            return media_state
    return str(fixture["evidenceClass"])
