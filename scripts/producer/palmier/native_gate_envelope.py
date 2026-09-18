"""Strict request/lane envelope shared by native gate entry points."""
from __future__ import annotations

import json

from palmier.mcp_client import PalmierError


def load_gate_envelope(path: str) -> tuple[str, list[str]]:
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PalmierError(f"cannot read native gate envelope: {exc}") from exc
    expected = {"schemaVersion", "request", "expectedLanes"}
    if not isinstance(value, dict) or set(value) != expected \
            or value.get("schemaVersion") != 1:
        raise PalmierError("native gate envelope must be schemaVersion 1")
    request, lanes = value.get("request"), value.get("expectedLanes")
    if not isinstance(request, str) or not isinstance(lanes, list) \
            or any(not isinstance(item, str) for item in lanes):
        raise PalmierError("native gate envelope request or lanes are invalid")
    return request, lanes
