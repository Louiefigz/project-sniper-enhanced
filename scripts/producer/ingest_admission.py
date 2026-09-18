"""Mandatory sandbox admission and source-set authority for Producer ingest."""
from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from headless.external_media_probe import admit_external_media
from ingest_admission_contract import (
    RECEIPTS_NAME,
    SOURCE_SETS_NAME,
    STORE_NAME,
    canonical_bytes,
    receipt_snapshot,
    source_set_document,
    verify_source_set_binding,
)
from ingest_probe import AUDIO_EXTS, MEDIA_EXTS, reject_unsupported_ingest_media


@dataclass(frozen=True)
class IngressCandidate:
    """One external file and the lane through which it entered Producer."""

    original_path: Path
    lane: str


@dataclass(frozen=True)
class AdmittedMedia:
    """Canonical snapshot and retained admission proof for one input file."""

    original_path: str
    lane: str
    snapshot_path: str
    sha256: str
    size_bytes: int
    media_kind: str
    receipt_path: str
    receipt_sha256: str


@dataclass(frozen=True)
class IngestAdmission:
    """Admitted files plus the manifest-facing source-set binding."""

    media_by_original: dict[str, AdmittedMedia]
    binding: dict


def _real_directory(path: Path, label: str) -> None:
    info = os.lstat(path)
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise RuntimeError(f"{label} must be a real directory")


def _read_expected(
    descriptor: int,
    size: int,
    label: str,
) -> tuple[bytearray, os.stat_result]:
    payload = bytearray()
    while len(payload) < size:
        chunk = os.read(descriptor, size - len(payload))
        if not chunk:
            raise RuntimeError(f"{label} was truncated")
        payload.extend(chunk)
    if os.read(descriptor, 1):
        raise RuntimeError(f"{label} grew while reading")
    return payload, os.fstat(descriptor)


def _existing_exact(path: Path, expected: bytes, label: str) -> None:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RuntimeError(f"{label} is unsafe") from exc
    try:
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_size != len(expected)):
            raise RuntimeError(f"{label} is unsafe")
        payload, after = _read_expected(
            descriptor, len(expected), label)
    finally:
        os.close(descriptor)
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    current = os.lstat(path)
    if (any(getattr(before, key) != getattr(after, key) for key in fields)
            or current.st_dev != after.st_dev
            or current.st_ino != after.st_ino):
        raise RuntimeError(f"{label} changed while reading")
    if payload != expected:
        raise RuntimeError(f"{label} collision")


def _write_exact(path: Path, payload: bytes) -> None:
    descriptor, staged = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            os.unlink(staged)
        except FileNotFoundError:
            pass


def _candidate(path: Path, lane: str) -> IngressCandidate:
    absolute = Path(os.path.abspath(path))
    info = os.lstat(absolute)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise RuntimeError(f"{lane} ingress must be a regular non-symlink file: {absolute}")
    reject_unsupported_ingest_media(absolute)
    return IngressCandidate(absolute, lane)


def _tree_candidates(
    root: Path,
    lane: str,
    extensions: set[str],
) -> list[IngressCandidate]:
    candidates = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"{lane} ingress tree cannot contain symlinks: {path}")
        relative = path.relative_to(root)
        if (path.is_file() and path.suffix.lower() in extensions
                and not any(part.startswith(".") for part in relative.parts)):
            candidates.append(_candidate(path, lane))
    return candidates


def collect_ingest_candidates(
    raw_files: list[Path],
    broll_dir: Path | None,
    music_dir: Path | None,
) -> list[IngressCandidate]:
    """Enumerate exactly the external files consumed by ``ingest.py``."""
    candidates = [_candidate(path, "source") for path in raw_files]
    if broll_dir:
        candidates += _tree_candidates(broll_dir, "broll", MEDIA_EXTS)
    if music_dir:
        candidates += _tree_candidates(music_dir, "music", AUDIO_EXTS)
    return candidates


def _store_receipt(receipt: dict, manifest_dir: Path) -> tuple[str, str]:
    payload = canonical_bytes(receipt)
    digest = hashlib.sha256(payload).hexdigest()
    relative = Path(STORE_NAME) / RECEIPTS_NAME / f"{digest}.json"
    destination = manifest_dir / relative
    if destination.exists():
        _existing_exact(
            destination, payload, "content-addressed admission receipt")
    else:
        _write_exact(destination, payload)
    return str(relative), digest


def _admit_one(
    candidate: IngressCandidate,
    manifest_dir: Path,
    runner: Callable[[str, str], dict],
) -> AdmittedMedia:
    reject_unsupported_ingest_media(candidate.original_path)
    store = manifest_dir / STORE_NAME
    receipt = runner(str(candidate.original_path), str(store))
    path, sha256, size, kind = receipt_snapshot(receipt, store)
    receipt_path, receipt_sha256 = _store_receipt(receipt, manifest_dir)
    return AdmittedMedia(
        str(candidate.original_path), candidate.lane, path, sha256, size,
        kind, receipt_path, receipt_sha256)


def _entry(media: AdmittedMedia) -> dict:
    return {
        "lane": media.lane,
        "originalPath": media.original_path,
        "snapshotPath": media.snapshot_path,
        "sha256": media.sha256,
        "sizeBytes": media.size_bytes,
        "mediaKind": media.media_kind,
        "admissionReceiptPath": media.receipt_path,
        "admissionReceiptSha256": media.receipt_sha256,
    }


def admit_ingest_candidates(
    candidates: list[IngressCandidate],
    manifest_dir: Path,
    runner: Callable[[str, str], dict] | None = None,
) -> IngestAdmission:
    """Admit all inputs or publish no source-set authority."""
    manifest_dir = Path(os.path.abspath(manifest_dir))
    manifest_dir.mkdir(parents=True, exist_ok=True)
    _real_directory(manifest_dir, "manifest")
    store = manifest_dir / STORE_NAME
    receipts = store / RECEIPTS_NAME
    store.mkdir(mode=0o700, exist_ok=True)
    _real_directory(store, "external-media snapshot store")
    receipts.mkdir(mode=0o700, exist_ok=True)
    _real_directory(receipts, "external-media receipt store")
    admit = runner or admit_external_media
    admitted = [_admit_one(candidate, manifest_dir, admit)
                for candidate in candidates]
    mapping = {media.original_path: media for media in admitted}
    if len(mapping) != len(admitted):
        raise RuntimeError("one external path entered Producer through multiple lanes")
    source_set = source_set_document([_entry(media) for media in admitted])
    payload = canonical_bytes(source_set)
    receipt_sha256 = hashlib.sha256(payload).hexdigest()
    relative = Path(SOURCE_SETS_NAME) / f"{receipt_sha256}.json"
    receipt_path = manifest_dir / relative
    receipt_path.parent.mkdir(mode=0o700, exist_ok=True)
    _real_directory(receipt_path.parent, "source-set receipt store")
    if receipt_path.exists():
        _existing_exact(
            receipt_path, payload, "content-addressed source-set receipt")
    else:
        _write_exact(receipt_path, payload)
    binding = {
        "schemaVersion": 1,
        "receiptPath": str(relative),
        "receiptSha256": receipt_sha256,
        "sourceSetDigest": source_set["sourceSetDigest"],
        "entryCount": len(admitted),
    }
    return IngestAdmission(mapping, binding)
