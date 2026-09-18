"""Deterministic speech-quality checks for transcript-bound cut output."""
from __future__ import annotations

import re
from statistics import median
from typing import Any

from edit_scope import resolve_scope
from transcript_cut_evidence import SourceEvidence

HARD_DUPLICATES = {
    "a", "an", "and", "but", "for", "i", "if", "is", "it", "maybe", "of",
    "or", "she", "so", "that", "the", "they", "this", "to", "we", "you",
}
SUBORDIMODULE_MARKERS = {"although", "because", "unless", "whereas"}
NOUN_PHRASE_LEADS = {"a", "all", "an", "every", "few", "many", "most", "no",
                     "our", "some", "the", "their", "these", "those", "your"}
NOUN_PHRASE_TAILS = {"accounts", "audience", "brands", "businesses", "clients",
                     "companies", "creators", "customers", "people", "teams",
                     "users", "viewers"}
HOOK_FUNCTION_WORDS = {
    "a", "an", "and", "as", "at", "but", "for", "if", "in", "is", "it",
    "of", "on", "or", "so", "the", "to", "we", "you",
}
MIN_HOOK_WORD_SPAN_S = 1.5
HOOK_LOCAL_PACE_MULTIPLIER = 4.0
HOOK_LOCAL_PACE_WORDS = 8


def _norm(text: Any) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(text).lower())


