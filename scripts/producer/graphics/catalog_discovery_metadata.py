#!/usr/bin/env python3
"""Project optional enriched registry metadata into a stable discovery shape."""
from __future__ import annotations


def _strings(value: object) -> list[str]:
    """Keep a bounded list of nonempty strings in source order."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item][:64]


def _variables(value: object) -> list[dict]:
    """Retain searchable variable roles/controls without sample media bytes."""
    if not isinstance(value, list):
        return []
    rows = []
    for item in value[:128]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        rows.append({key: item.get(key) for key in
                     ("id", "type", "role", "label", "description", "min", "max", "unit")
                     if item.get(key) is not None})
    return rows


def _sync_points(value: object) -> list[dict]:
    """Retain named timing landmarks, excluding arbitrary extra payloads."""
    if not isinstance(value, list):
        return []
    rows = []
    for item in value[:64]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        rows.append({key: item.get(key) for key in ("id", "phase", "offset")
                     if item.get(key) is not None})
    return rows


def _preview(value: object) -> dict:
    """Retain preview references only; discovery never fetches or embeds them."""
    if not isinstance(value, dict):
        return {}
    return {key: item for key, item in value.items()
            if key in ("video", "poster") and isinstance(item, str)}


def structured_metadata(record: dict) -> dict:
    """Normalize current optional fields while keeping old indexes readable."""
    variables = _variables(record.get("variables"))
    by_role: dict[str, list[str]] = {}
    for variable in variables:
        role = variable.get("role")
        if isinstance(role, str) and role:
            by_role.setdefault(role, []).append(variable["id"])
    return {"jobs": _strings(record.get("jobs")),
            "family": record.get("family") if isinstance(record.get("family"), str) else None,
            "profile": record.get("profile") if isinstance(record.get("profile"), str) else None,
            "variables": variables, "variableRoles": by_role,
            "inputs": [item["id"] for item in variables],
            "syncPoints": _sync_points(record.get("syncPoints")),
            "preview": _preview(record.get("preview"))}


def searchable_metadata_text(metadata: dict) -> dict[str, str]:
    """Flatten the structured fields used by deterministic semantic retrieval."""
    variables = metadata.get("variables") or []
    controls = " ".join(" ".join(str(row.get(key, "")) for key in
                                   ("id", "type", "role", "label", "description"))
                        for row in variables)
    sync = " ".join(str(row.get("id", "")) for row in metadata.get("syncPoints") or [])
    return {"jobs": " ".join(metadata.get("jobs") or []),
            "family": str(metadata.get("family") or ""),
            "profile": str(metadata.get("profile") or ""),
            "inputs": controls, "sync": sync}
