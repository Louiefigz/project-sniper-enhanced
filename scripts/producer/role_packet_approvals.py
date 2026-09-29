"""Given (approved) titles and scripts in the batch authority's approval-v2 form, verified against the transcript.

Requirement revision `approved-content-production-2026-09-27`: each clip's exact title and script
are handed over at batch start and bound in the batch authority (unit A1/A2, the only source and
change record); authors use them verbatim and critics judge the build against them instead of
reopening them. This module reproduces A1/A2's canonical form (studio.native_budget_selection on
branch shorts-sla/a12-tasks) byte for byte and verifies a row read through
studio.production.api.read_approval()["current"]: every identity is recomputed from the row's word
ranges and the observed transcript; a stored digest is never trusted.
"""
from __future__ import annotations

import hashlib
import json
import unicodedata

from role_packet_files import ArtifactError
from role_packet_transcript import Transcript

TITLE_UNITS = 120
TITLE_FORBIDDEN = frozenset([*map(chr, range(0x20)), "\x7f", "\x85", " ", " "])
MAX_RANGES, MAX_WORDS, MAX_WORD_TEXT = 128, 1024, 64
CANONICAL_FORM = ('approval-v2: script = sha256 of UTF-8 compact JSON {"sourceSha256","transcriptSha256",'
                  '"wordRanges","wordTexts","ranges"} in that key order, ensure_ascii off, ranges as [float, float] '
                  'seconds in script order; title = sha256 of the exact UTF-8 title; identity = sha256 of compact '
                  'JSON {"title","script"}')
ROW_KEYS = ("title", "titleSha256", "source", "transcript", "transcriptWords", "wordRanges", "wordTexts", "ranges",
            "script", "identity", "wordCount")


class ApprovalError(ArtifactError):
    """A given title or script is malformed, for another transcript, or its stored identity does not recompute."""


def title_problem(title: object) -> str | None:
    """Why a title breaks the createUserTitleCopy contract; a valid title is kept as its exact bytes."""
    if title is None:
        return None
    if type(title) is not str or all(char.isspace() or char == "﻿" for char in title):
        return "a title is nonblank text (or none)"
    try:
        units = len(title.encode("utf-16-le")) // 2
        title.encode("utf-8")
    except UnicodeEncodeError:
        return "a title is valid Unicode text"
    if units > TITLE_UNITS or TITLE_FORBIDDEN.intersection(title):
        return (f"a title is single-line copy of at most {TITLE_UNITS} characters (UTF-16 units), with no control "
                "or line-separator characters")
    return None


def compare_titles(approved: str | None, observed: str | None) -> str:
    """'exact', 'normalization-only' (NFC and collapsed/trimmed whitespace; not material) or 'different'."""
    if approved == observed:
        return "exact"
    if approved is None or observed is None:
        return "different"
    fold = [" ".join(unicodedata.normalize("NFC", text).split()) for text in (approved, observed)]
    return "normalization-only" if fold[0] == fold[1] else "different"


def title_identity(title: str | None) -> str | None:
    """SHA-256 of the exact title bytes, or None when no title was given."""
    return None if title is None else hashlib.sha256(title.encode("utf-8")).hexdigest()


def expand_words(word_ranges: list[list[int]]) -> list[int]:
    """Inclusive [first, last] word ranges as the ordered index list."""
    return [word for first, last in word_ranges for word in range(first, last + 1)]


def ranges_problem(word_ranges: object, count: int) -> str | None:
    """1-128 in-range inclusive ranges in script order that never overlap, at most 1024 words."""
    if type(word_ranges) is not list or not 0 < len(word_ranges) <= MAX_RANGES or not all(
            type(row) is list and len(row) == 2 and all(type(item) is int for item in row)
            and 0 <= row[0] <= row[1] < count for row in word_ranges):
        return f"an approved script names 1-{MAX_RANGES} in-range inclusive word ranges"
    if sum(last - first + 1 for first, last in word_ranges) > MAX_WORDS:
        return f"approved word ranges name at most {MAX_WORDS} words"
    indices = expand_words(word_ranges)
    if len(set(indices)) != len(indices) or len(indices) > MAX_WORDS:
        return f"approved word ranges do not overlap and name at most {MAX_WORDS} words"
    return None


def seconds_problem(ranges: list[list[float]]) -> str | None:
    """One ordered [start, end] second range per word range; the ranges never overlap."""
    ordered = sorted((float(start), float(end)) for start, end in ranges)
    if any(end <= start or start < 0 for start, end in ordered) or any(
            later[0] < earlier[1] for earlier, later in zip(ordered, ordered[1:])):
        return "approved second ranges are positive and do not overlap"
    return None


