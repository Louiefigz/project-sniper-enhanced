"""Hash-bind path resources and translated overlay placements."""
from __future__ import annotations

from fingerprints import file_sha256
from palmier.mcp_client import PalmierError


def bind_media_hashes(steps: list[dict]) -> list[dict]:
    """Bind every path-bearing operation to the exact imported file bytes."""
    bound = []
    for row in steps:
        if not isinstance(row.get("path"), str):
            bound.append(row)
            continue
        digest = file_sha256(row["path"])
        value = {**row, "fileHash": digest}
        if row.get("op") == "native-broll":
            value.update({"assetPath": row["path"], "assetHash": digest})
        bound.append(value)
    resources = {str(row["key"]): row for row in bound
                 if row.get("op") == "import"
                 and isinstance(row.get("key"), str)}
    result = []
    for row in bound:
        if row.get("op") not in {
                "overlays", "caption-alpha-shard", "title-alpha-shard",
                "graphics-alpha-shard"}:
            result.append(row)
            continue
        if row.get("op") != "overlays":
            asset = resources.get(str(row.get("mediaKey")))
            if not asset or not asset.get("fileHash"):
                raise PalmierError(
                    f"alpha asset {row.get('elementId')!r} is not bound")
            result.append({
                **row, "assetPath": asset["path"],
                "assetHash": asset["fileHash"]})
            continue
        entries = []
        for entry in row.get("entries") or []:
            asset = resources.get(str(entry.get("mediaKey")))
            if not asset or not asset.get("fileHash"):
                raise PalmierError(
                    f"overlay {entry.get('elementId')!r} has no bound asset")
            entries.append({**entry, "assetPath": asset["path"],
                            "assetHash": asset["fileHash"]})
        result.append({**row, "entries": entries})
    return result
