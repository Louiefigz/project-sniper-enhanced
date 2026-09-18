"""Filesystem snapshots for cross-ledger order reobservation."""

from __future__ import annotations

import hashlib
import os

_RECORD_DOMAIN = b"sniper-cross-ledger-order-record-v1\0"


def cross_ledger_order_record_name_v1(idempotency_key: str) -> str:
    """Derive one record name from the exact admission identity."""
    return hashlib.sha256(
        _RECORD_DOMAIN + idempotency_key.encode("ascii")
    ).hexdigest()


def durable_directory_snapshot(info: os.stat_result) -> tuple[int, ...]:
    """Exclude access time while retaining identity and mutation metadata."""
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_uid,
        info.st_gid,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )
