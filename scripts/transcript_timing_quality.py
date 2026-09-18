"""Objective word-timing quality gate shared by local ASR and Producer ingest."""

from __future__ import annotations

import math
from typing import Any

POLICY = "sniper-transcript-timing-quality-v1"
TINY_WORD_MAX_SECONDS = 0.011
OVERLAP_TOLERANCE_SECONDS = 0.0005
MAX_TINY_OR_OVERLAP_RATE = 0.01
MAX_COLLAPSED_RUN_WORDS = 1


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _words(payload: Any) -> tuple[list[dict], int]:
    if not isinstance(payload, dict) or not isinstance(
            payload.get("transcript"), list):
        return [], 1
    words: list[dict] = []
    malformed = 0
    for utterance in payload["transcript"]:
        if not isinstance(utterance, dict) or not isinstance(
                utterance.get("words"), list):
            malformed += 1
            continue
        for word in utterance["words"]:
            if not isinstance(word, dict) or not str(word.get("word", "")).strip():
                malformed += 1
                continue
            start, end = _number(word.get("start")), _number(word.get("end"))
            if start is None or end is None:
                malformed += 1
                continue
            words.append({"start": start, "end": end})
    return words, malformed


def _run_metrics(words: list[dict]) -> tuple[int, int, int]:
    tiny = 0
    current_run = 0
    max_run = 0
    nonpositive = 0
    for word in words:
        duration = word["end"] - word["start"]
        nonpositive += int(duration <= 0)
        is_tiny = 0 < duration <= TINY_WORD_MAX_SECONDS
        tiny += int(is_tiny)
        current_run = current_run + 1 if is_tiny else 0
        max_run = max(max_run, current_run)
    return tiny, max_run, nonpositive


def _sequence_metrics(words: list[dict]) -> tuple[int, int]:
    overlaps = 0
    backwards = 0
    for previous, current in zip(words, words[1:]):
        overlaps += int(
            current["start"] < previous["end"] - OVERLAP_TOLERANCE_SECONDS)
        backwards += int(
            current["start"] < previous["start"] - OVERLAP_TOLERANCE_SECONDS)
    return overlaps, backwards


def _violations(metrics: dict) -> list[dict]:
    rows: list[dict] = []
    checks = (
        ("no_words", metrics["wordCount"] == 0, "transcript has no timed words"),
        ("malformed_words", metrics["malformedWordCount"] > 0,
         f"{metrics['malformedWordCount']} words/utterances are malformed"),
        ("nonpositive_words", metrics["nonPositiveDurationCount"] > 0,
         f"{metrics['nonPositiveDurationCount']} words have non-positive duration"),
        ("backward_timeline", metrics["backwardStartCount"] > 0,
         f"{metrics['backwardStartCount']} word starts move backward"),
        ("collapsed_run", metrics["maxCollapsedRunWords"] > MAX_COLLAPSED_RUN_WORDS,
         f"max <=11ms consecutive-word run is {metrics['maxCollapsedRunWords']}"),
        ("tiny_word_rate", metrics["tinyWordCount"] > 1
         and metrics["tinyWordRate"] > MAX_TINY_OR_OVERLAP_RATE,
         f"<=11ms word rate is {metrics['tinyWordRate']:.6f}"),
        ("overlap_rate", metrics["overlappingPairCount"] > 1
         and metrics["overlapRate"] > MAX_TINY_OR_OVERLAP_RATE,
         f"overlapping-pair rate is {metrics['overlapRate']:.6f}"),
    )
    for code, failed, evidence in checks:
        if failed:
            rows.append({"code": code, "evidence": evidence})
    return rows


def timing_quality_report(payload: Any) -> dict:
    """Measure timing collapse and return a stable pass/fail evidence object."""
    words, malformed = _words(payload)
    tiny, max_run, nonpositive = _run_metrics(words)
    overlaps, backwards = _sequence_metrics(words)
    word_denominator = max(len(words), 1)
    pair_denominator = max(len(words) - 1, 1)
    metrics = {
        "wordCount": len(words),
        "malformedWordCount": malformed,
        "nonPositiveDurationCount": nonpositive,
        "tinyWordCount": tiny,
        "tinyWordRate": tiny / word_denominator,
        "overlappingPairCount": overlaps,
        "overlapRate": overlaps / pair_denominator,
        "backwardStartCount": backwards,
        "maxCollapsedRunWords": max_run,
    }
    violations = _violations(metrics)
    return {
        "schemaVersion": 1, "policy": POLICY,
        "status": "fail" if violations else "pass",
        **metrics, "violations": violations,
    }


def require_timing_quality(payload: Any) -> dict:
    """Return the report or reject a transcript that cannot drive word edits."""
    report = timing_quality_report(payload)
    if report["status"] != "pass":
        codes = ",".join(row["code"] for row in report["violations"])
        raise RuntimeError(f"transcript timing quality failed: {codes}")
    return report
