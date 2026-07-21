"""Closed caller request for one deterministic MP4 quality pass."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from .repair_intent import RepairIntentV1, parse_repair_intent
from .wire_identity import same_wire_value

_DIGEST = re.compile(r"[0-9a-f]{64}")


class QualityPassInputError(RuntimeError):
    """The caller quality-pass request is malformed or forged."""


@dataclass(frozen=True)
class QualityPassInputV1:
    """Canonical caller request for the sole no-fallback mechanical lane."""

    repair: RepairIntentV1
    repair_policy_id: str
    quality_policy_id: str
    document_json: bytes
    request_digest: str


def _canonical(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise QualityPassInputError("quality-pass JSON is not canonical") from exc
    return encoded.encode("ascii")


def parse_quality_pass_input(value: object) -> QualityPassInputV1:
    """Parse exact V1 input; no semantic fallback or alternate realization."""
    keys = {
        "fallbackPolicy",
        "operation",
        "qualityPolicyId",
        "realizationKind",
        "repairIntent",
        "repairPolicyId",
        "schemaVersion",
    }
    valid = (
        type(value) is dict
        and set(value) == keys
        and type(value.get("schemaVersion")) is int
        and value["schemaVersion"] == 1
        and value["operation"] == "quality-pass"
        and value["realizationKind"] == "deterministic-mp4"
        and value["fallbackPolicy"] == "none"
        and all(
            type(value.get(key)) is str and bool(_DIGEST.fullmatch(value[key]))
            for key in ("qualityPolicyId", "repairPolicyId")
        )
    )
    if not valid:
        raise QualityPassInputError("quality-pass envelope is invalid")
    try:
        repair = parse_repair_intent(value["repairIntent"])
    except RuntimeError as exc:
        raise QualityPassInputError(str(exc)) from exc
    raw = _canonical(value)
    digest = hashlib.sha256(b"sniper-quality-pass-input-v1\0" + raw).hexdigest()
    return QualityPassInputV1(
        repair, value["repairPolicyId"], value["qualityPolicyId"], raw, digest
    )


def validate_quality_pass_input(value: object) -> None:
    """Reject direct dataclass construction that bypassed the parser."""
    if type(value) is not QualityPassInputV1:
        raise QualityPassInputError("quality-pass input instance is invalid")
    try:
        parsed = parse_quality_pass_input(json.loads(value.document_json))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualityPassInputError("quality-pass input bytes are invalid") from exc
    if not same_wire_value(value, parsed):
        raise QualityPassInputError("quality-pass input identity is invalid")
