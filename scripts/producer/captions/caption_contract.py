#!/usr/bin/env python3
"""Strict runtime contracts for first-class caption authority."""
from __future__ import annotations

import copy
import re

WORD_ID_RE = re.compile(r"^w-[0-9a-f]{16}$")
GROUP_ID_RE = re.compile(r"^cg-[0-9a-f]{16}$")
CORRECTION_ID_RE = re.compile(r"^cc-[0-9a-f]{16}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
STYLE_ID_RE = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
BIDI_CONTROL_RE = re.compile(
    "[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]")
CAPTION_EDGE_WHITESPACE = (
    "\u0009\u000a\u000b\u000c\u000d"
    "\u001c\u001d\u001e\u001f\u0020\u0085\u00a0\u1680"
    "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000\ufeff"
)

_TRACK_KEYS = {
    "schemaVersion", "source", "defaultPolicy", "groups",
    "transcriptCorrectionHash",
}
_GROUP_KEYS = {
    "groupId", "anchor", "styleId", "mode", "placement", "language",
    "suppressUnderSceneIds",
}
_CORRECTION_KEYS = {
    "correctionId", "sourceWordIds", "displayTokens", "timingPolicy",
    "reason",
}
_DEFAULT_POLICIES = {"off", "line", "karaoke"}
_MODES = {"line", "karaoke-word", "karaoke-phrase"}
_PLACEMENTS = {"bottom-center", "lower-third", "center", "top-center"}


class CaptionContractError(ValueError):
    """Raised when caption authority is malformed or ambiguous."""


def caption_code_point_length(value: str) -> int:
    """Count caption text in Unicode code points, never UTF-16 units."""
    return len(value)


def trim_caption_text(value: str) -> str:
    """Trim the explicit V1 caption-edge whitespace set."""
    return value.strip(CAPTION_EDGE_WHITESPACE)


def _object(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise CaptionContractError(f"{label} must be an object")
    return value


def _exact_keys(value: dict, allowed: set[str], required: set[str],
                label: str) -> None:
    unknown = set(value) - allowed
    missing = required - set(value)
    if unknown:
        raise CaptionContractError(
            f"{label} has unknown fields: {', '.join(sorted(unknown))}")
    if missing:
        raise CaptionContractError(
            f"{label} is missing fields: {', '.join(sorted(missing))}")


def _identifier(value: object, pattern: re.Pattern[str], label: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise CaptionContractError(f"{label} is malformed")
    return value


def _string(value: object, label: str, limit: int = 500) -> str:
    if not isinstance(value, str) or not trim_caption_text(value) \
            or caption_code_point_length(value) > limit:
        raise CaptionContractError(
            f"{label} must be a non-empty string up to {limit} characters")
    return value


def _word_ids(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise CaptionContractError(f"{label} must be a non-empty list")
    result = [_identifier(item, WORD_ID_RE, f"{label}[{index}]")
              for index, item in enumerate(value)]
    if len(result) != len(set(result)):
        raise CaptionContractError(f"{label} contains duplicate word ids")
    return result


def _scene_ids(value: object, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(
            not isinstance(item, str) or not item or len(item) > 128
            for item in value):
        raise CaptionContractError(f"{label} must contain bounded scene ids")
    if len(value) != len(set(value)):
        raise CaptionContractError(f"{label} contains duplicate scene ids")
    return list(value)


def _validate_anchor(value: object, label: str) -> dict:
    anchor = _object(value, label)
    _exact_keys(anchor, {"kind", "wordIds"}, {"kind", "wordIds"}, label)
    if anchor.get("kind") != "word-range":
        raise CaptionContractError(f"{label}.kind must be word-range")
    return {"kind": "word-range",
            "wordIds": _word_ids(anchor.get("wordIds"), f"{label}.wordIds")}


def _validate_group(value: object, index: int) -> dict:
    label = f"CaptionTrackV1.groups[{index}]"
    group = _object(value, label)
    required = {"groupId", "anchor", "styleId", "mode", "placement"}
    _exact_keys(group, _GROUP_KEYS, required, label)
    result = {
        "groupId": _identifier(group.get("groupId"), GROUP_ID_RE,
                               f"{label}.groupId"),
        "anchor": _validate_anchor(group.get("anchor"), f"{label}.anchor"),
        "styleId": _identifier(group.get("styleId"), STYLE_ID_RE,
                               f"{label}.styleId"),
        "mode": group.get("mode"),
        "placement": group.get("placement"),
    }
    if result["mode"] not in _MODES:
        raise CaptionContractError(f"{label}.mode is unsupported")
    if result["placement"] not in _PLACEMENTS:
        raise CaptionContractError(f"{label}.placement is unsupported")
    if "language" in group:
        result["language"] = _identifier(
            group["language"], LANGUAGE_RE, f"{label}.language")
    if "suppressUnderSceneIds" in group:
        result["suppressUnderSceneIds"] = _scene_ids(
            group["suppressUnderSceneIds"],
            f"{label}.suppressUnderSceneIds")
    return result


def _validate_groups(value: object) -> list[dict]:
    if not isinstance(value, list):
        raise CaptionContractError("CaptionTrackV1.groups must be a list")
    groups = [_validate_group(row, index) for index, row in enumerate(value)]
    group_ids = [row["groupId"] for row in groups]
    if len(group_ids) != len(set(group_ids)):
        raise CaptionContractError("CaptionTrackV1 has duplicate group ids")
    claimed = [word_id for row in groups for word_id in row["anchor"]["wordIds"]]
    if len(claimed) != len(set(claimed)):
        raise CaptionContractError("CaptionTrackV1 groups overlap on a word id")
    return groups


def validate_caption_track(value: object) -> dict:
    """Return a defensive normalized CaptionTrackV1 copy."""
    track = _object(value, "CaptionTrackV1")
    required = {"schemaVersion", "source", "defaultPolicy", "groups"}
    _exact_keys(track, _TRACK_KEYS, required, "CaptionTrackV1")
    if track.get("schemaVersion") != 1 or track.get("source") != "kept-transcript":
        raise CaptionContractError(
            "CaptionTrackV1 has an unsupported version or source")
    policy = track.get("defaultPolicy")
    if policy not in _DEFAULT_POLICIES:
        raise CaptionContractError("CaptionTrackV1.defaultPolicy is unsupported")
    result = {
        "schemaVersion": 1, "source": "kept-transcript",
        "defaultPolicy": policy, "groups": _validate_groups(track.get("groups")),
    }
    if "transcriptCorrectionHash" in track:
        result["transcriptCorrectionHash"] = _identifier(
            track["transcriptCorrectionHash"], SHA256_RE,
            "CaptionTrackV1.transcriptCorrectionHash")
    return copy.deepcopy(result)


def _display_tokens(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise CaptionContractError(f"{label} must be a non-empty list")
    result = [_string(item, f"{label}[{index}]", 256)
              for index, item in enumerate(value)]
    if any(any(char in item for char in ("\\", "\r", "\n"))
           or BIDI_CONTROL_RE.search(item) for item in result):
        raise CaptionContractError(
            f"{label} cannot contain caption control characters")
    return result


def _validate_correction(value: object, index: int) -> dict:
    label = f"CaptionCorrectionLedgerV1.corrections[{index}]"
    row = _object(value, label)
    required = {
        "correctionId", "sourceWordIds", "displayTokens", "timingPolicy",
    }
    _exact_keys(row, _CORRECTION_KEYS, required, label)
    if row.get("timingPolicy") != "proportional-codepoints":
        raise CaptionContractError(f"{label}.timingPolicy is unsupported")
    result = {
        "correctionId": _identifier(
            row.get("correctionId"), CORRECTION_ID_RE,
            f"{label}.correctionId"),
        "sourceWordIds": _word_ids(
            row.get("sourceWordIds"), f"{label}.sourceWordIds"),
        "displayTokens": _display_tokens(
            row.get("displayTokens"), f"{label}.displayTokens"),
        "timingPolicy": "proportional-codepoints",
    }
    if "reason" in row:
        result["reason"] = _string(row["reason"], f"{label}.reason")
    return result


def validate_correction_ledger(value: object) -> dict:
    """Return a defensive normalized occurrence-bound correction ledger."""
    ledger = _object(value, "CaptionCorrectionLedgerV1")
    allowed = {"schemaVersion", "kind", "corrections"}
    _exact_keys(ledger, allowed, allowed, "CaptionCorrectionLedgerV1")
    if ledger.get("schemaVersion") != 1 \
            or ledger.get("kind") != "caption-correction-ledger":
        raise CaptionContractError(
            "CaptionCorrectionLedgerV1 has an unsupported version or kind")
    rows = ledger.get("corrections")
    if not isinstance(rows, list):
        raise CaptionContractError(
            "CaptionCorrectionLedgerV1.corrections must be a list")
    corrections = [_validate_correction(row, index)
                   for index, row in enumerate(rows)]
    identities = [row["correctionId"] for row in corrections]
    words = [item for row in corrections for item in row["sourceWordIds"]]
    if len(identities) != len(set(identities)):
        raise CaptionContractError("correction ids must be unique")
    if len(words) != len(set(words)):
        raise CaptionContractError(
            "one source word cannot belong to multiple corrections")
    return copy.deepcopy({
        "schemaVersion": 1, "kind": "caption-correction-ledger",
        "corrections": corrections,
    })
