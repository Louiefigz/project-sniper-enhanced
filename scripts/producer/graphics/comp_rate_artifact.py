#!/usr/bin/env python3
"""Fail-closed integrity/freshness checks for the retained rate matrix."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from fractions import Fraction
from typing import Optional

from fingerprints import file_sha256
from graphics.comp_capability_artifact import (
    MOTION_DIR,
    capability_digest,
    capability_row_issue,
    current_source_digest,
    load_artifact,
)
from graphics.render_tools import resolve_tools

RELEASED_RATES = (
    "24000/1001", "24", "25", "30000/1001",
    "30", "50", "60000/1001", "60",
)
PROBE_FRAMES = 4
RETAINED_RECEIPT_HASH = (
    "cf4f509636a96f20a244fefc7dc76d657a8c45aa61cbadc347e67ca76b83ddc7"
)
_HASH_KEYS = {
    "schemaVersion", "kind", "passed", "sourceDigest", "capabilityDigest",
    "rates", "compositionCount", "probeFrames", "tools", "probes",
}
_PROBE_KEYS = {
    "kind", "rate", "duration", "stream", "mediaSha256", "decoded",
}
_STREAM_KEYS = {
    "codec_name", "pix_fmt", "width", "height", "r_frame_rate",
    "avg_frame_rate", "nb_read_frames",
}
_SHA256 = frozenset("0123456789abcdef")
_CAPABILITY_PATH = os.path.join(MOTION_DIR, "comp_capabilities.json")


def _is_hash(value: object, length: int = 64) -> bool:
    return (isinstance(value, str) and len(value) == length
            and set(value) <= _SHA256)


def _receipt_hash(value: dict) -> str:
    payload = {key: item for key, item in value.items()
               if key != "receiptHash"}
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def current_tool_receipts() -> dict:
    """Exact executable identities against which evidence stays qualified."""
    return {
        name: {"path": path, "sha256": file_sha256(path)}
        for name, path in sorted(resolve_tools().items())
    }


def _current_capabilities() -> dict:
    comps, issue = load_artifact(_CAPABILITY_PATH)
    if issue:
        raise RuntimeError(issue)
    invalid = {
        kind: capability_row_issue(row)
        for kind, row in (comps or {}).items()
        if capability_row_issue(row)
    }
    if invalid:
        raise RuntimeError(f"capability rows are unreleased: {invalid}")
    return comps or {}


def _header_issue(value: dict, capabilities: dict) -> str:
    if set(value) != _HASH_KEYS | {"receiptHash"}:
        return "rate matrix has unsupported or missing top-level fields"
    expected = {
        "schemaVersion": 1,
        "kind": "hyperframes-released-rate-matrix",
        "passed": True,
        "sourceDigest": current_source_digest(),
        "capabilityDigest": capability_digest(capabilities),
        "rates": list(RELEASED_RATES),
        "compositionCount": len(capabilities),
        "probeFrames": PROBE_FRAMES,
    }
    for key, item in expected.items():
        if value.get(key) != item:
            return f"rate matrix {key} is stale or malformed"
    if not _is_hash(value.get("receiptHash")):
        return "rate matrix receiptHash is malformed"
    if value["receiptHash"] != _receipt_hash(value):
        return "rate matrix receiptHash does not match its rows"
    return ""


def _tools_issue(value: object, expected: dict) -> str:
    if not isinstance(value, dict) or set(value) != set(expected):
        return "rate matrix tool inventory is malformed"
    for name, current in expected.items():
        row = value.get(name)
        if (not isinstance(row, dict)
                or set(row) != {"path", "sha256"}
                or row != current):
            return f"rate matrix tool receipt is stale or malformed: {name}"
    return ""


def _duration_for(rate: str) -> dict[str, str]:
    value = Fraction(rate)
    duration = Fraction(
        (PROBE_FRAMES * 2 - 1) * value.denominator,
        2 * value.numerator,
    )
    return {
        "numerator": str(duration.numerator),
        "denominator": str(duration.denominator),
    }


def _stream_issue(stream: object, rate: str, canvas: list[int]) -> str:
    if not isinstance(stream, dict) or set(stream) != _STREAM_KEYS:
        return "stream facts are malformed"
    expected_rate = Fraction(rate)
    try:
        measured = (
            Fraction(str(stream["r_frame_rate"])),
            Fraction(str(stream["avg_frame_rate"])),
        )
        frames = int(stream["nb_read_frames"])
    except (TypeError, ValueError, ZeroDivisionError):
        return "stream rate/frame facts are malformed"
    if measured != (expected_rate, expected_rate):
        return "stream rate does not match the requested exact rational"
    expected = {
        "codec_name": "prores",
        "pix_fmt": "yuva444p12le",
        "width": canvas[0],
        "height": canvas[1],
    }
    if any(stream.get(key) != item for key, item in expected.items()):
        return "stream codec, alpha format, or canvas is not released"
    if frames != PROBE_FRAMES or stream["nb_read_frames"] != str(PROBE_FRAMES):
        return "stream did not fully decode the exact probe frame count"
    return ""


def _probe_issue(row: object, capabilities: dict) -> str:
    if not isinstance(row, dict) or set(row) != _PROBE_KEYS:
        return "probe row has unsupported or missing fields"
    kind, rate = row.get("kind"), row.get("rate")
    if kind not in capabilities or rate not in RELEASED_RATES:
        return "probe row references an unknown composition or rate"
    if row.get("duration") != _duration_for(rate):
        return "probe duration does not bind the exact sample frame interval"
    if row.get("decoded") is not True or not _is_hash(row.get("mediaSha256")):
        return "probe decode/media receipt is malformed"
    return _stream_issue(row.get("stream"), rate, capabilities[kind]["canvas"])


def validate_rate_matrix(
    value: object,
    tool_receipts: Optional[dict] = None,
    expected_receipt_hash: Optional[str] = RETAINED_RECEIPT_HASH,
) -> str:
    """Return an empty string only for fresh, complete, untampered evidence."""
    if not isinstance(value, dict):
        return "rate matrix is not an object"
    try:
        capabilities = _current_capabilities()
        issue = _header_issue(value, capabilities)
    except (OSError, RuntimeError, UnicodeDecodeError):
        return "current motion source closure cannot be verified"
    if issue:
        return issue
    if (expected_receipt_hash is not None
            and value["receiptHash"] != expected_receipt_hash):
        return "rate matrix does not match the reviewed retained receipt"
    try:
        expected_tools = tool_receipts or current_tool_receipts()
    except (OSError, RuntimeError):
        return "current render tools cannot be verified"
    issue = _tools_issue(value.get("tools"), expected_tools)
    if issue:
        return issue
    probes = value.get("probes")
    expected_pairs = {
        (kind, rate) for kind in capabilities for rate in RELEASED_RATES
    }
    if not isinstance(probes, list) or len(probes) != len(expected_pairs):
        return "rate matrix probe cross-product is incomplete"
    pairs = []
    for row in probes:
        issue = _probe_issue(row, capabilities)
        if issue:
            return issue
        pairs.append((row["kind"], row["rate"]))
    if len(set(pairs)) != len(pairs) or set(pairs) != expected_pairs:
        return "rate matrix probe identities repeat or are incomplete"
    if probes != sorted(probes, key=lambda row: (row["kind"], row["rate"])):
        return "rate matrix probe rows are not in canonical order"
    return ""


def load_rate_matrix(
    path: str,
    tool_receipts: Optional[dict] = None,
) -> tuple[Optional[dict], str]:
    """Read and validate a retained matrix without trusting its pass flag."""
    try:
        info = os.lstat(path)
        if not os.path.isfile(path) or os.path.islink(path) or info.st_nlink < 1:
            return None, "rate matrix path is not a regular file"
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"rate matrix is unreadable: {exc}"
    issue = validate_rate_matrix(value, tool_receipts)
    return (None, issue) if issue else (value, "")


def main() -> int:
    """Validate one retained matrix against current source and tools."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact")
    args = parser.parse_args()
    value, issue = load_rate_matrix(args.artifact)
    if issue:
        raise SystemExit(issue)
    print(json.dumps({
        "passed": True,
        "probes": len(value["probes"]),
        "receiptHash": value["receiptHash"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
