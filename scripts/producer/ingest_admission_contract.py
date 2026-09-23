"""Strict retained-receipt validation for Producer media source sets."""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

from headless.admission_receipt import AdmissionReceiptError, validate_admission_receipt
from headless.external_media_probe import POLICY_VERSION  # noqa: F401  historical name, re-exported
from headless.external_media_snapshot import (
    ExternalMediaSnapshot,
    observe_external_media_snapshot,
    verify_external_media_snapshot,
)
from ingest_admission_io import canonical_bytes, _read_regular
from ingest_media_observation import SourceVerificationCapture

SOURCE_SETS_NAME = ".sniper-source-sets"
STORE_NAME = ".sniper-external-media"
RECEIPTS_NAME = "receipts"
SOURCE_SET_POLICY = "sniper-producer-source-set-v1"
_SHA256 = set("0123456789abcdef")
MAX_ADMISSION_RECEIPT_BYTES = 4 * 1024 * 1024
MAX_SOURCE_SET_BYTES = 64 * 1024 * 1024


def _sha(value: object, label: str) -> str:
    if (type(value) is not str or len(value) != 64
            or any(char not in _SHA256 for char in value)):
        raise RuntimeError(f"{label} is not a lowercase SHA-256")
    return value


def _real_directory(path: Path, label: str) -> None:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise RuntimeError(f"{label} directory is unavailable") from exc
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise RuntimeError(f"{label} must be a real directory")


def receipt_snapshot(receipt: object, store: Path,
                     capture: SourceVerificationCapture | None = None) -> tuple[str, str, int, str]:
    """Validate a retained probe receipt and rehash its immutable snapshot.

    Native (v4) and historical container (v3) receipts are both accepted through
    ``headless.admission_receipt.validate_admission_receipt``; a native receipt
    must also carry the approved jail's attestations.
    """
    try:
        _limits, decoded = validate_admission_receipt(receipt)
    except AdmissionReceiptError as exc:
        raise RuntimeError(str(exc)) from exc
    snapshot = receipt.get("snapshot")
    if type(snapshot) is not dict:
        raise RuntimeError("external-media admission receipt lacks snapshot facts")
    path = snapshot.get("path")
    sha256 = _sha(snapshot.get("sha256"), "snapshot sha256")
    size, facts = snapshot.get("sizeBytes"), decoded.get("facts")
    if type(path) is not str or type(size) is not int or type(facts) is not dict:
        raise RuntimeError("external-media admission receipt lacks snapshot facts")
    if facts.get("sizeBytes") != size:
        raise RuntimeError("external-media admission size facts disagree")
    expected_path = store / f"{sha256}.media"
    if Path(path) != expected_path or not expected_path.is_file() \
            or expected_path.is_symlink():
        raise RuntimeError("external-media admission snapshot escaped its store")
    kind = facts.get("mediaKind")
    held = ExternalMediaSnapshot(path, sha256, size, 0, 0)
    if capture is None:
        verify_external_media_snapshot(held)
    else:
        capture.add(observe_external_media_snapshot(held, capture.runtime))
    return path, sha256, size, kind


def source_set_document(entries: list[dict]) -> dict:
    """Canonical ordered source-set document and its domain-separated digest."""
    ordered = sorted(entries, key=lambda row: (row["lane"], row["originalPath"]))
    digest = hashlib.sha256(
        b"sniper-producer-source-set-v1\0" + canonical_bytes(ordered)).hexdigest()
    return {
        "schemaVersion": 1,
        "policy": SOURCE_SET_POLICY,
        "entries": ordered,
        "sourceSetDigest": digest,
    }


def _verify_entry(entry: object, manifest_dir: Path, capture: SourceVerificationCapture | None = None) -> None:
    keys = {
        "lane", "originalPath", "snapshotPath", "sha256", "sizeBytes",
        "mediaKind", "admissionReceiptPath", "admissionReceiptSha256",
    }
    if type(entry) is not dict or set(entry) != keys:
        raise RuntimeError("source-set entry is malformed")
    if (entry["lane"] not in {"source", "broll", "music"}
            or type(entry["originalPath"]) is not str
            or not os.path.isabs(entry["originalPath"])):
        raise RuntimeError("source-set ingress identity is malformed")
    sha256 = _sha(entry["sha256"], "source-set snapshot sha256")
    size, snapshot = entry["sizeBytes"], entry["snapshotPath"]
    if type(size) is not int or type(snapshot) is not str:
        raise RuntimeError("source-set snapshot facts are malformed")
    expected_snapshot = manifest_dir / STORE_NAME / f"{sha256}.media"
    if Path(snapshot) != expected_snapshot:
        raise RuntimeError("source-set snapshot path is not canonical")
    receipt_sha = _sha(
        entry["admissionReceiptSha256"], "admission receipt sha256")
    expected_receipt = (
        Path(STORE_NAME) / RECEIPTS_NAME / f"{receipt_sha}.json")
    if Path(str(entry["admissionReceiptPath"])) != expected_receipt:
        raise RuntimeError("source-set admission receipt path is not canonical")
    receipt_path = manifest_dir / expected_receipt
    payload = _read_regular(
        receipt_path, MAX_ADMISSION_RECEIPT_BYTES, "admission receipt")
    if hashlib.sha256(payload).hexdigest() != receipt_sha:
        raise RuntimeError("source-set admission receipt hash mismatch")
    try:
        receipt = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError("external-media admission receipt is malformed") from exc
    try:
        if payload != canonical_bytes(receipt):
            raise RuntimeError(
                "external-media admission receipt is not canonical JSON")
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "external-media admission receipt is malformed") from exc
    observed = receipt_snapshot(receipt, manifest_dir / STORE_NAME, capture)
    if observed != (snapshot, sha256, size, entry["mediaKind"]):
        raise RuntimeError("source-set entry does not bind its admission receipt")


