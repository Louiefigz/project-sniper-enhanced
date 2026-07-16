"""Strict disk inputs for Palmier-native controller commands."""
from __future__ import annotations

import json

from palmier.mcp_client import PalmierError


def load_plan(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PalmierError(f"cannot read Palmier native plan: {exc}") from exc
    if not isinstance(value, dict):
        raise PalmierError("Palmier native plan is not an object")
    return value
