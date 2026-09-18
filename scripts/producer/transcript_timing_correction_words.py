"""Immutable versioned word revisions: no inferred text or timing boundaries."""
from __future__ import annotations

import copy

from cut_preview_io import digest
from transcript_source_authority import SourceObservation, bind_result
from transcript_timing_quality import require_timing_quality
from transcript_timing_correction_contract import correction_profile, number
from transcript_timing_correction_text import rewrite_text, text_origin

ROOT_KEYS = {"status", "transcript", "duration", "fps", "language", "model", "provenance",
             "sourceMediaAuthority", "transcriptPromotionAuthority"}


def _no_approvals(value: object) -> None:
    """Conservatively reject nested approval facts instead of copying their authority."""
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, dict):
            pending.extend(_unapproved_values(current))
        if isinstance(current, list):
            pending.extend(current)


def _unapproved_values(value: dict) -> list:
    """Prevent nested prior approval fields from entering a corrected payload."""
    if any("approv" in key.lower() for key in value):
        raise RuntimeError("timing correction cannot copy approval facts")
    return list(value.values())


def _word(value: object, duration: float) -> tuple[float, float]:
    """Validate an original word without coercion, normalization or sorting."""
    if type(value) is not dict or type(value.get("word")) is not str or not value["word"].strip():
        raise RuntimeError("timing correction requires original nonempty word text")
    start, end = number(value.get("start"), "word start"), number(value.get("end"), "word end")
    if not 0 <= start < end <= duration:
        raise RuntimeError("timing correction word is outside positive source bounds")
    if "confidence" in value and not 0 <= number(value["confidence"], "confidence") <= 1:
        raise RuntimeError("timing correction original confidence is malformed")
    return start, end


def word_locations(payload: dict, duration: float) -> list[tuple[int, int, dict]]:
    """Require ordered, nonoverlapping words and exact containing utterance bounds."""
    if type(payload) is not dict or set(payload) - ROOT_KEYS:
        raise RuntimeError("timing correction parent class is unsupported (including chained corrections)")
    _no_approvals(payload)
    rows = payload.get("transcript")
    if type(rows) is not list or not rows:
        raise RuntimeError("timing correction parent has no utterances")
    locations, previous = [], 0.0
    for row_index, row in enumerate(rows):
        locations_for_row, previous = _row_locations(row, row_index, duration, previous)
        locations.extend(locations_for_row)
    require_timing_quality(payload)
    return locations


def _row_locations(row: dict, index: int, duration: float, previous: float) -> tuple[list, float]:
    """Keep original word order and reject overlapping adjacent intervals."""
    locations = []
    for word_index, word in enumerate(_utterance(row, duration)):
        start, end = _word(word, duration)
        if start < previous:
            raise RuntimeError("timing correction requires neighbor-safe nonoverlapping source order")
        previous = end
        locations.append((index, word_index, word))
    return locations, previous


def _utterance(row: object, duration: float) -> list[dict]:
    """Require an existing utterance to exactly contain its original words."""
    if type(row) is not dict or type(row.get("words")) is not list or not row["words"]:
        raise RuntimeError("timing correction original utterance is malformed")
    words = row["words"]
    first, last = _word(words[0], duration), _word(words[-1], duration)
    if number(row.get("start"), "utterance start") != first[0] \
            or number(row.get("end"), "utterance end") != last[1]:
        raise RuntimeError("timing correction original utterance bounds do not match its words")
    if "text" in row and type(row["text"]) is not str:
        raise RuntimeError("timing correction original utterance text is malformed")
    return words


def revised_payload(payload: dict, proposed: dict, duration: float) -> dict:
    """Apply only the explicitly selected version, never a failed-parser fallback."""
    locations = word_locations(payload, duration)
    if proposed["schemaVersion"] == 2:
        result = rewrite_text(payload, proposed, locations)
        word_locations(result, duration)
        return result
    return _revised_timing(payload, proposed, duration, locations)


def _revised_timing(payload: dict, proposed: dict, duration: float, locations: list[tuple]) -> dict:
    """Preserve exact v1 semantics: only word and affected utterance bounds change."""
    result, touched = copy.deepcopy(payload), set()
    for change in proposed["corrections"]:
        index = change["sourceWordIndex"]
        if index >= len(locations):
            raise RuntimeError("timing correction source word index does not exist")
        row_index, word_index, original = locations[index]
        if (original["start"], original["end"]) == (change["newStart"], change["newEnd"]):
            raise RuntimeError("timing correction contains an unchanged interval")
        word = result["transcript"][row_index]["words"][word_index]
        word.update(start=change["newStart"], end=change["newEnd"])
        touched.add(row_index)
    for index in touched:
        row = result["transcript"][index]
        row.update(start=row["words"][0]["start"], end=row["words"][-1]["end"])
    word_locations(result, duration)
    return result


def _windows(old: dict, change: dict | None, source: dict) -> list[dict]:
    """Bind complete bounded old/new audition contexts, never inferred listening."""
    duration = source["duration"]
    change = change if change is not None else {"newStart": old["start"], "newEnd": old["end"]}
    ranges = [(max(0, old["start"] - 1), min(duration, old["end"] + 1)),
              (max(0, change["newStart"] - 1), min(duration, change["newEnd"] + 1))]
    if ranges[0][0] <= ranges[1][1] and ranges[1][0] <= ranges[0][1]:
        ranges = [(min(row[0] for row in ranges), max(row[1] for row in ranges))]
    if any(end - start > 30 for start, end in ranges):
        raise RuntimeError("timing correction requires an unsupported source audition longer than 30s")
    windows = [{"sourceId": source["id"], "start": start, "end": end} for start, end in ranges]
    return [{**row, "windowHash": digest(row)} for row in windows]


def correction_rows(payload: dict, proposed: dict, source: dict) -> list[dict]:
    """Bind every exact old/new interval and complete source-audition context."""
    words = word_locations(payload, source["duration"])
    revised_payload(payload, proposed, source["duration"])
    rows = []
    for change in proposed["corrections"]:
        original = words[change["sourceWordIndex"]][2]
        timing = change if proposed["schemaVersion"] == 1 else None
        changed = {"newBounds": {"start": change["newStart"], "end": change["newEnd"]}} \
            if timing is not None else {"newWord": change["newWord"]}
        body = {"sourceWordIndex": change["sourceWordIndex"], "originalWord": original,
                **changed, "sourceWindows": _windows(original, timing, source)}
        rows.append({**body, "correctionHash": digest(body)})
    return rows


def corrected_result(payload: dict, request: dict, decision: dict, observed: SourceObservation) -> dict:
    """Renew source binding while retaining ASR provenance as historical evidence."""
    result = revised_payload(payload, request["proposal"], request["binding"]["source"]["duration"])
    parent = result.pop("sourceMediaAuthority")
    profile = correction_profile(request["schemaVersion"])
    origin = {"boundsOrigin": "explicit-human-boundary-review-not-emitted-by-ASR"} \
        if profile["schemaVersion"] == 1 else text_origin()
    result[profile["marker"]] = {
        "schemaVersion": profile["schemaVersion"], "policy": profile["policy"], "scope": profile["scope"],
        "parentTranscript": request["binding"]["parents"]["transcript"],
        "parentSourceBindingDigest": parent["bindingDigest"],
        "requestHash": request["requestHash"], "recordHash": decision["recordHash"],
        **origin,
        "parentAsrProvenance": payload.get("provenance"),
        "correctionHashes": [row["correctionHash"] for row in request["corrections"]],
    }
    return bind_result(result, observed)