def _source_set_binding(manifest: dict) -> tuple[dict, Path]:
    binding = manifest.get("sourceSetAdmission")
    keys = {
        "schemaVersion", "receiptPath", "receiptSha256",
        "sourceSetDigest", "entryCount",
    }
    if type(binding) is not dict or set(binding) != keys:
        raise RuntimeError("manifest source-set admission binding is malformed")
    if type(binding["schemaVersion"]) is not int \
            or binding["schemaVersion"] != 1:
        raise RuntimeError("manifest source-set admission binding is unsupported")
    receipt_sha = _sha(binding["receiptSha256"], "source-set receipt sha256")
    expected_path = Path(SOURCE_SETS_NAME) / f"{receipt_sha}.json"
    if Path(str(binding["receiptPath"])) != expected_path:
        raise RuntimeError("source-set receipt path is not canonical")
    return binding, expected_path


def _verify_source_set_directories(manifest_dir: Path) -> None:
    _real_directory(manifest_dir, "manifest")
    _real_directory(manifest_dir / STORE_NAME, "external-media snapshot store")
    _real_directory(
        manifest_dir / STORE_NAME / RECEIPTS_NAME,
        "external-media receipt store",
    )
    _real_directory(manifest_dir / SOURCE_SETS_NAME, "source-set receipt store")


def _read_source_set(
    binding: dict,
    manifest_dir: Path,
    expected_path: Path,
) -> dict:
    payload = _read_regular(
        manifest_dir / expected_path, MAX_SOURCE_SET_BYTES,
        "source-set receipt")
    if hashlib.sha256(payload).hexdigest() != binding["receiptSha256"]:
        raise RuntimeError("source-set receipt hash mismatch")
    try:
        source_set = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError("source-set receipt is malformed") from exc
    try:
        if payload != canonical_bytes(source_set):
            raise RuntimeError("source-set receipt is not canonical JSON")
    except (TypeError, ValueError) as exc:
        raise RuntimeError("source-set receipt is malformed") from exc
    if (type(source_set) is not dict or set(source_set) != {
            "schemaVersion", "policy", "entries", "sourceSetDigest"}):
        raise RuntimeError("source-set receipt is malformed")
    if (type(source_set["schemaVersion"]) is not int
            or source_set["schemaVersion"] != 1
            or source_set["policy"] != SOURCE_SET_POLICY):
        raise RuntimeError("source-set receipt has wrong authority")
    return source_set


def _verify_source_set_entries(
    binding: dict,
    source_set: dict,
    manifest_dir: Path,
    capture: SourceVerificationCapture | None = None,
) -> list[dict]:
    entries = source_set["entries"]
    if type(entries) is not list:
        raise RuntimeError("source-set entries are malformed")
    expected = source_set_document(entries)
    if source_set != expected or binding["sourceSetDigest"] != expected["sourceSetDigest"]:
        raise RuntimeError("source-set digest mismatch")
    if type(binding["entryCount"]) is not int \
            or binding["entryCount"] != len(entries):
        raise RuntimeError("source-set entry count mismatch")
    for entry in entries:
        _verify_entry(entry, manifest_dir, capture)
    return entries


def verify_source_set_binding(
    manifest: dict,
    manifest_dir: Path,
    capture: SourceVerificationCapture | None = None,
) -> list[dict]:
    """Rehash the retained source set, per-file receipts, and snapshot bytes."""
    manifest_dir = Path(os.path.abspath(manifest_dir))
    binding, expected_path = _source_set_binding(manifest)
    _verify_source_set_directories(manifest_dir)
    source_set = _read_source_set(binding, manifest_dir, expected_path)
    return _verify_source_set_entries(binding, source_set, manifest_dir, capture)


def verify_manifest_source_set_if_present(
    manifest: dict,
    manifest_path: str,
    capture: SourceVerificationCapture | None = None,
) -> list[dict] | None:
    """Reverify admission; canonical product spawns reject legacy manifests."""
    if "sourceSetAdmission" not in manifest:
        if os.environ.get("SNIPER_REQUIRE_SOURCE_SET_ADMISSION") == "1":
            raise RuntimeError(
                "asset manifest lacks mandatory source-set admission authority")
        return None
    return verify_source_set_binding(
        manifest, Path(manifest_path).absolute().parent, capture)