def derive_script(source_sha256: str, transcript: Transcript, word_ranges: object) -> dict:
    """The approval-v2 script for word ranges on the observed transcript: texts and seconds are read, not given."""
    problem = ranges_problem(word_ranges, len(transcript.words))
    if problem:
        raise ApprovalError(problem)
    texts = [transcript.words[index]["text"] for index in expand_words(word_ranges)]
    if not all(0 < len(text) <= MAX_WORD_TEXT for text in texts):
        raise ApprovalError(f"every kept word has 1-{MAX_WORD_TEXT} characters of text")
    ranges = [[float(transcript.words[first]["start"]), float(transcript.words[last]["end"])] for first, last in word_ranges]
    problem = seconds_problem(ranges)
    if problem:
        raise ApprovalError(problem)
    return {"sourceSha256": source_sha256, "transcriptSha256": transcript.sha256,
            "transcriptWords": len(transcript.words), "wordRanges": [list(row) for row in word_ranges],
            "wordTexts": texts, "ranges": ranges}


def script_identity(script: dict) -> str:
    """The canonical approval-v2 script identity."""
    body = json.dumps({"sourceSha256": script["sourceSha256"], "transcriptSha256": script["transcriptSha256"],
                       "wordRanges": script["wordRanges"], "wordTexts": script["wordTexts"],
                       "ranges": [[float(start), float(end)] for start, end in script["ranges"]]},
                      ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def approval_identity(title: str | None, script_sha256: str) -> str:
    """One identity over the exact title and the script identity."""
    body = json.dumps({"title": title, "script": script_sha256}, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def approval_row(title: str | None, script: dict) -> dict:
    """The authority's row shape for one given title and derived script."""
    problem = title_problem(title)
    if problem:
        raise ApprovalError(problem)
    identity = script_identity(script)
    return {"title": title, "titleSha256": title_identity(title), "source": script["sourceSha256"],
            "transcript": script["transcriptSha256"], "transcriptWords": script["transcriptWords"],
            "wordRanges": script["wordRanges"], "wordTexts": script["wordTexts"], "ranges": script["ranges"],
            "script": identity, "identity": approval_identity(title, identity), "wordCount": len(script["wordTexts"])}


def checked_ranges(row: dict) -> list[list[float]]:
    """A stored row's second ranges: one numeric [start, end] per word range, never overlapping."""
    ranges = row["ranges"]
    shaped = type(ranges) is list and len(ranges) == len(row["wordRanges"]) and all(
        type(item) is list and len(item) == 2 and all(isinstance(value, (int, float)) and not isinstance(value, bool)
                                                      for value in item) for item in ranges)
    problem = None if shaped else "approval ranges give one [start, end] per word range"
    problem = problem or seconds_problem(ranges)
    if problem:
        raise ApprovalError(problem)
    return [[float(start), float(end)] for start, end in ranges]


def verified_row(row: dict, transcript: Transcript, derived_seconds: bool) -> dict:
    """Recompute a row (sealed in evidence or read from the authority) against the observed transcript.

    Word texts and the transcript identity must match the observation; every identity is recomputed.
    ``derived_seconds`` (evidence rows) also requires the seconds this engine derives from the words.
    """
    if not isinstance(row, dict) or not set(ROW_KEYS) <= set(row) or type(row["source"]) is not str \
            or len(row["source"]) != 64 or type(row["wordRanges"]) is not list:
        raise ApprovalError(f"an approval row carries {list(ROW_KEYS)} with a SHA-256 source")
    if row["transcript"] != transcript.sha256:
        raise ApprovalError(f"approval is for transcript {str(row['transcript'])[:12]}, not the observed "
                            f"{transcript.sha256[:12]}")
    script, ranges = derive_script(row["source"], transcript, row["wordRanges"]), checked_ranges(row)
    drift = [key for key in ("wordTexts", "transcriptWords") if row[key] != script[key]]
    drift += ["ranges"] if derived_seconds and ranges != script["ranges"] else []
    problem = title_problem(row["title"])
    if problem or drift:
        raise ApprovalError(f"approval row does not match its title contract or the observed transcript: {problem or drift}")
    recomputed = approval_row(row["title"], {**script, "ranges": ranges})
    wrong = [key for key in ("titleSha256", "script", "identity", "wordCount") if row[key] != recomputed[key]]
    if wrong:
        raise ApprovalError(f"approval row identities do not recompute from its title, words and seconds: {wrong}")
    return recomputed
