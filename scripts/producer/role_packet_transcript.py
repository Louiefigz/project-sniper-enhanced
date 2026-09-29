"""The admitted transcript a script is cut from: exact bytes, the writer's word index space and frame rule.

One index space. The native writer (plan-review-packet-source.ts `packetSpeechEvidence` over the whole
source, then guided-proposal-speech.ts) numbers `sourceWord` over the utterance words it keeps: it
drops words whose kept duration is at most 1e-6 s or that start at or beyond the source's end, and
orders them by start. approval-v2 (unit A1/A2) numbers the raw flattened words. The two coincide
exactly when no word is dropped or reordered, so a transcript where they would differ is refused
here, with a specific error, instead of being mapped. `occurrence_frames` mirrors the writer's exact
frame rule (`occurrence`/`proposalRelativeFrame`): the word interval clipped to its segment's cut,
floor for the start edge and ceil for the end edge on the exact decimal clock, capped at the
segment's length. It locates where a kept word must sit; it judges nothing.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction

from role_packet_files import MAX_RECEIPT_JSON, ArtifactError, artifact, read_json

MAX_WORDS = 200_000
KEPT_EPSILON = 1e-6


@dataclass(frozen=True)
class Transcript:
    """One observed admitted transcript."""
    path: str
    sha256: str
    words: tuple[dict, ...]


def word_row(raw: object, label: str) -> dict:
    """{text, start, end} for one transcript word as the writer parses it (text in `word`)."""
    times = [raw.get(key) for key in ("start", "end")] if isinstance(raw, dict) else [None, None]
    if not isinstance(raw, dict) or not isinstance(raw.get("word"), str) or not all(
            isinstance(value, (int, float)) and not isinstance(value, bool) for value in times) or times[1] < times[0]:
        raise ArtifactError(f"{label} needs text in `word` and ordered numeric start/end")
    return {"text": raw["word"], "start": times[0], "end": times[1]}


def utterance_words(value: object, path: str) -> list[dict]:
    """Every word of the utterance array, in file order (the writer's transcriptRows)."""
    rows = value.get("transcript") if isinstance(value, dict) else None
    if not isinstance(rows, list) or not all(isinstance(row, dict) and isinstance(row.get("words"), list) for row in rows):
        raise ArtifactError(f"{path} is not an utterance transcript ({{transcript: [{{words: [...]}}]}}) the writer reads")
    return [word_row(word, f"{path} word {row_index}.{word_index}") for row_index, row in enumerate(rows)
            for word_index, word in enumerate(row["words"])]


def index_space_problem(words: list[dict], duration: float) -> str | None:
    """Why the writer's kept-word numbering would differ from the raw flattened numbering, if it would."""
    dropped = [index for index, word in enumerate(words)
               if not 0 <= word["start"] or min(word["end"], duration) <= word["start"] + KEPT_EPSILON]
    reordered = [index for index, (earlier, later) in enumerate(zip(words, words[1:]), start=1)
                 if later["start"] < earlier["start"]]
    if not dropped and not reordered:
        return None
    return (f"the writer drops words {dropped[:8]} (zero duration or at/after the source end) and reorders words "
            f"{reordered[:8]}, so its word indices differ from approval-v2's")


def observe_transcript(path: str, duration: float) -> Transcript:
    """Hash and read an admitted transcript whose raw word indices are exactly the writer's."""
    row = artifact("transcript", path, "Admitted transcript.")
    words = utterance_words(read_json(row["path"], MAX_RECEIPT_JSON), row["path"])
    problem = "it has no words" if not words or len(words) > MAX_WORDS else index_space_problem(words, float(duration))
    if problem:
        raise ArtifactError(f"{row['path']}: refused because {problem}")
    return Transcript(row["path"], row["sha256"], tuple(words))


def exact(value: int | float) -> Fraction:
    """The decimal a JSON number spells, as an exact fraction."""
    return Fraction(repr(value)) if isinstance(value, float) else Fraction(value)


def occurrence_frames(occurrence: list, canvas: dict, words: tuple[dict, ...]) -> tuple[int, int, int] | None:
    """(startFrame, endFrameExclusive, clipMask) the writer derives for this occurrence, or None when unmappable."""
    segment, index = occurrence[1], occurrence[2]
    cuts, parts = canvas.get("cuts") or [], canvas.get("segments") or []
    if not (isinstance(segment, int) and 0 <= segment < min(len(cuts), len(parts)) and 0 <= index < len(words)):
        return None
    cut, part, word = cuts[segment], parts[segment], words[index]
    start, end = max(exact(word["start"]), exact(cut["start"])), min(exact(word["end"]), exact(cut["end"]))
    if end <= start or cut.get("speed", 1) != 1:
        return None
    numerator, denominator = str(canvas["frameRate"]).split("/")
    rate, origin = Fraction(int(numerator), int(denominator)), exact(cut["start"])
    length = part["endFrameExclusive"] - part["startFrame"]
    first = part["startFrame"] + min(length, math.floor((start - origin) * rate))
    last = part["startFrame"] + min(length, math.ceil((end - origin) * rate))
    mask = (1 if exact(word["start"]) < start else 0) | (2 if exact(word["end"]) > end else 0)
    return first, last, mask
