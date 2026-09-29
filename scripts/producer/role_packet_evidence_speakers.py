"""Shared-evidence schema version 2 (P2-07): speaker certainty and basis, face regions and protected caption phrases.

Each speaker interval gains a ``certainty`` and a ``basis``. The vocabulary is defined once, here (X53). P3a
imports ``CERTAINTIES`` and ``BASES``; there is no second definition and no mapping table. The rules:
- ``unresolved`` exactly when ``speaker`` is null;
- ``established`` only with basis ``listening`` (and ``speakers.listening`` true), or ``operator-statement`` with
  at least one bound-file citation in ``evidence``;
- a ``transcript-only`` basis is never ``established``.
Each refusal is an ``EvidenceError`` naming the row. People may carry a ``faceRegion`` in source pixels. Speaker
observations map faces to people through it (X59(7); role_packet_evidence_coverage).

Version 1 records stay readable through ``mapped_intervals``, which is read-only. A null speaker reads as
unresolved. Otherwise the interval reads as established when the record says it listened, and as probable when it
did not. Version 1 carries no phrases and no coverage, so it can bind packets but cannot satisfy P2-08.

The engine-observed half (approvals, ``coverage``, ``observations_binding``) is role_packet_evidence_coverage.
Its P2-07 names are re-exported here.
"""
from __future__ import annotations

import math

from role_packet_evidence_coverage import coverage, observations_binding
from role_packet_evidence_record import source_transcript
from role_packet_evidence_schema import (INTERVAL_LIMIT, LIST_LIMIT, EvidenceError, citations, cited, exact, interval,
                                         people, text, texts)

__all__ = ["BASES", "CERTAINTIES", "caption_phrases", "coverage", "mapped_intervals", "observations_binding",
           "speakers_v2"]

CERTAINTIES = ("established", "probable", "unresolved")
BASES = ("listening", "operator-statement", "visual-and-stereo", "transcript-only")
DECIDERS = ("operator", "coordinator")
SPEAKER_KEYS = ("method", "listening", "people", "intervals", "limits")
INTERVAL_KEYS = ("source", "startSeconds", "endSeconds", "speaker", "visible", "note")
V2_INTERVAL_KEYS = (*INTERVAL_KEYS, "basis", "certainty", "evidence")
PHRASE_KEYS = ("source", "sourceWordIndexes", "display", "decidedBy", "files", "note")
PHRASE_WORDS = range(2, 7)


def face_region(value: object, label: str, durations: dict) -> dict:
    """A person's face region on one admitted source: ``{source, xRange: [x0, x1]}`` with 0 <= x0 < x1 source px."""
    row = exact(value, ("source", "xRange"), label)
    span = row["xRange"]
    numbers = isinstance(span, list) and len(span) == 2 and all(
        isinstance(item, (int, float)) and not isinstance(item, bool) and math.isfinite(item) for item in span)
    if not isinstance(row["source"], str) or row["source"] not in durations or not numbers or not 0 <= span[0] < span[1]:
        raise EvidenceError(f"{label} must be {{source: an admitted source id, xRange: [x0, x1]}} with "
                            "0 <= x0 < x1 in source pixels")
    return row


def people_v2(value: object, context: dict) -> list[dict]:
    """Version 1's people rules on every person, plus an optional ``faceRegion`` each."""
    if not isinstance(value, list):
        return people(value, context)
    people([{key: item[key] for key in item if key != "faceRegion"} if isinstance(item, dict) else item
            for item in value], context)
    for index, item in enumerate(value):
        if "faceRegion" in item:
            face_region(item["faceRegion"], f"speakers.people[{index}].faceRegion", context["durations"])
    return value


def grounds(row: dict, label: str, context: dict) -> None:
    """``evidence`` lists 0-64 citations; established needs listening that happened, or a filed operator statement."""
    evidence = row["evidence"]
    if not isinstance(evidence, list) or len(evidence) > LIST_LIMIT:
        raise EvidenceError(f"{label}.evidence must list 0-{LIST_LIMIT} citations")
    if evidence:
        citations(evidence, f"{label}.evidence", context)
    if row["certainty"] != "established":
        return
    if row["basis"] == "transcript-only":
        raise EvidenceError(f"{label}: a transcript-only basis is never established")
    if row["basis"] == "listening" and context["listening"] is True:
        return
    if row["basis"] == "operator-statement" and any(set(item) == {"file"} for item in evidence):
        return
    raise EvidenceError(f"{label}: established needs basis listening with speakers.listening true, or "
                        "operator-statement citing at least one bound file in evidence")


