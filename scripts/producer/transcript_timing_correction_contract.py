"""Closed versioned source-word corrections and explicit human source decisions."""
from __future__ import annotations

import math
import re

from transcript_timing_review_contract import closed, hash_value, parse_json, record_bytes
from transcript_timing_correction_text import lexical_word

POLICY = "sniper-source-word-timing-correction-v1"
MAX_CORRECTIONS = 128
MAX_INPUT_BYTES = 1024 * 1024
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
SCOPE = "explicit-human-boundary-correction-not-model-alignment-or-edit-approval"
TEXT_POLICY = "sniper-source-word-text-correction-v2"
TEXT_SCOPE = "explicit-human-source-faithful-text-correction-not-model-output-or-edit-approval"


def correction_profile(version: object) -> dict:
    """Keep v1 bytes/semantics distinct; a new version never upgrades old records."""
    if type(version) is not int or version not in (1, 2):
        raise RuntimeError("unsupported source word correction version")
    if version == 1:
        return {"schemaVersion": 1, "policy": POLICY, "scope": SCOPE,
                "kindPrefix": "source-word-timing-correction", "marker": "timingCorrectionAuthority",
                "actor": "explicit-local-operator-boundary-attestation"}
    return {"schemaVersion": 2, "policy": TEXT_POLICY, "scope": TEXT_SCOPE,
            "kindPrefix": "source-word-text-correction", "marker": "sourceWordCorrectionAuthority",
            "actor": "explicit-local-operator-source-transcription-attestation"}


def number(value: object, label: str) -> float:
    """Accept finite JSON numbers without booleans or coercion."""
    if type(value) not in (int, float):
        raise RuntimeError(f"timing correction {label} must be finite")
    try:
        result = float(value)
    except OverflowError as exc:
        raise RuntimeError(f"timing correction {label} must be finite") from exc
    if not math.isfinite(result):
        raise RuntimeError(f"timing correction {label} must be finite")
    return result


def identifier(value: object) -> str:
    """Require an explicit UUIDv4 identity; never manufacture a human request."""
    if type(value) is not str or UUID.fullmatch(value) is None:
        raise RuntimeError("timing correction identity must be UUIDv4")
    return value


def proposal(value: object) -> dict:
    """Parse one explicitly versioned proposal against held parent hashes."""
    keys = {"schemaVersion", "operation", "requestId", "sourceId", "expectedPlanSha256",
            "expectedManifestSha256", "expectedTranscriptSha256", "corrections"}
    row = closed(value, keys, "correction proposal")
    profile = correction_profile(row["schemaVersion"])
    if row["operation"] != "propose-" + profile["kindPrefix"]:
        raise RuntimeError("unsupported timing correction proposal")
    identifier(row["requestId"])
    if type(row["sourceId"]) is not str or re.fullmatch(r"raw-[1-9][0-9]*", row["sourceId"]) is None:
        raise RuntimeError("timing correction sourceId must use raw-N vocabulary")
    for key in ("expectedPlanSha256", "expectedManifestSha256", "expectedTranscriptSha256"):
        hash_value(row[key], key)
    corrections = row["corrections"]
    if type(corrections) is not list or not 1 <= len(corrections) <= MAX_CORRECTIONS:
        raise RuntimeError("timing correction requires 1–128 changes")
    indices = [_change(item, row["schemaVersion"]) for item in corrections]
    if indices != sorted(set(indices)):
        raise RuntimeError("timing correction word indices must be sorted and unique")
    record_bytes(row)
    return row


def _change(value: object, version: int) -> int:
    """Keep closed text-only and timing-only fields from crossing versions."""
    keys = {"sourceWordIndex", "newStart", "newEnd"} if version == 1 else {"sourceWordIndex", "newWord"}
    row = closed(value, keys, "versioned word change")
    index = row["sourceWordIndex"]
    if type(index) is not int or index < 0:
        raise RuntimeError("timing correction word index is invalid")
    if version == 2:
        lexical_word(row["newWord"])
        return index
    start, end = number(row["newStart"], "newStart"), number(row["newEnd"], "newEnd")
    if not 0 <= start < end:
        raise RuntimeError("timing correction interval must be positive and nonnegative")
    return index


def _review(value: object, correction: dict, version: int) -> None:
    """Match every supplied human boundary/source-window attestation exactly."""
    compare = "comparedOriginalAndProposedBounds" if version == 1 else "comparedOriginalAndProposedText"
    keys = {"correctionHash", "listenedToSourceWindows", compare, "rationale"}
    if version == 2:
        keys.add("confirmsSourceFaithfulTranscription")
    row = closed(value, keys, "boundary review")
    if row["correctionHash"] != correction["correctionHash"] \
            or row[compare] is not True:
        raise RuntimeError("timing correction requires exact explicit boundary comparison")
    if version == 2 and row["confirmsSourceFaithfulTranscription"] is not True:
        raise RuntimeError("text correction requires explicit source-faithful transcription confirmation")
    rationale = row["rationale"]
    if type(rationale) is not str or not 12 <= len(rationale.strip()) <= 2000 \
            or any(ord(c) < 32 for c in rationale):
        raise RuntimeError("timing correction rationale must be bounded plain text")
    windows, reviewed = correction["sourceWindows"], row["listenedToSourceWindows"]
    if type(reviewed) is not list or len(reviewed) != len(windows):
        raise RuntimeError("timing correction requires every source window attestation")
    for item, window in zip(reviewed, windows):
        held = closed(item, {"windowHash", "listened"}, "source audition")
        if held["windowHash"] != window["windowHash"] or held["listened"] is not True:
            raise RuntimeError("timing correction cannot infer source listening")


def submission(value: object, request: dict) -> dict:
    """Require supplied human attestations, not artifact-existence inference."""
    keys = {"schemaVersion", "operation", "requestHash", "idempotencyKey", "expectedRecordHash", "reviews"}
    row = closed(value, keys, "correction submission")
    profile = correction_profile(request["schemaVersion"])
    if type(row["schemaVersion"]) is not int or row["schemaVersion"] != profile["schemaVersion"] \
            or row["operation"] != "record-" + profile["kindPrefix"] \
            or row["requestHash"] != request["requestHash"] or row["expectedRecordHash"] is not None:
        raise RuntimeError("timing correction request or single-record CAS does not match")
    identifier(row["idempotencyKey"])
    reviews = row["reviews"]
    if type(reviews) is not list or len(reviews) != len(request["corrections"]):
        raise RuntimeError("timing correction must review each exact change once")
    for review, correction in zip(reviews, request["corrections"]):
        _review(review, correction, profile["schemaVersion"])
    record_bytes(row)
    return row
