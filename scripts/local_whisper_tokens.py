"""Strict ordinary whisper.cpp token envelopes, not acoustic alignment.

Whitespace boundaries must exist between tokens, never inside a token. Unicode
text is preserved exactly; this does not assert linguistic word segmentation.
DTW points are deliberately unused. Unknown or partial timing is not repaired.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
import unicodedata

PARSER_POLICY = "sniper-whisper-ordinary-token-envelopes-v1"
_CONTROL = re.compile(r"\[_BEG_\]|\[_TT_([1-9][0-9]{0,3})\]")


class WhisperParseError(ValueError):
    """Whisper output cannot establish complete ordinary token envelopes."""


@dataclass(frozen=True)
class TokenSpan:
    """One complete JSON text token with its unmodified millisecond interval."""

    text: str
    start_ms: float
    end_ms: float
    confidence: float | None


def finite_number(value: object, label: str) -> float:
    """Reject coercion, booleans and nonfinite values at the timing boundary."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WhisperParseError(f"{label} must be a finite number")
    try:
        parsed = float(value)
    except OverflowError as exc:
        raise WhisperParseError(f"{label} must be a finite number") from exc
    if not math.isfinite(parsed):
        raise WhisperParseError(f"{label} must be a finite number")
    return parsed


def _bounds(value: object) -> tuple[float, float]:
    """Read an explicit nonnegative interval; validate lexical points as words."""
    if not isinstance(value, dict):
        raise WhisperParseError("missing explicit token/row offsets")
    start = finite_number(value.get("from"), "offset from")
    end = finite_number(value.get("to"), "offset to")
    if not 0 <= start <= end:
        raise WhisperParseError("negative or reversed token/row offsets")
    return start, end


def punctuation(text: str) -> bool:
    """Identify punctuation characters, without inferring a spoken duration."""
    return bool(text) and all(unicodedata.category(char).startswith("P") for char in text)


def _text(value: object) -> str:
    """Require lossless Unicode text rather than stringifying malformed JSON."""
    if not isinstance(value, str):
        raise WhisperParseError("token/row text must be a string")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise WhisperParseError("incomplete Unicode token/row text") from exc
    if "\ufffd" in value or any(unicodedata.category(c) == "Cc" and not c.isspace() for c in value):
        raise WhisperParseError("lossy or control-character token/row text")
    return value


def _confidence(token: dict) -> float | None:
    """Keep absent confidence unknown; never average control-token scores."""
    if "p" not in token:
        return None
    probability = finite_number(token["p"], "token confidence")
    if not 0 <= probability <= 1:
        raise WhisperParseError("token confidence is outside [0,1]")
    return probability


def _control(text: str, token: dict, timestamp_base: int | None) -> bool:
    """Recognize matching model-specific BEGIN or timestamp IDs 1 through 1500."""
    match = _CONTROL.fullmatch(text)
    if match is None:
        return False
    index = int(match.group(1)) if match.group(1) is not None else 0
    if index > 1500 or timestamp_base is None or token.get("id") != timestamp_base + index:
        raise WhisperParseError("unknown or mismatched control token id/model/index")
    return True


def _token(value: object, row_bounds: tuple[float, float], timestamp_base: int | None) -> TokenSpan | None:
    """Validate one token; exclude only recognized zero-duration controls."""
    if not isinstance(value, dict):
        raise WhisperParseError("token must be an object")
    text = _text(value.get("text"))
    start, end = _bounds(value.get("offsets"))
    if "id" in value and (type(value["id"]) is not int or value["id"] < 0):
        raise WhisperParseError("token id must be a nonnegative integer")
    if start < row_bounds[0] or end > row_bounds[1]:
        raise WhisperParseError("token offsets escape their row")
    confidence = _confidence(value)
    if _control(text, value, timestamp_base):
        if start != end:
            raise WhisperParseError("control token has a nonzero interval")
        expected = row_bounds[0] if text == "[_BEG_]" else row_bounds[1]
        if start != expected:
            raise WhisperParseError("control token is not at its explicit row boundary")
        return None
    parts = text.split()
    if len(parts) != 1 or parts[0].startswith("[_"):
        raise WhisperParseError("ambiguous multiword, empty or unknown control token")
    if parts[0] == "[BLANK_AUDIO]":
        raise WhisperParseError("non-speech placeholder has no qualified lexical timing")
    return TokenSpan(text, start, end, confidence)


