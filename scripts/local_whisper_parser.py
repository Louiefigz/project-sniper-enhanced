"""Production compatibility parser: emitted rows with uniform word subdivision.

This is the explicit pre-token-parser contract, not token or acoustic alignment.
It retains row-span inflation, a 10ms floor, and legacy punctuation/order rules.
Strict token parsing stays experimental until uncertainty survives all consumers;
there is no try-strict-then-fallback branch or runtime parser selection knob.
"""

from __future__ import annotations

import re
from typing import Optional
PARSER_POLICY = "sniper-whisper-row-uniform-compatibility-v1"


class WhisperParseError(ValueError):
    """whisper.cpp output does not satisfy the transcript contract."""


def _confidence(row: dict) -> Optional[float]:
    """Preserve historical row averaging, including any emitted control scores."""
    values = [t.get("p") for t in row.get("tokens", [])
              if isinstance(t.get("p"), (int, float))]
    return round(sum(values) / len(values), 6) if values else None


def _row_words(row: dict, offset: float, speaker: Optional[int]) -> list[dict]:
    """Retain row intervals, uniform subdivision and the historical 10ms floor."""
    text = " ".join(str(row.get("text", "")).split())
    if not text or re.fullmatch(r"\[[A-Z_]+\]", text):
        return []
    bounds = row.get("offsets", {})
    start_ms, end_ms = bounds.get("from"), bounds.get("to")
    if not isinstance(start_ms, (int, float)) or not isinstance(end_ms, (int, float)):
        return []
    parts = text.split()
    span = max(0.01, (float(end_ms) - float(start_ms)) / 1000.0)
    confidence = _confidence(row)
    words: list[dict] = []
    for index, part in enumerate(parts):
        start = offset + float(start_ms) / 1000.0 + span * index / len(parts)
        end = offset + float(start_ms) / 1000.0 + span * (index + 1) / len(parts)
        word = {"word": part, "start": round(start, 3), "end": round(end, 3)}
        if confidence is not None:
            word["confidence"] = confidence
        if speaker is not None:
            word["speaker"] = speaker
        words.append(word)
    return words


def _merge_punctuation(words: list[dict]) -> list[dict]:
    """Keep the production punctuation-attachment compatibility behavior."""
    merged: list[dict] = []
    for word in words:
        if merged and re.fullmatch(r"[.,!?;:]+", word["word"]):
            merged[-1]["word"] += word["word"]
            merged[-1]["end"] = max(merged[-1]["end"], word["end"])
        else:
            merged.append(word)
    return merged


def _as_utterance(words: list[dict]) -> dict:
    """Preserve production text normalization, without asserting token fidelity."""
    text = " ".join(w["word"] for w in words)
    text = re.sub(r"\s+([.,!?;:])", r"\1", text)
    return {"start": words[0]["start"], "end": words[-1]["end"],
            "text": text, "words": words}


def _break_before(current: list[dict], word: dict) -> bool:
    """Retain existing bounded speaker, gap, word-count and duration grouping."""
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
    for word in sorted(words, key=lambda item: (item["start"], item["end"])):
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
    """Use the explicit legacy row contract, never a hidden token fallback."""
    rows = payload.get("transcription")
    if not isinstance(rows, list):
        raise WhisperParseError("whisper JSON has no transcription array")
    words = [word for row in rows if isinstance(row, dict)
             for word in _row_words(row, timeline_offset, speaker)]
    words = _merge_punctuation(words)
    if not words:
        raise WhisperParseError("local Whisper returned no spoken words")
    return shape_utterances(words)
