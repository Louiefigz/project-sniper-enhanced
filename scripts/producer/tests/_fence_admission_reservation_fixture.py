"""Exact fixture helpers for durable fence-admission reservations."""

from __future__ import annotations

import os

from _cross_ledger_order_fixture import CrossLedgerOrderFixture
from headless.active_fence_lock import locked_publish_mutex_v1
from headless.cross_ledger_order_schema import (
    build_cross_ledger_order_identity_v1,
)
from headless.fence_admission_reservation_store import (
    FenceAdmissionReservationRequestV1,
    persist_or_replay_fence_admission_reservation_v1,
    reobserve_fence_admission_reservation_v1,
)
from headless.operation_admission_store_reader import (
    operation_admission_record_name_v3,
)


def reservation_identity(fixture: CrossLedgerOrderFixture, admitted: object):
    """Build the prospective exact order identity for one admission."""
    enrolled = fixture.durable_enrollment
    retained = enrolled.structural_binding.enrollment
    return build_cross_ledger_order_identity_v1(
        (
            retained.authority_id,
            retained.unit_id,
            retained.enrollment_key,
            enrolled.record_id,
            retained.enrollment_digest,
            admitted.idempotency_key,
            admitted.attempt_id,
            admitted.intended_child_generation_id,
            operation_admission_record_name_v3(admitted.idempotency_key),
            admitted.admission_digest,
        )
    )


def reservation_request(
    fixture: CrossLedgerOrderFixture, lock: object, admitted: object
) -> FenceAdmissionReservationRequestV1:
    """Return one exact four-field reservation request."""
    return FenceAdmissionReservationRequestV1(
        lock,
        reservation_identity(fixture, admitted),
        admitted,
        fixture.durable_enrollment,
    )


def same_file(fd: int, path: str) -> bool:
    """Report whether a descriptor is the current named inode."""
    try:
        held = os.fstat(fd)
        named = os.stat(path, follow_symlinks=False)
    except OSError:
        return False
    return (held.st_dev, held.st_ino) == (named.st_dev, named.st_ino)


class FenceAdmissionReservationFixture:
    """One enrolled authority and its exact prospective V3 admission."""

    def __init__(self) -> None:
        self.cross = CrossLedgerOrderFixture()
        self.root = self.cross.root
        self.admitted = self.cross.request().admission.admission

    def close(self) -> None:
        """Remove the temporary authority root."""
        self.cross.close()

    def persist(self, admitted: object | None = None):
        """Persist under a fresh live publisher-mutex witness."""
        selected = admitted or self.admitted
        with locked_publish_mutex_v1(self.root) as lock:
            request = reservation_request(self.cross, lock, selected)
            return persist_or_replay_fence_admission_reservation_v1(request)

    def reobserve(self, admitted: object | None = None):
        """Read through the noncreating exact replay API."""
        selected = admitted or self.admitted
        with locked_publish_mutex_v1(self.root) as lock:
            request = reservation_request(self.cross, lock, selected)
            return reobserve_fence_admission_reservation_v1(request)
