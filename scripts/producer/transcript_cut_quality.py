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
SUBORDINATE_MARKERS = {"although", "because", "unless", "whereas"}
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


def _suspicious_word_spans(plan: dict, output: list[tuple]
                           ) -> tuple[list[dict], list[str]]:
    """Detect a retention-killing pause assigned to the first function word."""
    words = _unique_word_spans(output)
    if not _strict_hook(plan) or len(words) < 4:
        return [], []
    token, word, cut_index = words[0]
    start, end = float(word["start"]), float(word["end"])
    duration = end - start
    samples = [float(row[1]["end"]) - float(row[1]["start"])
               for row in words[1:1 + HOOK_LOCAL_PACE_WORDS]]
    finding = _opening_timing_finding(token, word, cut_index, samples)
    if finding is None:
        return [], []
    error = (f"kept hook: first function word {token!r} spans {duration:.3f}s at "
             f"{start:.3f}-{end:.3f}s ({finding['paceRatio']:.1f}x local word pace) — probable "
             "ASR-assigned dead air must be removed at legal word boundaries")
    return [finding], [error]


def _forbidden_opening_starts(plan: dict, sources: dict[str, SourceEvidence],
                              output: list[tuple], epsilon: float) -> list[dict]:
    """Record an excluded boundary word that the same gate would reject if kept."""
    words = _unique_word_spans(output)
    cuts = plan.get("cutTrack") or []
    if not _strict_hook(plan) or len(words) < 4 or not cuts:
        return []
    first = cuts[0]
    source_id = str(first.get("sourceId", ""))
    source = sources.get(source_id)
    try:
        boundary = float(first["start"])
    except (KeyError, TypeError, ValueError):
        return []
    if source is None:
        return []
    candidate = next((word for word in reversed(source.words)
                      if abs(float(word["end"]) - boundary) <= epsilon), None)
    tokens = _norm(candidate.get("word")) if candidate else []
    samples = [float(row[1]["end"]) - float(row[1]["start"])
               for row in words[:HOOK_LOCAL_PACE_WORDS]]
    if len(tokens) != 1 or not samples:
        return []
    finding = _opening_timing_finding(tokens[0], candidate, 0, samples)
    if finding is None:
        return []
    return [{**finding, "sourceId": source_id,
             "requiredStartAtOrAfter": round(boundary, 4),
             "reason": "probable_asr_assigned_dead_air"}]


def inspect_output(plan: dict, sources: dict[str, SourceEvidence], epsilon: float
                   ) -> tuple[dict, list[str], list[str]]:
    """Return receipt metrics plus hard errors and advisory warnings."""
    output = _kept_output(plan, sources, epsilon)
    duplicates: list[dict] = []
    errors: list[str] = []
    warnings: list[str] = []
    for previous, current in zip(output, output[1:]):
        if previous[0] != current[0]:
            continue
        severity = "error" if current[0] in HARD_DUPLICATES else "warning"
        issue = (f"kept output: adjacent duplicate word {current[0]!r} at "
                 f"{previous[1]['end']:.3f}-{current[1]['start']:.3f}s")
        (errors if severity == "error" else warnings).append(issue)
        duplicates.append({"word": current[0], "at": round(current[1]["start"], 4),
                           "severity": severity})
    tokens = [row[0] for row in output]
    incomplete = bool(tokens and tokens[-1] in SUBORDINATE_MARKERS)
    incomplete = incomplete or (len(tokens) >= 3 and tokens[-3] == "because"
                                and tokens[-2] in NOUN_PHRASE_LEADS
                                and tokens[-1] in NOUN_PHRASE_TAILS)
    if incomplete:
        errors.append(
            "kept output: semantically incomplete final subordinate fragment: "
            + " ".join(tokens[-4:]))
    suspicious, timing_errors = _suspicious_word_spans(plan, output)
    errors.extend(timing_errors)
    forbidden = _forbidden_opening_starts(plan, sources, output, epsilon)
    report = {"keptWords": len(output), "adjacentDuplicates": duplicates,
              "incompleteFinalSubordinate": incomplete,
              "suspiciousWordSpans": suspicious,
              "forbiddenOpeningStarts": forbidden}
    return report, errors, warnings
