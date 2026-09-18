"""Exact media-inventory recovery for interrupted Palmier import receipts."""
from __future__ import annotations

import os
import time
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
    deadline = getattr(client, "deadline", None)
    stop = time.monotonic() + min(
        120.0, deadline.remaining()) if deadline is not None else None
    while True:
        matches = []
        for asset in _assets(client.call_json("get_media", {})):
            if asset.get("name") not in names:
                continue
            duration = asset.get("durationSeconds")
            duration_ok = probe.duration is None or duration is not None \
                and abs(float(duration) - probe.duration) <= 0.1
            size_ok = probe.width is None or (
                asset.get("width"), asset.get("height")) \
                == (probe.width, probe.height)
            if duration_ok and size_ok and isinstance(asset.get("id"), str):
                matches.append(asset["id"])
        if explicit is not None and explicit in matches:
            return explicit
        if explicit is None and len(matches) > 1:
            raise PalmierError(
                "Palmier import receipt recovery is ambiguous")
        if explicit is None and len(matches) == 1:
            return matches[0]
        if stop is None or time.monotonic() >= stop:
            detail = "explicit asset did not match" if explicit else \
                "no unique exact media asset"
            raise PalmierError(
                f"Palmier import receipt recovery failed: {detail}")
        time.sleep(min(0.25, deadline.remaining()))
