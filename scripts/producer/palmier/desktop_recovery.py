"""Exact media-inventory recovery for interrupted Palmier import receipts."""
from __future__ import annotations

import os
from typing import Any

from ingest_probe import probe_media
from palmier.mcp_client import PalmierError


def _assets(value: object) -> list[dict]:
    rows = value.get("assets") if isinstance(value, dict) else value
    return [row for row in rows or [] if isinstance(row, dict)]


def recover_media_ref(client: Any, binding: dict,
                      explicit: str | None = None,
                      probe_fn: Any = probe_media) -> str:
    """Resolve one missed import from exact name, duration, and canvas facts."""
    path = binding["path"]
    probe = probe_fn(path)
    names = {os.path.basename(path), os.path.splitext(os.path.basename(path))[0]}
    names.update(value for value in (binding.get("importName"),
                 binding.get("elementId")) if isinstance(value, str))
    matches = []
    for asset in _assets(client.call_json("get_media", {})):
        if asset.get("name") not in names:
            continue
        duration = asset.get("durationSeconds")
        duration_ok = probe.duration is None or duration is not None \
            and abs(float(duration) - probe.duration) <= 0.1
        size_ok = probe.width is None or (asset.get("width"), asset.get("height")) \
            == (probe.width, probe.height)
        if duration_ok and size_ok and isinstance(asset.get("id"), str):
            matches.append(asset["id"])
    if explicit is not None:
        if explicit not in matches:
            raise PalmierError(
                "explicit Palmier mediaRef does not match the reserved import")
        return explicit
    if len(matches) != 1:
        raise PalmierError(
            "Palmier import receipt recovery did not find one exact media asset")
    return matches[0]
