#!/usr/bin/env python3
"""Deterministic stable-word range operations for CaptionTrackV1."""
from __future__ import annotations

import copy
import hashlib

from captions.caption_contract import (
    CaptionContractError,
    validate_caption_track,
    validate_correction_ledger,
)

_RANGE_KEYS = {
    "wordIds", "styleId", "mode", "placement", "language",
    "suppressUnderSceneIds",
}
_CORRECTION_KEYS = {"sourceWordIds", "displayTokens", "reason"}


def _stable_id(prefix: str, domain: str, values: list[str]) -> str:
    payload = (domain + "\0" + "\0".join(values)).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(payload).hexdigest()[:16]}"


def new_caption_track(default_policy: str = "off") -> dict:
    """Create an empty validated first-class caption track."""
    return validate_caption_track({
        "schemaVersion": 1, "source": "kept-transcript",
        "defaultPolicy": default_policy, "groups": [],
    })


def _exact_request(value: object, allowed: set[str], required: set[str],
                   label: str) -> dict:
    if not isinstance(value, dict):
        raise CaptionContractError(f"{label} must be an object")
    unknown, missing = set(value) - allowed, required - set(value)
    if unknown or missing:
        detail = sorted(unknown or missing)
        kind = "unknown" if unknown else "missing"
        raise CaptionContractError(
            f"{label} has {kind} fields: {', '.join(detail)}")
    return value


def _range_group(request: object) -> dict:
    row = _exact_request(
        request, _RANGE_KEYS,
        {"wordIds", "styleId", "mode", "placement"},
        "CaptionRangeStyleV1")
    word_ids = row["wordIds"]
    if not isinstance(word_ids, list):
        raise CaptionContractError("CaptionRangeStyleV1.wordIds must be a list")
    group = {
        "groupId": _stable_id(
            "cg", "sniper-caption-group-v1", [str(item) for item in word_ids]),
        "anchor": {"kind": "word-range", "wordIds": list(word_ids)},
        "styleId": row["styleId"], "mode": row["mode"],
        "placement": row["placement"],
    }
    for key in ("language", "suppressUnderSceneIds"):
        if key in row:
            group[key] = copy.deepcopy(row[key])
    return group


def upsert_caption_range(track: object, request: object) -> dict:
    """Add or replace one exact stable-word caption range."""
    current = validate_caption_track(track)
    group = _range_group(request)
    groups = list(current["groups"])
    matches = [index for index, row in enumerate(groups)
               if row["groupId"] == group["groupId"]]
    if len(matches) > 1:
        raise CaptionContractError("caption group identity is ambiguous")
    if matches:
        if groups[matches[0]]["anchor"] != group["anchor"]:
            raise CaptionContractError("caption group identity collision")
        groups[matches[0]] = group
    else:
        groups.append(group)
    return validate_caption_track({**current, "groups": groups})


def remove_caption_range(track: object, word_ids: object) -> dict:
    """Remove exactly one group selected by its stable source-word range."""
    if not isinstance(word_ids, list):
        raise CaptionContractError("caption removal wordIds must be a list")
    current = validate_caption_track(track)
    ident = _stable_id(
        "cg", "sniper-caption-group-v1", [str(item) for item in word_ids])
    matches = [row for row in current["groups"] if row["groupId"] == ident]
    if len(matches) != 1 or matches[0]["anchor"]["wordIds"] != word_ids:
        raise CaptionContractError(
            "caption removal did not resolve exactly one stable range")
    groups = [row for row in current["groups"] if row["groupId"] != ident]
    return validate_caption_track({**current, "groups": groups})


def new_correction_ledger() -> dict:
    """Create an empty validated occurrence-bound correction authority."""
    return validate_correction_ledger({
        "schemaVersion": 1, "kind": "caption-correction-ledger",
        "corrections": [],
    })


def _correction_row(request: object) -> dict:
    row = _exact_request(
        request, _CORRECTION_KEYS,
        {"sourceWordIds", "displayTokens"}, "CorrectCaptionWordsV1")
    word_ids = row["sourceWordIds"]
    if not isinstance(word_ids, list):
        raise CaptionContractError(
            "CorrectCaptionWordsV1.sourceWordIds must be a list")
    result = {
        "correctionId": _stable_id(
            "cc", "sniper-caption-correction-v1",
            [str(item) for item in word_ids]),
        "sourceWordIds": list(word_ids),
        "displayTokens": copy.deepcopy(row["displayTokens"]),
        "timingPolicy": "proportional-codepoints",
    }
    if "reason" in row:
        result["reason"] = row["reason"]
    return result


def upsert_caption_correction(ledger: object, request: object) -> dict:
    """Correct one occurrence without text-matching any other occurrence."""
    current = validate_correction_ledger(ledger)
    correction = _correction_row(request)
    rows = list(current["corrections"])
    matches = [index for index, row in enumerate(rows)
               if row["correctionId"] == correction["correctionId"]]
    if len(matches) > 1:
        raise CaptionContractError("caption correction identity is ambiguous")
    if matches:
        if rows[matches[0]]["sourceWordIds"] != correction["sourceWordIds"]:
            raise CaptionContractError("caption correction identity collision")
        rows[matches[0]] = correction
    else:
        rows.append(correction)
    return validate_correction_ledger({**current, "corrections": rows})
