"""Explicit one-to-one source-faithful text changes, never inferred ASR repair."""
from __future__ import annotations

import copy
import unicodedata

CHANGED_WORD_KEYS = {"word", "start", "end", "confidence", "speaker", "id"}


def lexical_word(value: object) -> str:
    """Require one exact lexical token; never trim, normalize or split its text."""
    if type(value) is not str or not 1 <= len(value) <= 120:
        raise RuntimeError("text correction requires one lexical token of 1–120 characters")
    if any(char.isspace() or unicodedata.category(char).startswith("C") for char in value) \
            or not any(char.isalnum() for char in value) or value.startswith("[_"):
        raise RuntimeError("text correction cannot contain whitespace, controls or punctuation-only text")
    return value


def _row_text(row: dict) -> None:
    """Require any emitted utterance text to match its exact ordered word join."""
    if "text" in row and row["text"] != " ".join(word["word"] for word in row["words"]):
        raise RuntimeError("text correction original utterance text is ambiguous; exact word join required")


def _identity(value: object) -> None:
    """Preserve only bounded scalar speaker/id metadata, never lexical subobjects."""
    if type(value) is int and 0 <= value <= 2 ** 53 - 1:
        return
    if type(value) is str and 1 <= len(value) <= 128 and value.strip() \
            and not any(unicodedata.category(char).startswith("C") for char in value):
        return
    raise RuntimeError("text correction changed-word speaker/id metadata is unsupported")


def _changed_word_fields(word: dict) -> None:
    """Unknown text/probability aliases cannot silently survive a lexical change."""
    if set(word) - CHANGED_WORD_KEYS:
        raise RuntimeError("text correction changed-word metadata is unsupported; lexical/confidence aliases forbidden")
    for key in ("speaker", "id"):
        if key in word:
            _identity(word[key])


def _change(result: dict, change: dict, locations: list[tuple]) -> int:
    """Change one indexed word only; old model confidence cannot describe new text."""
    index = change["sourceWordIndex"]
    if index >= len(locations):
        raise RuntimeError("text correction source word index does not exist")
    row_index, word_index, original = locations[index]
    _changed_word_fields(original)
    old, new = lexical_word(original["word"]), lexical_word(change["newWord"])
    if old == new:
        raise RuntimeError("text correction contains unchanged text")
    word = result["transcript"][row_index]["words"][word_index]
    word["word"] = new
    word.pop("confidence", None)
    return row_index


def rewrite_text(payload: dict, proposed: dict, locations: list[tuple]) -> dict:
    """Preserve all timings/identities and every field except exact authored text."""
    for row in payload["transcript"]:
        _row_text(row)
    result = copy.deepcopy(payload)
    touched = {_change(result, change, locations) for change in proposed["corrections"]}
    for index in touched:
        row = result["transcript"][index]
        if "text" in row:
            row["text"] = " ".join(word["word"] for word in row["words"])
    return result


def text_origin() -> dict:
    """Scope human lexical evidence separately from retained historical ASR facts."""
    return {"textOrigin": "explicit-human-source-review-not-emitted-by-ASR",
            "changedWordConfidence": "removed-original-retained-in-request"}
