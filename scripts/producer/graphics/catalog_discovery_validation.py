"""Recorded catalog metadata shapes; invalid claims are diagnostic, not evidence."""
from __future__ import annotations

import math
import re

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
ITEM_TYPES = ("block", "component")
STUDY_TEXT = ("mechanism", "fit", "quality", "aspectFlex", "port")
_LOCK_TEXT = ("source", "cliVersion", "mirroredAt", "boundary")
_LOCK_COUNTS = ("itemsListed", "itemsInstalled", "files")


def _dims_issue(value: object) -> str | None:
    """Validate optional strictly positive integer canvas dimensions."""
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"width", "height"}:
        return "dimensions must be {width, height}"
    if any(type(item) is not int or item <= 0 for item in value.values()):
        return "dimensions must be positive integers"
    return None


def index_record_issue(record: object) -> str | None:
    """Why one index row is unusable; retain valid original index semantics."""
    if not isinstance(record, dict):
        return "record is not an object"
    name = record.get("name")
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        return f"name is not a valid catalog name: {name!r}"
    if record.get("type") not in ITEM_TYPES:
        return f"{name}: type must be block|component"
    for key in ("title", "description"):
        if not isinstance(record.get(key), str):
            return f"{name}: {key} must be a string"
    tags = record.get("tags")
    if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
        return f"{name}: tags must be a list of strings"
    dims = _dims_issue(record.get("dimensions"))
    if dims:
        return f"{name}: {dims}"
    duration = record.get("duration")
    if duration is not None and (isinstance(duration, bool)
                                 or not isinstance(duration, (int, float))
                                 or (isinstance(duration, float) and not math.isfinite(duration))
                                 or duration <= 0):
        return f"{name}: duration must be a finite positive number"
    return None


def study_record_issue(row: object) -> str | None:
    """Permit original optional claims, including explanatory boolean strings."""
    name = row.get("name") if isinstance(row, dict) else None
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        return f"invalid name {name!r}"
    if row.get("type") is not None and row["type"] not in ITEM_TYPES:
        return "type must be block|component when present"
    if any(row.get(key) is not None and not isinstance(row[key], str) for key in STUDY_TEXT):
        return "study text fields must be strings or null"
    if any(row.get(key) is not None and type(row[key]) not in (bool, str)
           for key in ("scrubSafe", "selfContained")):
        return "study safety claims must be booleans, explanatory strings or null"
    variables = row.get("variables")
    if variables is not None and (not isinstance(variables, list)
                                 or any(not isinstance(item, str) for item in variables)):
        return "variables must be a list of strings or null"
    return None


def _known_missing(value: object, issues: list[str]) -> dict[str, str]:
    """Keep valid missing-source rows while reporting malformed container/rows."""
    if value is None:
        return {}
    if not isinstance(value, list):
        issues.append("lock knownMissing ignored: must be a list or null")
        return {}
    missing = {}
    for row in value:
        name = row.get("name") if isinstance(row, dict) else None
        if not isinstance(name, str) or not NAME_RE.fullmatch(name) \
                or not isinstance(row.get("reason", ""), str):
            issues.append(f"lock knownMissing row ignored: {row!r}")
            continue
        missing[name] = row.get("reason", "")
    return missing


def validated_lock(data: dict) -> tuple[dict, list[str]]:
    """Project only typed finite snapshot facts, never capability authority."""
    lock, issues = {}, []
    for key in (*_LOCK_TEXT, *_LOCK_COUNTS):
        value = data.get(key)
        valid = isinstance(value, str) if key in _LOCK_TEXT else type(value) is int and value >= 0
        if value is not None and not valid:
            issues.append(f"lock {key} ignored: expected " + ("text" if key in _LOCK_TEXT else "nonnegative integer"))
            value = None
        lock[key] = value
    lock["knownMissing"] = _known_missing(data.get("knownMissing"), issues)
    return lock, issues
