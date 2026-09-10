"""Hash closure for graphics imported by a Palmier working checkpoint."""
from __future__ import annotations

import hashlib
import json
import os

from fingerprints import file_sha256
from palmier.checkpoint_graphics_cache import validate_placement_receipt

_VERSION = 1
_KIND = "palmier-checkpoint-graphics-authority"


def _record(receipt: dict) -> dict:
    output = receipt["output"]
    media_path = os.path.abspath(output["path"])
    proof_path = os.path.abspath(output["proofPath"])
    receipt_path = media_path + ".placement.json"
    return {
        "mediaPath": media_path, "mediaSha256": file_sha256(media_path),
        "proofPath": proof_path, "proofSha256": file_sha256(proof_path),
        "receiptPath": receipt_path,
        "receiptSha256": file_sha256(receipt_path),
    }


def _digest(records: list[dict]) -> str:
    raw = json.dumps(records, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(
        b"palmier-checkpoint-graphics-authority-v1\0" + raw.encode()).hexdigest()


def bind_checkpoint_asset_authority(
    capability: dict,
    receipts: list[dict],
) -> dict:
    """Attach the exact media/proof/placement-receipt closure."""
    if not receipts:
        return capability
    records = [_record(receipt) for receipt in receipts]
    authority = {"schemaVersion": _VERSION, "kind": _KIND,
                 "records": records, "authorityHash": _digest(records)}
    return {**capability, "graphicsAssetAuthority": authority}


def _file_current(record: dict, cache: dict[str, str]) -> bool:
    fields = (
        ("mediaPath", "mediaSha256"),
        ("proofPath", "proofSha256"),
        ("receiptPath", "receiptSha256"),
    )
    for path_key, hash_key in fields:
        path, expected = record.get(path_key), record.get(hash_key)
        if not isinstance(path, str) or not isinstance(expected, str):
            return False
        absolute = os.path.abspath(path)
        try:
            cache.setdefault(absolute, file_sha256(absolute))
        except OSError:
            return False
        if cache[absolute] != expected:
            return False
    return True


def checkpoint_assets_current(capability: dict) -> bool:
    """Whether every placed checkpoint asset still closes over its inputs."""
    authority = capability.get("graphicsAssetAuthority")
    if authority is None:
        return True
    if not isinstance(authority, dict) \
            or authority.get("schemaVersion") != _VERSION \
            or authority.get("kind") != _KIND:
        return False
    records = authority.get("records")
    if not isinstance(records, list) or not records \
            or authority.get("authorityHash") != _digest(records):
        return False
    cache: dict[str, str] = {}
    for record in records:
        if not isinstance(record, dict) or not _file_current(record, cache):
            return False
        try:
            validate_placement_receipt(record["mediaPath"], cache)
        except (OSError, ValueError, RuntimeError):
            return False
    return True
