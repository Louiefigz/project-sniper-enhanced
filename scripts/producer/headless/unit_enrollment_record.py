"""Stable record identity for prospective unit enrollments."""

from __future__ import annotations

import hashlib

_RECORD_DOMAIN = b"sniper-unit-enrollment-record-v1\0"


def unit_enrollment_record_name_v1(enrollment_key: str) -> str:
    """Derive the one record name owned by an enrollment key."""
    return hashlib.sha256(
        _RECORD_DOMAIN + enrollment_key.encode("ascii")
    ).hexdigest()
