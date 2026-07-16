#!/usr/bin/env python3
"""Content-keyed Palmier media reuse, including adopted-library dedup."""
from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field

from ingest_probe import MediaProbe, probe_media
from palmier.mcp_client import PalmierClient, PalmierError, emit

ProjectGuard = Callable[[str], None]


@dataclass(frozen=True)
class MediaBindings:
    """Resolved translator media keys plus the next persistent media map."""

    refs: dict[str, str]
    seconds: dict[str, float]
    media_map: dict[str, dict]
    component_status: dict[str, dict] = field(default_factory=dict)


def content_key(media_key: str, path: str, source_hash: str) -> str:
    """Stable media identity across shadow-timeline builds."""
    if media_key == "master":
        return f"master:{source_hash}"
    if media_key == "src":
        return f"src:{source_hash}"
    if media_key.startswith("gfx:"):
        return f"gfx:{os.path.basename(path)}"
    return f"{media_key}:{path}"


def _assets(payload: dict | list) -> list[dict]:
    return payload.get("assets", []) if isinstance(payload, dict) else payload


def _matches(asset: dict, names: set[str], probe: MediaProbe) -> bool:
    if asset.get("name") not in names:
        return False
    duration = asset.get("durationSeconds")
    if probe.duration is not None:
        if duration is None or abs(float(duration) - probe.duration) > 0.1:
            return False
    if probe.width is None:
        return asset.get("width") is None and asset.get("height") is None
    return (asset.get("width"), asset.get("height")) == (
        probe.width, probe.height)


class MediaLibrary:
    """Resolve imports from sidecar, project library, or a new import."""

    def __init__(self, client: PalmierClient, source_hash: str,
                 project_guard: ProjectGuard):
        self.client = client
        self.source_hash = source_hash
        self.project_guard = project_guard

    def ensure(self, imports: dict[str, str],
               media_map: dict[str, dict]) -> MediaBindings:
        """Resolve every translator media key without duplicate imports."""
        self.project_guard("media_inventory")
        inventory = _assets(self.client.call_json("get_media", {}))
        next_map = dict(media_map)
        refs: dict[str, str] = {}
        seconds: dict[str, float] = {}
        for key, path in imports.items():
            ck = content_key(key, path, self.source_hash)
            asset = self._resolve(key, path, media_map.get(ck), inventory)
            refs[key] = asset["id"]
            seconds[key] = float(asset.get("durationSeconds") or 0)
            next_map[ck] = {"ref": refs[key], "seconds": seconds[key]}
        return MediaBindings(refs, seconds, next_map)

    def _resolve(self, key: str, path: str, prior: dict | None,
                 inventory: list[dict]) -> dict:
        prior_ref = prior and prior.get("ref")
        asset = next((row for row in inventory if row.get("id") == prior_ref), None)
        if asset:
            emit(status="media_reused", key=key, mediaRef=asset["id"])
            return asset
        try:
            probe = probe_media(path)
        except (OSError, RuntimeError, ValueError) as exc:
            raise PalmierError(f"cannot probe media for Palmier: {path}: {exc}") from exc
        names = {os.path.splitext(os.path.basename(path))[0]}
        if key in ("src", "master"):
            names.add(self._source_name(key))
        matches = sorted((a for a in inventory if _matches(a, names, probe)),
                         key=lambda a: str(a.get("id", "")))
        if matches:
            emit(status="media_adopted", key=key, mediaRef=matches[0]["id"])
            return matches[0]
        return self._import(key, path)

    def _import(self, key: str, path: str) -> dict:
        self.project_guard(f"import:{key}")
        result = self.client.call_json("import_media", {"source": {"path": path}})
        ref = result.get("mediaRef") or result.get("id")
        if not ref:
            raise PalmierError(f"import_media returned no mediaRef: {result}")
        asset = self.client.wait_media(ref)
        if key in ("src", "master") and asset.get("name") != self._source_name(key):
            self.project_guard("rename_source_media")
            self.client.call("organize_media", {"renames": [{
                "item": ref, "name": self._source_name(key)}]})
            asset = {**asset, "name": self._source_name(key)}
        emit(status="imported", key=key, mediaRef=ref)
        return asset

    def _source_name(self, key: str) -> str:
        prefix = "master" if key == "master" else "src"
        return f"sniper-{prefix}-{self.source_hash[:12]}"
