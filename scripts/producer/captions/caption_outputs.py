#!/usr/bin/env python3
"""SRT, burned-shard, Palmier, and chapter projections from one cue compiler."""
from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

from captions.caption_contract import (
    CaptionContractError,
    WORD_ID_RE,
    caption_code_point_length,
    trim_caption_text,
)
from captions.caption_fingerprints import canonical_digest
from captions.caption_words import CaptionFrameRate, validate_resolved_words

_PUNCTUATION = re.compile(r"^[,.;:!?،؛؟%)\]}’”，。！？；：、]+$")
_COMPACT_LANGUAGE = re.compile(r"^(?:zh|ja|ko)(?:-|$)", re.IGNORECASE)
_CHAPTER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class PalmierCaptionCapabilities:
    """Measured native-caption fidelity required before native projection."""

    exact_word_timing: bool
    exact_style: bool
    complete_readback: bool
    max_detail_rows: int = 200

    def __post_init__(self) -> None:
        facts = (
            self.exact_word_timing,
            self.exact_style,
            self.complete_readback,
        )
        if any(not isinstance(value, bool) for value in facts):
            raise CaptionContractError("Palmier caption facts must be booleans")
        if isinstance(self.max_detail_rows, bool) \
                or not isinstance(self.max_detail_rows, int) \
                or self.max_detail_rows < 1:
            raise CaptionContractError(
                "Palmier caption detail row cap must be positive")


def _rate(compilation: dict) -> CaptionFrameRate:
    value = compilation.get("fps")
    if not isinstance(value, dict):
        raise CaptionContractError("caption compilation has no exact fps")
    try:
        return CaptionFrameRate(
            int(value.get("numerator")), int(value.get("denominator")))
    except (TypeError, ValueError) as exc:
        raise CaptionContractError(
            "caption compilation fps is malformed") from exc


def _cues(compilation: dict) -> list[dict]:
    rows = compilation.get("cues")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise CaptionContractError("caption compilation has no cue list")
    return rows


def cue_text(cue: dict) -> str:
    """Join display tokens without inserting spaces before punctuation."""
    result = ""
    for token in cue.get("tokens") or []:
        text = str(token.get("text", ""))
        result += display_separator(
            text, bool(result), cue.get("language")) + text
    return result


def display_separator(text: str, has_previous: bool,
                      language: object = None) -> str:
    """Return the one canonical visible separator before a display token."""
    compact = bool(_COMPACT_LANGUAGE.match(str(language or "")))
    if not has_previous or compact or _PUNCTUATION.fullmatch(text):
        return ""
    return " "


def _round_fraction(value: Fraction) -> int:
    quotient, remainder = divmod(value.numerator, value.denominator)
    return quotient + (1 if remainder * 2 >= value.denominator else 0)


def _frame_ms(frame: int, rate: CaptionFrameRate) -> int:
    return _round_fraction(
        Fraction(frame * 1000 * rate.denominator, rate.numerator))


def _srt_time(frame: int, rate: CaptionFrameRate) -> str:
    milliseconds = max(0, _frame_ms(frame, rate))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def burned_caption_projection(compilation: dict) -> list[dict]:
    """Return exact alpha-shard placements consumed by the burned renderer."""
    return [{
        "cueId": row["cueId"], "text": cue_text(row),
        "startFrame": row["startFrame"],
        "endFrameExclusive": row["endFrameExclusive"],
        "tokens": row["tokens"], "styleId": row["styleId"],
        "mode": row["mode"], "placement": row["placement"],
        "contentAssetKey": row["contentAssetKey"],
        "placedShardKey": row["placedShardKey"],
    } for row in _cues(compilation)]


def srt_records(compilation: dict) -> list[dict]:
    """Return the SRT semantic records before text serialization."""
    rate = _rate(compilation)
    return [{
        "cueId": row["cueId"], "text": cue_text(row),
        "startFrame": row["startFrame"],
        "endFrameExclusive": row["endFrameExclusive"],
        "start": _srt_time(row["startFrame"], rate),
        "end": _srt_time(row["endFrameExclusive"], rate),
    } for row in _cues(compilation)]


def build_srt(compilation: dict) -> str:
    """Serialize the same compiled cues used by burned/Palmier outputs."""
    chunks = [
        f"{index}\n{row['start']} --> {row['end']}\n{row['text']}\n"
        for index, row in enumerate(srt_records(compilation), start=1)
    ]
    return "\n".join(chunks)


def assert_srt_burned_parity(compilation: dict) -> None:
    """Fail if SRT and burned projections differ in cue text or frame range."""
    burned = burned_caption_projection(compilation)
    srt = srt_records(compilation)
    left = [(row["cueId"], row["text"], row["startFrame"],
             row["endFrameExclusive"]) for row in burned]
    right = [(row["cueId"], row["text"], row["startFrame"],
              row["endFrameExclusive"]) for row in srt]
    if left != right:
        raise CaptionContractError("SRT and burned caption projections diverge")


def _native_allowed(cues: list[dict],
                    capability: PalmierCaptionCapabilities) -> bool:
    facts = (
        capability.exact_word_timing,
        capability.exact_style,
        capability.complete_readback,
    )
    return all(facts) and len(cues) <= capability.max_detail_rows