def interval_v2(value: object, label: str, ids: set[str], context: dict) -> dict:
    """One version 2 interval: version 1's rules, then certainty, basis and evidence."""
    row = exact(value, V2_INTERVAL_KEYS, label)
    interval({key: row[key] for key in INTERVAL_KEYS}, label, ids, context["durations"])
    if row["certainty"] not in CERTAINTIES:
        raise EvidenceError(f"{label}.certainty must be one of {list(CERTAINTIES)}")
    if row["basis"] not in BASES:
        raise EvidenceError(f"{label}.basis must be one of {list(BASES)}")
    if (row["certainty"] == "unresolved") != (row["speaker"] is None):
        raise EvidenceError(f"{label}: certainty is unresolved exactly when speaker is null (unresolved)")
    grounds(row, label, context)
    return row


def speakers_v2(value: object, context: dict) -> dict:
    """Version 2 speaker facts: version 1's block, face regions, and per interval certainty, basis and evidence.

    Args:
        value: The authored ``speakers`` block.
        context: ``bound`` keys and source ``durations`` (``role_packet_evidence_schema.field_context``).

    Returns:
        The validated block, equal to its input when valid (so a sealed record re-validates to itself).

    Raises:
        EvidenceError: The first refused field, named by its row.
    """
    row = exact(value, SPEAKER_KEYS, "speakers")
    if not isinstance(row["listening"], bool):
        raise EvidenceError("speakers.listening must be true or false (stills and transcripts are not listening)")
    found = people_v2(row["people"], context)
    ids = {item["id"] for item in found}
    if not isinstance(row["intervals"], list) or len(row["intervals"]) > INTERVAL_LIMIT:
        raise EvidenceError(f"speakers.intervals must be a list of at most {INTERVAL_LIMIT} rows")
    scope = {**context, "listening": row["listening"]}
    return {"method": text(row["method"], "speakers.method"), "listening": row["listening"], "people": found,
            "intervals": [interval_v2(item, f"speakers.intervals[{index}]", ids, scope)
                          for index, item in enumerate(row["intervals"])],
            "limits": texts(row["limits"], "speakers.limits", required=True)}


def mapped_intervals(version: int, speakers: dict) -> list[dict]:
    """Every validated interval with its certainty and basis; a version 1 record's are mapped (read-only).

    Version 1: a null speaker is unresolved; otherwise established when the record says it listened, else
    probable. Its basis is listening when it listened and null otherwise, because version 1 recorded no basis.
    """
    if version == 2:
        return [dict(row) for row in speakers["intervals"]]
    heard = speakers["listening"] is True
    return [{**row, "certainty": "unresolved" if row["speaker"] is None else "established" if heard else "probable",
             "basis": "listening" if heard else None, "evidence": []} for row in speakers["intervals"]]


def word_count(context: dict, source: str) -> int:
    """How many words the admitted source's transcript holds (observed once per validation)."""
    counts = context.setdefault("wordCounts", {})
    if source not in counts:
        counts[source] = len(source_transcript(context["current"], source)[1].words)
    return counts[source]


def phrase(value: object, label: str, context: dict) -> dict:
    """One protected phrase: 2-6 consecutive transcript words of an admitted source, and the files that decided it."""
    row = exact(value, PHRASE_KEYS, label)
    if not isinstance(row["source"], str) or row["source"] not in context["durations"]:
        raise EvidenceError(f"{label}.source must be an admitted source id {sorted(context['durations'])}")
    indexes = row["sourceWordIndexes"]
    shaped = isinstance(indexes, list) and len(indexes) == 2 and all(type(item) is int for item in indexes)
    first, last = indexes if shaped else (-1, -1)
    if not 0 <= first or last - first + 1 not in PHRASE_WORDS or last >= word_count(context, row["source"]):
        raise EvidenceError(f"{label}.sourceWordIndexes must be [first, last] naming 2-6 words of source "
                            f"{row['source']}'s transcript")
    if row["decidedBy"] not in DECIDERS:
        raise EvidenceError(f"{label}.decidedBy must be one of {list(DECIDERS)}")
    text(row["display"], f"{label}.display")
    cited(row["files"], f"{label}.files", context["bound"], required=True)
    if row["note"] is not None:
        text(row["note"], f"{label}.note")
    return row


def caption_phrases(value: object, context: dict) -> list[dict]:
    """At most 64 protected caption phrases; two phrases on one source never share a word (E-C3).

    Args:
        value: The authored ``captionPhrases`` list.
        context: As for ``speakers_v2``, plus ``current`` (the observed inputs) for the transcripts.

    Returns:
        The validated rows, equal to their input.
    """
    if not isinstance(value, list) or len(value) > LIST_LIMIT:
        raise EvidenceError(f"captionPhrases must be a list of at most {LIST_LIMIT} phrases")
    rows = [phrase(item, f"captionPhrases[{index}]", context) for index, item in enumerate(value)]
    spans = sorted((row["source"], *row["sourceWordIndexes"], index) for index, row in enumerate(rows))
    for earlier, later in zip(spans, spans[1:]):
        if earlier[0] == later[0] and later[1] <= earlier[2]:
            raise EvidenceError(f"captionPhrases[{later[3]}] overlaps captionPhrases[{earlier[3]}] on source {later[0]} "
                                f"(source words {later[1]}-{later[2]})")
    return rows
