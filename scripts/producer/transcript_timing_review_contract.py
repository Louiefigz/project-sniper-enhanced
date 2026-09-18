"""Closed, source-bound human timing-review records; never general cut approval."""
from __future__ import annotations

from datetime import datetime
import json
import re

from cut_preview_io import digest
from cross_runtime_canonical_json import canonical_compact_json

POLICY = "sniper-source-timing-review-v1"
MAX_RECORD_BYTES = 1024 * 1024
MAX_ANOMALIES = 128
MAX_DECISIONS = 32
SHA = re.compile(r"[0-9a-f]{64}")
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
DISPOSITIONS = {"kept-audited", "excluded-abandoned-start-audited", "unresolved"}
SUBMISSION_KEYS = {"schemaVersion", "operation", "requestHash", "idempotencyKey",
                   "expectedPreviousDecisionHash", "reviews"}


def closed(value: object, keys: set[str], label: str) -> dict:
    """Require one exact object without coercion or unknown authority fields."""
    if type(value) is not dict or set(value) != keys:
        raise RuntimeError(f"timing review {label} has unknown or missing fields")
    return value


def hash_value(value: object, label: str) -> str:
    """Reject malformed or coerced digest tokens."""
    if type(value) is not str or SHA.fullmatch(value) is None:
        raise RuntimeError(f"timing review {label} is not a SHA-256")
    return value


def record_bytes(value: dict) -> bytes:
    """One bounded byte representation; self-hashes are integrity, not consent."""
    raw = (canonical_compact_json(value) + "\n").encode("utf-8")
    if len(raw) > MAX_RECORD_BYTES:
        raise RuntimeError("timing review record exceeds its byte budget")
    return raw


def _pairs(pairs: list[tuple]) -> dict:
    row = {}
    for key, value in pairs:
        if key in row:
            raise RuntimeError("timing review JSON repeats an object key")
        row[key] = value
    return row


def parse_json(raw: bytes) -> object:
    """Reject duplicate keys and non-finite values before accepting a record."""
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
    canonical_compact_json(value)  # Reject non-finite or invalid UTF-8 domain values.
    return value


def _text(value: object) -> None:
    if type(value) is not str or not 12 <= len(value.strip()) <= 2000 \
            or any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise RuntimeError("timing review rationale must be bounded plain UTF-8 text")


def _review(value: object, anomaly: dict) -> dict:
    row = closed(value, {"anomalyHash", "disposition", "sourceWindows",
                         "listenedToSourceWindows", "comparedExactCutBoundary",
                         "rationale"}, "row")
    _text(row["rationale"])
    expected = ("kept-audited" if anomaly["finding"]["position"] == "kept_opening"
                else "excluded-abandoned-start-audited")
    if row["anomalyHash"] != anomaly["anomalyHash"] \
            or digest(row["sourceWindows"]) != digest(anomaly["sourceWindows"]) \
            or type(row["disposition"]) is not str or row["disposition"] not in DISPOSITIONS \
            or row["disposition"] not in {"unresolved", expected}:
        raise RuntimeError("timing review disposition/window/anomaly binding changed")
    if type(row["comparedExactCutBoundary"]) is not bool:
        raise RuntimeError("timing review requires explicit human attestations")
    listened = _listening(row["listenedToSourceWindows"], anomaly["sourceWindows"])
    if row["disposition"] != "unresolved" and (not listened or not row["comparedExactCutBoundary"]):
        raise RuntimeError("timing review cannot infer listening or boundary review")
    return row


def _listening(value: object, windows: list[dict]) -> bool:
    if type(value) is not list or len(value) != len(windows):
        raise RuntimeError("timing review must explicitly address both source contexts")
    listened = []
    for item, window in zip(value, windows):
        row = closed(item, {"windowHash", "listened"}, "window attestation")
        if row["windowHash"] != window["windowHash"] or type(row["listened"]) is not bool:
            raise RuntimeError("timing review window attestation is not exact")
        listened.append(row["listened"])
    return all(listened)


def submission(value: object, request: dict) -> dict:
    """Parse a supplied decision only; never synthesize human attestations."""
    row = closed(value, SUBMISSION_KEYS, "submission")
    if type(row["schemaVersion"]) is not int or row["schemaVersion"] != 1 \
            or row["operation"] != "record-source-timing-review" \
            or row["requestHash"] != request["requestHash"] \
            or type(row["idempotencyKey"]) is not str \
            or UUID.fullmatch(row["idempotencyKey"]) is None:
        raise RuntimeError("timing review submission identity is invalid")
    if row["expectedPreviousDecisionHash"] is not None:
        hash_value(row["expectedPreviousDecisionHash"], "previous decision")
    reviews, anomalies = row["reviews"], request["anomalies"]
    if type(reviews) is not list or len(reviews) != len(anomalies):
        raise RuntimeError("timing review must address every exact anomaly once")
    for review, anomaly in zip(reviews, anomalies):
        _review(review, anomaly)
    return row


def decision(value: object, request: dict) -> dict:
    """Validate an immutable record, including its complete original submission."""
    keys = {"schemaVersion", "kind", "policy", "actor", "requestHash", "sequence",
            "previousDecisionHash", "recordedAt", "submission", "decisionHash"}
    row = closed(value, keys, "decision")
    sent = submission(row["submission"], request)
    if type(row["schemaVersion"]) is not int or row["schemaVersion"] != 1 \
            or row["kind"] != "source-timing-review-decision" or row["policy"] != POLICY \
            or row["actor"] != "explicit-local-operator-attestation" \
            or row["requestHash"] != request["requestHash"] \
            or type(row["sequence"]) is not int or not 1 <= row["sequence"] <= MAX_DECISIONS \
            or row["previousDecisionHash"] != sent["expectedPreviousDecisionHash"]:
        raise RuntimeError("timing review decision identity is malformed")
    if type(row["recordedAt"]) is not str:
        raise RuntimeError("timing review decision timestamp is invalid")
    parsed = datetime.fromisoformat(row["recordedAt"].replace("Z", "+00:00"))
    if parsed.utcoffset() is None or not row["recordedAt"].endswith("Z"):
        raise RuntimeError("timing review decision timestamp must be UTC")
    expected = digest({key: item for key, item in row.items() if key != "decisionHash"})
    if row["decisionHash"] != expected:
        raise RuntimeError("timing review decision digest changed")
    return row
