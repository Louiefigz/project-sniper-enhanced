"""Experimental ordinary-token envelopes, not the production ASR parser.

Do not select this as the default until internal timing uncertainty is preserved
and gated by every consumer. A complete recognized word can have a zero token
interval; rejecting that entire source is not a usable production migration.
"""

from __future__ import annotations

import re
from typing import Optional
from local_whisper_tokens import (
    PARSER_POLICY, WhisperParseError, finite_number, token_words,
)


def _as_utterance(words: list[dict]) -> dict:
    text = " ".join(w["word"] for w in words)
    return {"start": words[0]["start"], "end": words[-1]["end"],
            "text": text, "words": words}


def _break_before(current: list[dict], word: dict) -> bool:
    previous = current[-1]
    if previous.get("speaker") != word.get("speaker"):
        return True
    if word["start"] - previous["end"] >= 0.8:
        return True
    return len(current) >= 40 or word["end"] - current[0]["start"] >= 15.0


def shape_utterances(words: list[dict]) -> list[dict]:
    """Group timestamped words into bounded sentence-like utterances."""
    utterances: list[dict] = []
    current: list[dict] = []
    for word in words:
        if current and _break_before(current, word):
            utterances.append(_as_utterance(current))
            current = []
        current.append(word)
        if re.search(r"[.!?][\"']?$", word["word"]):
            utterances.append(_as_utterance(current))
            current = []
    if current:
        utterances.append(_as_utterance(current))
    return utterances


def parse_whisper_json(payload: dict, timeline_offset: float = 0.0,
                       speaker: Optional[int] = None) -> list[dict]:
    """Parse token bounds; signed finite source-PTS offsets are never clamped."""
    rows = payload.get("transcription") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise WhisperParseError("whisper JSON has no transcription array")
    offset = finite_number(timeline_offset, "timeline offset")
    if speaker is not None and (isinstance(speaker, bool) or not isinstance(speaker, int)):
        raise WhisperParseError("speaker must be an integer or absent")
    words = token_words(rows, payload.get("model"))
    for word in words:
        word["start"] = finite_number(word["start"] + offset, "word start")
        word["end"] = finite_number(word["end"] + offset, "word end")
        if word["start"] >= word["end"]:
            raise WhisperParseError("timeline offset collapses the word interval")
        if speaker is not None:
            word["speaker"] = speaker
    return shape_utterances(words)