def _kept_output(plan: dict, sources: dict[str, SourceEvidence],
                 epsilon: float) -> list[tuple]:
    output: list[tuple] = []
    for cut_index, cut in enumerate(plan.get("cutTrack") or []):
        source = sources.get(str(cut.get("sourceId", "")))
        try:
            start, end = float(cut["start"]), float(cut["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if source is None:
            continue
        for word in source.words:
            if word["start"] >= start - epsilon and word["end"] <= end + epsilon:
                output.extend((token, word, cut_index) for token in _norm(word["word"]))
    return output


def _unique_word_spans(output: list[tuple]) -> list[tuple]:
    """Collapse normalized tokens that came from the same timestamped word."""
    unique: list[tuple] = []
    seen: set[tuple] = set()
    for token, word, cut_index in output:
        start, end = float(word["start"]), float(word["end"])
        identity = (cut_index, start, end)
        if identity in seen:
            continue
        seen.add(identity)
        unique.append((token, word, cut_index))
    return unique


def _strict_hook(plan: dict) -> bool:
    target = plan.get("target") or {}
    try:
        return target.get("mode") == "longform" \
            and resolve_scope(target) in ("produced", "full")
    except (TypeError, ValueError):
        return False


def _opening_timing_finding(token: str, word: dict, cut_index: int,
                             samples: list[float]) -> dict | None:
    raw = str(word.get("word", "")).strip()
    start, end = float(word["start"]), float(word["end"])
    duration = end - start
    local_median = median(samples)
    threshold = max(MIN_HOOK_WORD_SPAN_S,
                    HOOK_LOCAL_PACE_MULTIPLIER * local_median)
    if token not in HOOK_FUNCTION_WORDS or raw.endswith((".", "?", "!")) \
            or duration < threshold:
        return None
    ratio = duration / local_median if local_median > 0 else 0.0
    return {"word": token, "start": round(start, 4), "end": round(end, 4),
            "duration": round(duration, 4), "cutIndex": cut_index,
            "localMedianS": round(local_median, 4),
            "paceRatio": round(ratio, 2)}


def _timing_candidates(plan: dict, sources: dict[str, SourceEvidence],
                       output: list[tuple], epsilon: float) -> list[tuple]:
    """Inspect the opening and every omitted prefix word without making cuts."""
    cuts = plan.get("cutTrack") or []
    words = _unique_word_spans(output)
    if not _strict_hook(plan) or not words or not cuts:
        return []
    _, kept, cut_index = words[0]
    kept_source_id = str(cuts[cut_index].get("sourceId", ""))
    kept_index = next(index for index, row in enumerate(sources[kept_source_id].words) if row is kept)
    candidates = [(kept, kept_index, cut_index, kept_source_id, "kept_opening")]
    first = cuts[0]
    source_id = str(first.get("sourceId", ""))
    source = sources.get(source_id)
    try:
        boundary = float(first["start"])
    except (KeyError, TypeError, ValueError):
        return candidates
    if source is None:
        return candidates
    candidates.extend((word, index, 0, source_id, "excluded_before_opening")
                      for index, word in enumerate(source.words)
                      if float(word["end"]) <= boundary + epsilon
                      and float(word["start"]) < boundary - epsilon)
    return candidates


def _source_pace(index: int, source: SourceEvidence) -> list[float]:
    """Use following source words, not a pace changed by removing more speech."""
    return [float(row["end"]) - float(row["start"])
            for row in source.words[index + 1:index + 1 + HOOK_LOCAL_PACE_WORDS]]


def _timing_reviews(plan: dict, sources: dict[str, SourceEvidence],
                    output: list[tuple], epsilon: float
                    ) -> tuple[list[dict], list[str]]:
    """Block unresolved metadata anomalies; timing cannot prove speech or silence."""
    findings, errors = [], []
    for word, word_index, cut_index, source_id, position in _timing_candidates(
            plan, sources, output, epsilon):
        tokens = _norm(word["word"])
        samples = _source_pace(word_index, sources[source_id])
        if len(tokens) != 1 or len(samples) < 3:
            continue
        finding = _opening_timing_finding(tokens[0], word, cut_index, samples)
        if finding is None:
            continue
        findings.append({**finding, "sourceId": source_id, "position": position,
                         "sourceWordIndex": word_index,
                         "confidence": word.get("confidence"),
                         "reason": "unresolved_opening_word_timing",
                         "reviewRequired": True})
        errors.append(timing_review_error(findings[-1]))
    return findings, errors


def timing_review_error(finding: dict) -> str:
    """Identify only this exact anomaly; a review cannot clear other cut errors."""
    return (f"opening timing review required: {finding['sourceId']} {finding['position']} "
            f"function word {finding['word']!r} spans {finding['duration']:.3f}s at "
            f"{finding['start']:.3f}-{finding['end']:.3f}s — source-grounded speech "
            "review is required; word timing and confidence do not prove silence "
            "or authorize deleting, restoring, or retiming speech")


def inspect_output(plan: dict, sources: dict[str, SourceEvidence], epsilon: float
                   ) -> tuple[dict, list[str], list[str]]:
    """Return receipt metrics plus hard errors and advisory warnings."""
    output = _kept_output(plan, sources, epsilon)
    duplicates: list[dict] = []
    errors: list[str] = []
    warnings: list[str] = []
    for previous, current in zip(output, output[1:]):
        if previous[1] is current[1]:
            continue          # tokens of ONE timestamped word ("It's" -> it, s) are not a repeat
        word = "".join(_norm(current[1]["word"]))
        if not word or word != "".join(_norm(previous[1]["word"])):
            continue          # whole spoken words must match: "it." then "It's" is not a stutter
        severity = "error" if word in HARD_DUPLICATES else "warning"
        issue = (f"kept output: adjacent duplicate word {word!r} at "
                 f"{previous[1]['end']:.3f}-{current[1]['start']:.3f}s")
        (errors if severity == "error" else warnings).append(issue)
        duplicates.append({"word": word, "at": round(current[1]["start"], 4),
                           "severity": severity})
    tokens = [row[0] for row in output]
    incomplete = bool(tokens and tokens[-1] in SUBORDIMODULE_MARKERS)
    incomplete = incomplete or (len(tokens) >= 3 and tokens[-3] == "because"
                                and tokens[-2] in NOUN_PHRASE_LEADS
                                and tokens[-1] in NOUN_PHRASE_TAILS)
    if incomplete:
        errors.append(
            "kept output: semantically incomplete final subordinate fragment: "
            + " ".join(tokens[-4:]))
    suspicious, timing_errors = _timing_reviews(plan, sources, output, epsilon)
    errors.extend(timing_errors)
    report = {"keptWords": len(output), "adjacentDuplicates": duplicates,
              "incompleteFinalSubordinate": incomplete,
              "suspiciousWordSpans": suspicious,
              "forbiddenOpeningStarts": []}  # Legacy field; never a cut directive.
    return report, errors, warnings
