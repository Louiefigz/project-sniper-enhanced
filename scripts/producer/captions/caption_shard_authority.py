#!/usr/bin/env python3
"""Validate the alpha-shard closure required by final caption provenance."""
from __future__ import annotations

import json
import os

from captions.caption_shard_contract import validate_caption_shard_manifest


def validate_bound_shards(out_dir: str, authority: dict) -> str | None:
    """Return a fail-closed diagnostic, or None for a current shard closure."""
    expected = authority.get("alphaShardManifestHash")
    if not isinstance(expected, str):
        return "caption authority has no bound alpha-shard manifest"
    path = os.path.join(out_dir, "caption_shards.json")
    try:
        with open(path, encoding="utf-8") as handle:
            manifest = json.load(handle)
        manifest = validate_caption_shard_manifest(manifest, out_dir)
    except (OSError, json.JSONDecodeError, ValueError):
        return "caption alpha-shard manifest is missing or unreadable"
    if expected != manifest["authorityHash"]:
        return "caption alpha-shard manifest digest is stale"
    entries = manifest["entries"]
    files = authority.get("files") or {}
    for row in entries:
        cue_id = row.get("cueId")
        media = row.get("media")
        if not isinstance(cue_id, str) or not isinstance(media, dict) \
                or files.get(f"shard:{cue_id}") != media:
            return "caption alpha-shard media is not bound by authority"
    return None