def row_tokens(value: object, timestamp_base: int | None) -> tuple[tuple[float, float], list[TokenSpan]]:
    """Require complete exact row text reconstruction after control removal."""
    if not isinstance(value, dict) or not isinstance(value.get("tokens"), list) or not value["tokens"]:
        raise WhisperParseError("row must contain a nonempty token array")
    text = _text(value.get("text"))
    if text.strip() == "[BLANK_AUDIO]":
        raise WhisperParseError("non-speech placeholder has no qualified lexical timing")
    bounds = _bounds(value.get("offsets"))
    tokens = [_token(token, bounds, timestamp_base) for token in value["tokens"]]
    ordinary = [token for token in tokens if token is not None]
    if "".join(token.text for token in ordinary) != text:
        raise WhisperParseError("token text does not exactly reconstruct row text")
    if text and not ordinary:
        raise WhisperParseError("spoken row has no ordinary timed tokens")
    return bounds, ordinary


def _validate_lexical_envelope(tokens: list[TokenSpan]) -> None:
    """Require positive lexical timing; zero pieces cannot enlarge its bounds."""
    lexical = [token for token in tokens if not punctuation(token.text.strip())]
    if not lexical:
        raise WhisperParseError("punctuation has no lexical word to attach to")
    positive = [token for token in lexical if token.start_ms < token.end_ms]
    if not positive:
        raise WhisperParseError("word has nonpositive lexical duration")
    start, end = positive[0].start_ms, max(token.end_ms for token in positive)
    points = [token.start_ms for token in lexical if token.start_ms == token.end_ms]
    if any(point < start or point > end for point in points):
        raise WhisperParseError("zero lexical point is outside positive lexical envelope")


def _word(tokens: list[TokenSpan]) -> dict:
    """Envelope explicit pieces, including punctuation, without filling gaps."""
    _validate_lexical_envelope(tokens)
    start, end = tokens[0].start_ms, max(token.end_ms for token in tokens)
    if start >= end:
        raise WhisperParseError("word envelope has nonpositive duration")
    word = {"word": "".join(token.text.strip() for token in tokens),
            "start": start / 1000, "end": end / 1000}
    scores = [token.confidence for token in tokens]
    if all(score is not None for score in scores):
        word["confidence"] = round(sum(scores) / len(scores), 6)
    return word


def _boundary(current: list[TokenSpan], token: TokenSpan) -> bool:
    """Never erase real whitespace, including before an opening punctuation mark."""
    return token.text[0].isspace() or current[-1].text[-1].isspace()


def _all_tokens(rows: list, timestamp_base: int | None) -> list[TokenSpan]:
    """Flatten only complete rows, preserving and checking their source order."""
    ordinary: list[TokenSpan] = []
    previous_row_start = -1.0
    for row in rows:
        bounds, tokens = row_tokens(row, timestamp_base)
        if bounds[0] < previous_row_start:
            raise WhisperParseError("row starts move backward")
        previous_row_start = bounds[0]
        ordinary.extend(tokens)
    return ordinary


def _timestamp_base(model: object) -> int | None:
    """Bound the supported whisper.cpp vocabularies, each with 1501 timestamps."""
    vocab = model.get("vocab") if isinstance(model, dict) else None
    if type(vocab) is not int or vocab not in (51864, 51865, 51866):
        return None
    return vocab - 1501


def token_words(rows: list, model: object = None) -> list[dict]:
    """Preserve original ordering and validate it before utterance shaping."""
    words: list[dict] = []
    current: list[TokenSpan] = []
    previous_token_start = -1.0
    for token in _all_tokens(rows, _timestamp_base(model)):
        if token.start_ms < previous_token_start:
            raise WhisperParseError("token starts move backward")
        previous_token_start = token.start_ms
        if current and _boundary(current, token):
            words.append(_word(current))
            current = []
        current.append(token)
    if current:
        words.append(_word(current))
    if not words:
        raise WhisperParseError("local Whisper returned no spoken words")
    return words
