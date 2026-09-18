"""Closed policy identity for deterministic private MP4 quality passes."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache

from .wire_identity import same_wire_value

_DIGEST = re.compile(r"[0-9a-f]{64}")
_DOMAIN = b"sniper-deterministic-quality-policy-v1\0"


class DeterministicQualityPolicyError(RuntimeError):
    """A deterministic quality policy is malformed or not the current V1."""


@dataclass(frozen=True)
class DeterministicQualityPolicyV1:
    """Immutable canonical document and its domain-separated identity."""

    document_json: bytes
    policy_id: str

    def decoded_document(self) -> dict:
        """Return a disposable decoded copy of the authoritative bytes."""
        return json.loads(self.document_json)


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
        raise DeterministicQualityPolicyError(
            "quality policy is not canonical JSON"
        ) from exc
    return encoded.encode("ascii")


def _policy_id(raw: bytes) -> str:
    return hashlib.sha256(_DOMAIN + raw).hexdigest()


def _valid_document(value: object) -> bool:
    if type(value) is not dict:
        return False
    root_keys = {
        "compositor",
        "publication",
        "qualityGates",
        "realization",
        "renderedCritics",
        "schemaVersion",
    }
    if set(value) != root_keys or type(value.get("schemaVersion")) is not int:
        return False
    return (
        value["schemaVersion"] == 1
        and _valid_realization(value["realization"])
        and _valid_compositor(value["compositor"])
        and _valid_quality_gates(value["qualityGates"])
        and _valid_critics(value["renderedCritics"])
        and _valid_publication(value["publication"])
    )


def _exact_dict(value: object, expected: dict) -> bool:
    if type(value) is not dict or set(value) != set(expected):
        return False
    return all(
        type(value[key]) is type(item) and value[key] == item
        for key, item in expected.items()
    )


def _valid_realization(value: object) -> bool:
    return _exact_dict(
        value,
        {
            "fallbackPolicy": "none",
            "kind": "deterministic-mp4",
        },
    )


def _valid_compositor(value: object) -> bool:
    return _exact_dict(
        value,
        {
            "audioDisposition": "copy",
            "eofAction": "pass",
            "proxyDisposition": "omitted-by-policy",
        },
    )


def _valid_quality_gates(value: object) -> bool:
    return _exact_dict(
        value,
        {
            "auditProfile": "B",
            "effectOracle": "SECTION_MARKER_ACCENT_V1",
            "fullDecode": True,
        },
    )


def _valid_publication(value: object) -> bool:
    return _exact_dict(
        value,
        {
            "allowed": False,
            "candidateDisposition": "private-counterfactual",
        },
    )


def _valid_critics(value: object) -> bool:
    expected = ["composition", "editorial"]
    return (
        type(value) is list
        and len(value) == len(expected)
        and all(type(item) is str for item in value)
        and value == expected
    )


def parse_deterministic_quality_policy(
    value: object,
) -> DeterministicQualityPolicyV1:
    """Parse the sole exact deterministic MP4 quality policy document."""
    if not _valid_document(value):
        raise DeterministicQualityPolicyError(
            "deterministic quality policy document is invalid"
        )
    raw = _canonical(value)
    return DeterministicQualityPolicyV1(raw, _policy_id(raw))


def decode_deterministic_quality_policy(
    raw: object,
) -> DeterministicQualityPolicyV1:
    """Decode exact canonical bytes without accepting alternate encodings."""
    if type(raw) is not bytes:
        raise DeterministicQualityPolicyError(
            "quality policy document must be immutable bytes"
        )
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeterministicQualityPolicyError(
            "quality policy document bytes are invalid"
        ) from exc
    parsed = parse_deterministic_quality_policy(value)
    if parsed.document_json != raw:
        raise DeterministicQualityPolicyError(
            "quality policy document is not exact canonical JSON"
        )
    return parsed


def validate_deterministic_quality_policy(value: object) -> None:
    """Reject forged instances and any non-current policy identity."""
    if type(value) is not DeterministicQualityPolicyV1:
        raise DeterministicQualityPolicyError(
            "deterministic quality policy instance is invalid"
        )
    parsed = decode_deterministic_quality_policy(value.document_json)
    valid = (
        isinstance(value.policy_id, str)
        and bool(_DIGEST.fullmatch(value.policy_id))
        and same_wire_value(value, parsed)
        and same_wire_value(value, current_deterministic_quality_policy())
    )
    if not valid:
        raise DeterministicQualityPolicyError(
            "deterministic quality policy identity is invalid"
        )


def _current_document() -> dict:
    return {
        "schemaVersion": 1,
        "realization": {"kind": "deterministic-mp4", "fallbackPolicy": "none"},
        "compositor": {
            "eofAction": "pass",
            "audioDisposition": "copy",
            "proxyDisposition": "omitted-by-policy",
        },
        "qualityGates": {
            "auditProfile": "B",
            "fullDecode": True,
            "effectOracle": "SECTION_MARKER_ACCENT_V1",
        },
        "renderedCritics": ["composition", "editorial"],
        "publication": {
            "allowed": False,
            "candidateDisposition": "private-counterfactual",
        },
    }


@lru_cache(maxsize=1)
def current_deterministic_quality_policy() -> DeterministicQualityPolicyV1:
    """Return the process-stable full quality policy, separate from repair."""
    return parse_deterministic_quality_policy(_current_document())
