"""Private color-screening input vocabulary, not a canonical grade schema."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

POLICY = "sniper-private-source-color-v1"
MAX_SAMPLES = 64
MAX_GROUPS = 12
SHA = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class DiagnosticRequest:
    """Exact parents and explicitly declared context for a read-only attempt."""

    producer_dir: Path
    plan_hash: str
    manifest_hash: str
    contexts: list[dict]
    sample_budget: int = 32
    timeout_seconds: int = 120


def finite(value: object) -> bool:
    """Reject booleans, non-numbers and non-finite timing/measurement values."""
    return type(value) in (int, float) and math.isfinite(value)


def _group(value: object, duration: float) -> None:
    """Validate one declared source-time lighting interval without coercion."""
    keys = {"id", "start", "end", "intent", "description"}
    if type(value) is not dict or set(value) != keys:
        raise ValueError("color lighting group has unknown or missing fields")
    if not isinstance(value["id"], str) or not re.fullmatch(r"[a-z0-9-]{1,64}", value["id"]) \
            or value["id"] == "unclassified":
        raise ValueError("color lighting group id is invalid")
    if not finite(value["start"]) or not finite(value["end"]) \
            or not 0 <= value["start"] < value["end"] <= duration:
        raise ValueError("color lighting group is outside its source")
    if value["intent"] not in {"neutral", "dark", "colored", "unknown"}:
        raise ValueError("color lighting intent is unsupported")
    if type(value["description"]) is not str or len(value["description"]) > 500:
        raise ValueError("color lighting description is invalid")


def context(value: object, source: dict) -> dict:
    """Keep all declared history, rejecting overlap or silently dropped fields."""
    keys = {"sourceId", "sourceProfile", "cameraProfile", "historyState",
            "transformHistory", "lightingGroups"}
    if type(value) is not dict or set(value) != keys or value["sourceId"] != source["id"]:
        raise ValueError("color source context is malformed")
    if value["sourceProfile"] not in {"bt709-sdr", "unknown", "log", "hdr"} \
            or value["historyState"] not in {"known", "unknown"}:
        raise ValueError("color source profile/history state is unsupported")
    if value["cameraProfile"] is not None and (type(value["cameraProfile"]) is not str
                                              or len(value["cameraProfile"]) > 200):
        raise ValueError("color camera profile is invalid")
    history = value["transformHistory"]
    if type(history) is not list or len(history) > 20 or any(
            type(row) is not str or not 1 <= len(row) <= 500 for row in history):
        raise ValueError("color transform history must be explicit bounded notes")
    groups = value["lightingGroups"]
    if type(groups) is not list or len(groups) > MAX_GROUPS:
        raise ValueError("color lighting groups exceed their bound")
    for row in groups:
        _group(row, float(source["duration"]))
    ordered = sorted(groups, key=lambda row: row["start"])
    if len({row["id"] for row in groups}) != len(groups) or any(
            left["end"] > right["start"] for left, right in zip(ordered, ordered[1:])):
        raise ValueError("color lighting groups repeat ids or overlap")
    return {**value, "lightingGroups": ordered}


def unknown_context(source: dict) -> dict:
    """Missing context remains explicit; it never means neutral or no transform."""
    return {"sourceId": source["id"], "sourceProfile": "unknown", "cameraProfile": None,
            "historyState": "unknown", "transformHistory": [], "lightingGroups": []}


def validate_request(request: DiagnosticRequest) -> None:
    """Validate private bounds before touching input media or creating a job."""
    if not SHA.fullmatch(request.plan_hash) or not SHA.fullmatch(request.manifest_hash):
        raise ValueError("color diagnostic requires exact lowercase parent SHA-256s")
    if type(request.contexts) is not list or len(request.contexts) > 8:
        raise ValueError("color diagnostic supports at most eight sources")
    if type(request.sample_budget) is not int or not 5 <= request.sample_budget <= MAX_SAMPLES:
        raise ValueError("color sample budget must be 5..64")
    if type(request.timeout_seconds) is not int or not 30 <= request.timeout_seconds <= 120:
        raise ValueError("color diagnostic timeout must be 30..120 seconds")
