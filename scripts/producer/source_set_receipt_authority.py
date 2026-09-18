"""Reopen one retained source-set receipt without trusting a manifest."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from ingest_admission_contract import (
    MAX_SOURCE_SET_BYTES,
    RECEIPTS_NAME,
    SOURCE_SETS_NAME,
    SOURCE_SET_POLICY,
    STORE_NAME,
    _read_regular,
    _real_directory,
    _verify_entry,
    canonical_bytes,
    source_set_document,
)


def _canonical_receipt_path(receipt_path: Path) -> tuple[Path, str]:
    absolute = Path(os.path.abspath(receipt_path))
    if absolute.parent.name != SOURCE_SETS_NAME:
        raise RuntimeError("source-set artifact escaped its receipt store")
    digest = absolute.stem
    if absolute.suffix != ".json" or len(digest) != 64 \
            or any(char not in "0123456789abcdef" for char in digest):
        raise RuntimeError("source-set artifact path has no receipt hash")
    return absolute, digest


def _parse(payload: bytes) -> dict:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError("source-set artifact is malformed") from exc
    if payload != canonical_bytes(value):
        raise RuntimeError("source-set artifact is not canonical JSON")
    keys = {"schemaVersion", "policy", "entries", "sourceSetDigest"}
    if type(value) is not dict or set(value) != keys \
            or type(value.get("schemaVersion")) is not int \
            or value["schemaVersion"] != 1 \
            or value["policy"] != SOURCE_SET_POLICY \
            or type(value["entries"]) is not list:
        raise RuntimeError("source-set artifact has wrong authority")
    expected = source_set_document(value["entries"])
    if value != expected:
        raise RuntimeError("source-set artifact digest is stale")
    return value


def verify_source_set_receipt_artifact(receipt_path: Path) -> dict:
    """Rehash a graph-bound source set, its receipts, and every snapshot."""
    absolute, receipt_hash = _canonical_receipt_path(receipt_path)
    manifest_dir = absolute.parent.parent
    _real_directory(manifest_dir, "source authority")
    _real_directory(manifest_dir / STORE_NAME, "external-media snapshot store")
    _real_directory(
        manifest_dir / STORE_NAME / RECEIPTS_NAME,
        "external-media receipt store",
    )
    _real_directory(absolute.parent, "source-set receipt store")
    payload = _read_regular(
        absolute, MAX_SOURCE_SET_BYTES, "source-set artifact")
    if hashlib.sha256(payload).hexdigest() != receipt_hash:
        raise RuntimeError("source-set artifact hash changed")
    value = _parse(payload)
    for entry in value["entries"]:
        _verify_entry(entry, manifest_dir)
    return value