def _native_projection(cues: list[dict]) -> dict:
    return {
        "schemaVersion": 1, "kind": "native-caption-cues",
        "fidelity": "exact", "readbackRequired": True,
        "entries": [{
            "captionGroupId": row["cueId"], "content": cue_text(row),
            "startFrame": row["startFrame"],
            "endFrameExclusive": row["endFrameExclusive"],
            "tokens": [{
                "content": token["text"],
                "startFrame": token["startFrame"],
                "endFrameExclusive": token["endFrameExclusive"],
            } for token in row["tokens"]],
            "styleId": row["styleId"], "mode": row["mode"],
            "placement": row["placement"],
            "expectedFingerprint": row["captionCueFingerprint"],
        } for row in cues],
    }


def _alpha_projection(cues: list[dict]) -> dict:
    return {
        "schemaVersion": 1, "kind": "regenerable-alpha-captions",
        "fidelity": "baked-regenerable", "readbackRequired": True,
        "entries": [{
            "elementId": row["cueId"],
            "assetKey": row["contentAssetKey"],
            "placementKey": row["placedShardKey"],
            "startFrame": row["startFrame"],
            "endFrameExclusive": row["endFrameExclusive"],
            "regenerable": True,
        } for row in cues],
    }


def project_captions_to_palmier(
        compilation: dict,
        capability: PalmierCaptionCapabilities) -> dict:
    """Use native cues only under complete measured fidelity, else alpha."""
    cues = _cues(compilation)
    if _native_allowed(cues, capability):
        return _native_projection(cues)
    return _alpha_projection(cues)


def _chapter_anchor(row: object) -> dict:
    if not isinstance(row, dict) or set(row) != {
            "chapterId", "title", "wordId"}:
        raise CaptionContractError("chapter anchor is malformed")
    if not isinstance(row["chapterId"], str) \
            or not _CHAPTER_ID.fullmatch(row["chapterId"]):
        raise CaptionContractError("chapter id is malformed")
    if not isinstance(row["title"], str) \
            or not trim_caption_text(row["title"]) \
            or caption_code_point_length(row["title"]) > 500 \
            or "\n" in row["title"] or "\r" in row["title"]:
        raise CaptionContractError("chapter title is empty")
    if not isinstance(row["wordId"], str) \
            or not WORD_ID_RE.fullmatch(row["wordId"]):
        raise CaptionContractError("chapter word id is malformed")
    return {
        "chapterId": row["chapterId"],
        "title": trim_caption_text(row["title"]),
        "wordId": row["wordId"],
    }


def validate_chapter_anchors(chapters: object) -> list[dict]:
    """Validate the strict semantic chapter plan vocabulary."""
    if not isinstance(chapters, list):
        raise CaptionContractError("captionChapters must be a list")
    rows = [_chapter_anchor(row) for row in chapters]
    chapter_ids = [row["chapterId"] for row in rows]
    word_ids = [row["wordId"] for row in rows]
    if len(chapter_ids) != len(set(chapter_ids)):
        raise CaptionContractError("chapter ids must be unique")
    if len(word_ids) != len(set(word_ids)):
        raise CaptionContractError("chapter word anchors must be unique")
    return rows


def _chapter_row(row: dict, positions: dict[str, dict]) -> dict:
    word = positions.get(row["wordId"])
    if word is None:
        raise CaptionContractError(
            f"chapter {row['chapterId']} references a non-kept word")
    return {
        **row, "startFrame": word["startFrame"],
        "sourceWordId": word["wordId"],
    }


def compile_chapters(chapters: object, words: object,
                     rate: CaptionFrameRate) -> dict:
    """Compile semantic chapter anchors from the same resolved word authority."""
    if not isinstance(rate, CaptionFrameRate):
        raise CaptionContractError("chapter projection needs an exact frame rate")
    resolved = validate_resolved_words(words)
    positions = {row["wordId"]: row for row in resolved}
    rows = [
        _chapter_row(row, positions)
        for row in validate_chapter_anchors(chapters)
    ]
    if rows != sorted(rows, key=lambda row: row["startFrame"]):
        raise CaptionContractError("chapter anchors are not in timeline order")
    projected = [{
        **row,
        "timestampMs": _frame_ms(row["startFrame"], rate),
    } for row in rows]
    return {
        "schemaVersion": 1, "kind": "caption-bound-chapters",
        "fps": rate.to_dict(), "chapters": projected,
        "digest": canonical_digest(
            "sniper-caption-bound-chapters-v1",
            {"fps": rate.to_dict(), "chapters": projected}),
    }


def _chapter_time(milliseconds: int) -> str:
    total = max(0, milliseconds // 1000)
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def build_semantic_chapters(projection: object) -> str:
    """Serialize compiled semantic chapters into YouTube chapter text."""
    if not isinstance(projection, dict) \
            or projection.get("kind") != "caption-bound-chapters":
        raise CaptionContractError("chapter projection is malformed")
    rows = projection.get("chapters")
    if not isinstance(rows, list) or any(not isinstance(row, dict)
                                         for row in rows):
        raise CaptionContractError("chapter projection rows are malformed")
    return "".join(
        f"{_chapter_time(row['timestampMs'])} {row['title']}\n"
        for row in rows
    )
