"""Occurrence-aware, stable-word target resolution for P2 cut repair."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable, Sequence

from edit.exact_timing import SampleRange, TimingContractError


class TargetResolutionError(ValueError):
    """A phrase target cannot be resolved safely."""


class TargetNotFoundError(TargetResolutionError):
    """No transcript range matches the requested target."""


class TargetAmbiguousError(TargetResolutionError):
    """More than one transcript range still matches."""

def _tokens(value: object) -> list[str]:
    """Unicode-alphanumeric exact tokens; punctuation is not semantic."""
    tokens: list[str] = []
    current: list[str] = []
    for char in str(value).casefold():
        if char.isalnum():
            current.append(char)
            continue
        if current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return tokens


@dataclass(frozen=True)
class WordRef:
    """One controller-minted transcript word on an exact source sample clock."""

    word_id: str
    source_id: str
    index: int
    text: str
    samples: SampleRange
    speaker: str | None
    transcript_timing_hash: str


def _word_id(source_id: str, index: int) -> str:
    payload = f"sniper-caption-word-v1\0{source_id}\0{index}".encode()
    return f"w-{hashlib.sha256(payload).hexdigest()[:16]}"


def build_word_refs(source_id: str, rows: Sequence[dict],
                    timing_hash: str) -> list[WordRef]:
    """Build stable words from exact-sample transcript rows."""
    if not source_id or len(timing_hash) != 64 \
            or any(char not in "0123456789abcdef" for char in timing_hash):
        raise TargetResolutionError("word authority requires source and timing hashes")
    words: list[WordRef] = []
    previous_end = 0
    for index, row in enumerate(rows):
        text = str(row.get("word", row.get("text", ""))).strip()
        try:
            samples = SampleRange(row["startSample"], row["endSampleExclusive"])
        except (KeyError, TypeError, ValueError, TimingContractError) as exc:
            raise TargetResolutionError(
                f"word[{index}] has invalid exact sample timing") from exc
        if not text or samples.start_sample < previous_end:
            raise TargetResolutionError(
                f"word[{index}] is empty, overlapping, or out of order")
        speaker_value = row.get("speaker")
        speaker = None if speaker_value is None else str(speaker_value)
        words.append(WordRef(
            _word_id(source_id, index),
            source_id, index, text, samples, speaker, timing_hash))
        previous_end = samples.end_sample_exclusive
    if not words:
        raise TargetResolutionError("transcript contains no exact words")
    return words


@dataclass(frozen=True)
class PhraseTarget:
    """Operator phrase plus deterministic disambiguators."""

    phrase: str
    source_id: str | None = None
    occurrence: int | None = None
    speaker: str | None = None
    before_context: str | None = None
    after_context: str | None = None
    approximate_source_sample: int | None = None
    tolerance_samples: int | None = None


@dataclass(frozen=True)
class ResolvedWordRange:
    """One unique contiguous transcript range."""

    source_id: str
    word_ids: tuple[str, ...]
    first_word_index: int
    last_word_index: int
    occurrence: int
    samples: SampleRange
    text: str
    speaker: str | None
    transcript_timing_hash: str

    def to_dict(self) -> dict[str, object]:
        """Return the closed word-range target fields."""
        return {
            "kind": "word-range",
            "sourceId": self.source_id,
            "wordIds": list(self.word_ids),
            "occurrence": self.occurrence,
            "sourceSampleRange": self.samples.to_dict(),
            "transcriptTimingHash": self.transcript_timing_hash,
        }


@dataclass(frozen=True)
class _Match:
    words: tuple[WordRef, ...]
    occurrence: int


def _token_stream(words: Sequence[WordRef]) -> tuple[list[str], list[int]]:
    tokens: list[str] = []
    owners: list[int] = []
    for index, word in enumerate(words):
        for token in _tokens(word.text):
            tokens.append(token)
            owners.append(index)
    return tokens, owners


def _validate_words(words: Sequence[WordRef]) -> None:
    seen_ids: set[str] = set()
    previous: dict[str, WordRef] = {}
    for word in words:
        prior = previous.get(word.source_id)
        malformed = (not word.source_id or word.word_id in seen_ids
                     or type(word.index) is not int or word.index < 0
                     or word.word_id != _word_id(word.source_id, word.index))
        drifted = prior is not None and (
            word.index <= prior.index
            or word.samples.start_sample < prior.samples.end_sample_exclusive
            or word.transcript_timing_hash != prior.transcript_timing_hash)
        if malformed or drifted:
            raise TargetResolutionError(
                "word authority has duplicate identity, timing drift, or bad order")
        seen_ids.add(word.word_id)
        previous[word.source_id] = word


def _matches(words: Sequence[WordRef], phrase: str) -> list[_Match]:
    needle = _tokens(phrase)
    if not needle:
        raise TargetResolutionError("target phrase contains no searchable tokens")
    tokens, owners = _token_stream(words)
    found: list[_Match] = []
    seen: set[tuple[int, int]] = set()
    occurrences: dict[str, int] = {}
    for offset in range(0, len(tokens) - len(needle) + 1):
        if tokens[offset:offset + len(needle)] != needle:
            continue
        last_offset = offset + len(needle) - 1
        if offset > 0 and owners[offset - 1] == owners[offset]:
            continue
        if last_offset + 1 < len(owners) \
                and owners[last_offset + 1] == owners[last_offset]:
            continue
        bounds = owners[offset], owners[last_offset]
        if bounds in seen:
            continue
        seen.add(bounds)
        selected = tuple(words[bounds[0]:bounds[1] + 1])
        sources = {word.source_id for word in selected}
        if len(sources) != 1:
            continue
        source_id = selected[0].source_id
        occurrences[source_id] = occurrences.get(source_id, 0) + 1
        found.append(_Match(selected, occurrences[source_id]))
    return found


def _context_matches(match: _Match, words: Sequence[WordRef],
                     target: PhraseTarget) -> bool:
    owned = [word for word in words
             if word.source_id == match.words[0].source_id]
    first = next(index for index, word in enumerate(owned)
                 if word.word_id == match.words[0].word_id)
    last = next(index for index, word in enumerate(owned)
                if word.word_id == match.words[-1].word_id)
    if target.before_context is not None:
        expected = _tokens(target.before_context)
        actual = [token for word in owned[:first] for token in _tokens(word.text)]
        if not expected or actual[-len(expected):] != expected:
            return False
    if target.after_context is not None:
        expected = _tokens(target.after_context)
        actual = [token for word in owned[last + 1:]
                  for token in _tokens(word.text)]
        if not expected or actual[:len(expected)] != expected:
            return False
    return True


def _matches_target(match: _Match, words: Sequence[WordRef],
                    target: PhraseTarget) -> bool:
    selected = match.words
    if len({word.source_id for word in selected}) != 1:
        return False
    if target.source_id is not None \
            and any(word.source_id != target.source_id for word in selected):
        return False
    if target.speaker is not None \
            and any(word.speaker != target.speaker for word in selected):
        return False
    speakers = {word.speaker for word in selected if word.speaker is not None}
    if len(speakers) > 1:
        return False
    if not _context_matches(match, words, target):
        return False
    if target.approximate_source_sample is None:
        return True
    if type(target.approximate_source_sample) is not int or \
            target.approximate_source_sample < 0 \
            or type(target.tolerance_samples) is not int \
            or target.tolerance_samples < 0:
        raise TargetResolutionError("approximate sample/tolerance is invalid")
    middle = (selected[0].samples.start_sample
              + selected[-1].samples.end_sample_exclusive) // 2
    return abs(middle - target.approximate_source_sample) \
        <= target.tolerance_samples


def _selected_match(candidates: list[_Match],
                    target: PhraseTarget) -> _Match:
    if target.occurrence is not None:
        if type(target.occurrence) is not int or target.occurrence <= 0:
            raise TargetResolutionError("occurrence is one-based and must be positive")
        hits = [row for row in candidates if row.occurrence == target.occurrence]
        if not hits:
            raise TargetNotFoundError(
                f"phrase occurrence {target.occurrence} did not match the supplied context")
        if len(hits) > 1:
            raise TargetAmbiguousError(
                "occurrence is source-local; supply source or more context")
        return hits[0]
    if not candidates:
        raise TargetNotFoundError("phrase did not match the supplied transcript authority")
    if len(candidates) > 1:
        occurrences = [row.occurrence for row in candidates]
        raise TargetAmbiguousError(
            f"phrase remains ambiguous across occurrences {occurrences}")
    return candidates[0]


def resolve_phrase(words: Sequence[WordRef],
                   target: PhraseTarget) -> ResolvedWordRange:
    """Resolve one phrase or fail closed on zero/multiple occurrences."""
    if not words:
        raise TargetResolutionError("word authority is empty")
    _validate_words(words)
    filtered = [row for row in _matches(words, target.phrase)
                if _matches_target(row, words, target)]
    match = _selected_match(filtered, target)
    selected = match.words
    speakers = {word.speaker for word in selected if word.speaker is not None}
    return ResolvedWordRange(
        source_id=selected[0].source_id,
        word_ids=tuple(word.word_id for word in selected),
        first_word_index=selected[0].index,
        last_word_index=selected[-1].index,
        occurrence=match.occurrence,
        samples=SampleRange(selected[0].samples.start_sample,
                            selected[-1].samples.end_sample_exclusive),
        text=" ".join(word.text for word in selected),
        speaker=next(iter(speakers)) if speakers else None,
        transcript_timing_hash=selected[0].transcript_timing_hash,
    )


def protected_word_ranges(words: Iterable[WordRef],
                          target: ResolvedWordRange) -> tuple[SampleRange, ...]:
    """Return same-source speech ranges except the resolved repair words."""
    selected = set(target.word_ids)
    return tuple(word.samples for word in words
                 if word.source_id == target.source_id
                 and word.word_id not in selected)
