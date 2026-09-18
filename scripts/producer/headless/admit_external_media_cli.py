#!/usr/bin/env python3
"""Durably admit one external media file for a non-ingest product lane."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from headless.external_media_probe import admit_external_media  # noqa: E402
from headless.external_media_probe_policy import MediaProbeLimits  # noqa: E402
from ingest_admission_contract import canonical_bytes, receipt_snapshot  # noqa: E402

RECEIPT_DIR = ".sniper-reference-admission"
REFERENCE_LIMITS = MediaProbeLimits(
    max_bytes=2 * 1024 ** 3,
    max_width=8192,
    max_height=8192,
    max_frames=500_000,
    max_duration_seconds=3600,
    max_streams=32,
)
MAX_RECEIPT_BYTES = 4 * 1024 * 1024


def _cancel(_signum: int, _frame: object) -> None:
    raise KeyboardInterrupt("reference admission cancelled")


def _real_directory(path: Path, label: str) -> None:
    info = os.lstat(path)
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise RuntimeError(f"{label} must be a real directory")


def _read_receipt_payload(
    descriptor: int,
    size: int,
) -> tuple[bytes, os.stat_result]:
    chunks, remaining = [], size
    while remaining:
        chunk = os.read(descriptor, remaining)
        if not chunk:
            raise RuntimeError("reference admission receipt was truncated")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks), os.fstat(descriptor)


def _existing_receipt(path: Path, expected: bytes) -> None:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or not 0 < info.st_size <= MAX_RECEIPT_BYTES):
            raise RuntimeError("reference admission receipt is unsafe")
        payload, after = _read_receipt_payload(descriptor, info.st_size)
    finally:
        os.close(descriptor)
    current = os.lstat(path)
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if (any(getattr(info, key) != getattr(after, key) for key in fields)
            or current.st_dev != after.st_dev
            or current.st_ino != after.st_ino):
        raise RuntimeError("reference admission receipt changed while reading")
    if payload != expected:
        raise RuntimeError("reference admission receipt collision")


def _write_exact(path: Path, payload: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
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


def admit_reference(source: str, store: str) -> dict:
    """Full-decode one video and retain its immutable receipt beside the bytes."""
    root = Path(os.path.abspath(store))
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    _real_directory(root, "reference snapshot store")
    receipt_root = root / RECEIPT_DIR
    receipt_root.mkdir(mode=0o700, exist_ok=True)
    _real_directory(receipt_root, "reference receipt store")
    receipt = admit_external_media(source, str(root), REFERENCE_LIMITS)
    snapshot, sha256, size, kind = receipt_snapshot(receipt, root)
    facts = receipt["decoded"]["facts"]
    if kind != "timed-media" or facts["videoStreams"] < 1:
        raise RuntimeError("reference admission requires a timed video stream")
    payload = canonical_bytes(receipt)
    receipt_sha256 = hashlib.sha256(payload).hexdigest()
    receipt_path = receipt_root / f"{receipt_sha256}.json"
    if receipt_path.exists():
        _existing_receipt(receipt_path, payload)
    else:
        _write_exact(receipt_path, payload)
    return {
        "schemaVersion": 1,
        "policy": "sniper-reference-media-admission-v1",
        "snapshotPath": snapshot,
        "snapshotSha256": sha256,
        "sizeBytes": size,
        "mediaKind": kind,
        "durationSeconds": facts["durationSeconds"],
        "receiptPath": str(receipt_path),
        "receiptSha256": receipt_sha256,
    }


def main(argv: list[str] | None = None) -> int:
    signal.signal(signal.SIGTERM, _cancel)
    signal.signal(signal.SIGINT, _cancel)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("--store", required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps({"ok": True, **admit_reference(
            os.path.abspath(args.source), os.path.abspath(args.store))}),
            flush=True)
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), flush=True)
        return 1
    except KeyboardInterrupt:
        print(json.dumps(
            {"ok": False, "error": "reference admission cancelled"}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
