"""Durable immutable reservation records guarded by the publisher mutex."""

from __future__ import annotations

import os

from .active_fence_lock import (
    ActiveFenceLockError,
    ActiveFenceLockV1,
    validate_active_fence_lock_v1,
)
from .authority_record import AuthorityRecordError, read_authority_record
from .durable_files import DurableFileError
from .fence_admission_reservation_records import (
    MAX_RESERVATION_RECORDS,
    STORE_NAME,
    ObservedFenceAdmissionReservationV1,
    fence_admission_reservation_record_name_v1,
    open_existing_fence_admission_reservation_store_v1,
    open_fence_admission_reservation_store_v1,
    pinned_fence_admission_reservation_v1,
    stable_fence_admission_reservation_scan_v1,
)
from .fence_admission_reservation_pending import (
    recover_fence_admission_reservation_pending_v1,
    write_fence_admission_reservation_record_v1,
)
from .fence_admission_reservation_schema import (
    FenceAdmissionReservationSchemaError,
    FenceAdmissionReservationV1,
    build_fence_admission_reservation_v1,
)
from .fence_admission_reservation_types import (
    FENCE_ADMISSION_RESERVATION_STATUS,
    DurableFenceAdmissionReservationV1,
    FenceAdmissionReservationConflictV1,
    FenceAdmissionReservationError,
    FenceAdmissionReservationRequestV1,
)
from .record_durability import assert_named_private_directory_identity
from .unit_enrollment_store import (
    UnitEnrollmentStoreError,
    reobserve_prospective_unit_enrollment_v1,
)
from .unit_enrollment_store_types import UnitEnrollmentReadRequestV1
from .wire_identity import same_wire_value


def _checked_request(
    value: object,
) -> tuple[
    FenceAdmissionReservationRequestV1,
    FenceAdmissionReservationV1,
]:
    if type(value) is not FenceAdmissionReservationRequestV1:
        raise FenceAdmissionReservationError(
            "fence admission reservation request is invalid"
        )
    validate_active_fence_lock_v1(value.lock)
    reservation = build_fence_admission_reservation_v1(
        value.identity, value.admission, value.enrollment
    )
    root = value.lock.authority_root
    if root != os.path.realpath(root):
        raise FenceAdmissionReservationError(
            "fence reservation authority root is invalid"
        )
    return value, reservation


def _require_authority(lock: ActiveFenceLockV1, authority_id: str) -> None:
    retained = read_authority_record(lock.root_fd)
    expected = {"authorityId": authority_id, "schemaVersion": 1}
    if retained != expected:
        raise FenceAdmissionReservationError(
            "fence reservation authority is invalid"
        )


def _reobserve_enrollment(request: FenceAdmissionReservationRequestV1) -> None:
    expected = request.enrollment
    retained = expected.structural_binding.enrollment
    observed = reobserve_prospective_unit_enrollment_v1(
        UnitEnrollmentReadRequestV1(
            request.lock.authority_root,
            retained.authority_id,
            retained.enrollment_key,
        )
    )
    exact = observed.record_id == expected.record_id and same_wire_value(
        observed.structural_binding, expected.structural_binding
    )
    if not exact:
        raise FenceAdmissionReservationError(
            "fence reservation enrollment changed"
        )


def _validate_roles(
    records: tuple[ObservedFenceAdmissionReservationV1, ...],
    authority_id: str,
) -> None:
    roles: dict[str, str] = {}
    unique: dict[tuple[str, str], str] = {}
    for item in records:
        value = item.reservation
        expected_name = fence_admission_reservation_record_name_v1(
            value.attempt_id
        )
        if item.name != expected_name or value.authority_id != authority_id:
            raise FenceAdmissionReservationError(
                "fence reservation record identity is invalid"
            )
        values = {
            "attempt": value.attempt_id,
            "idempotency": value.idempotency_key,
            "enrollment": value.enrollment_key,
            "unit": value.unit_id,
            "child": value.intended_child_generation_id,
        }
        for role, identifier in values.items():
            previous = roles.setdefault(identifier, role)
            if previous != role:
                raise FenceAdmissionReservationError(
                    "fence reservation UUID roles conflict"
                )
            key = (role, identifier)
            owner = unique.setdefault(key, item.name)
            if role not in {"enrollment", "unit"} and owner != item.name:
                raise FenceAdmissionReservationError(
                    "fence reservation unique role is duplicated"
                )


def _require_candidate_roles(
    records: tuple[ObservedFenceAdmissionReservationV1, ...],
    candidate: FenceAdmissionReservationV1,
) -> None:
    retained: dict[str, tuple[str, str]] = {}
    for item in records:
        value = item.reservation
        values = {
            "attempt": value.attempt_id,
            "idempotency": value.idempotency_key,
            "enrollment": value.enrollment_key,
            "unit": value.unit_id,
            "child": value.intended_child_generation_id,
        }
        for role, identifier in values.items():
            retained.setdefault(identifier, (role, item.name))
    candidate_values = {
        "attempt": candidate.attempt_id,
        "idempotency": candidate.idempotency_key,
        "enrollment": candidate.enrollment_key,
        "unit": candidate.unit_id,
        "child": candidate.intended_child_generation_id,
    }
    for role, identifier in candidate_values.items():
        previous = retained.get(identifier)
        aliases = previous is not None and previous[0] != role
        repeatable = {"enrollment", "unit"}
        duplicated = previous is not None and role not in repeatable
        if aliases or duplicated:
            raise FenceAdmissionReservationConflictV1(
                "fence reservation candidate UUID role conflicts"
            )


def _retained_result(
    store_fd: int,
    expected: FenceAdmissionReservationV1,
    created: bool,
) -> DurableFenceAdmissionReservationV1:
    name = fence_admission_reservation_record_name_v1(expected.attempt_id)
    with pinned_fence_admission_reservation_v1(store_fd, name) as selected:
        if selected.raw != expected.document_json:
            raise FenceAdmissionReservationConflictV1(
                "attempt is bound to different reservation bytes"
            )
        records = stable_fence_admission_reservation_scan_v1(store_fd)
        _validate_roles(records, expected.authority_id)
        if not any(item.name == name for item in records):
            raise FenceAdmissionReservationError(
                "fence reservation disappeared during replay"
            )
        return DurableFenceAdmissionReservationV1(
            FENCE_ADMISSION_RESERVATION_STATUS,
            created,
            name,
            selected.reservation,
            True,
            True,
            False,
            False,
        )


def _persist_locked(
    store_fd: int, reservation: FenceAdmissionReservationV1
) -> DurableFenceAdmissionReservationV1:
    name = fence_admission_reservation_record_name_v1(reservation.attempt_id)
    recover_fence_admission_reservation_pending_v1(
        store_fd, name, reservation.document_json
    )
    records = stable_fence_admission_reservation_scan_v1(store_fd)
    _validate_roles(records, reservation.authority_id)
    if any(item.name == name for item in records):
        return _retained_result(store_fd, reservation, False)
    if len(records) >= MAX_RESERVATION_RECORDS:
        raise FenceAdmissionReservationError(
            "fence reservation store exceeds its record limit"
        )
    _require_candidate_roles(records, reservation)
    write_fence_admission_reservation_record_v1(
        store_fd, name, reservation.document_json
    )
    return _retained_result(store_fd, reservation, True)


def persist_or_replay_fence_admission_reservation_v1(
    value: object,
) -> DurableFenceAdmissionReservationV1:
    """Persist/replay one exact binding using only a live caller-held mutex."""
    store_fd = None
    try:
        request, reservation = _checked_request(value)
        _require_authority(request.lock, reservation.authority_id)
        _reobserve_enrollment(request)
        validate_active_fence_lock_v1(request.lock)
        store_fd = open_fence_admission_reservation_store_v1(request.lock)
        result = _persist_locked(store_fd, reservation)
        assert_named_private_directory_identity(
            request.lock.root_fd, STORE_NAME, store_fd
        )
        validate_active_fence_lock_v1(request.lock)
        return result
    except FenceAdmissionReservationConflictV1:
        raise
    except FenceAdmissionReservationError:
        raise
    except (
        ActiveFenceLockError,
        AuthorityRecordError,
        DurableFileError,
        FenceAdmissionReservationSchemaError,
        UnitEnrollmentStoreError,
        OSError,
    ) as exc:
        raise FenceAdmissionReservationError(
            "fence admission reservation persistence failed"
        ) from exc
    finally:
        if store_fd is not None:
            os.close(store_fd)


def reobserve_fence_admission_reservation_v1(
    value: object,
) -> DurableFenceAdmissionReservationV1:
    """Reobserve an exact existing binding without creating or healing it."""
    store_fd = None
    try:
        request, reservation = _checked_request(value)
        _require_authority(request.lock, reservation.authority_id)
        _reobserve_enrollment(request)
        validate_active_fence_lock_v1(request.lock)
        store_fd = open_existing_fence_admission_reservation_store_v1(
            request.lock
        )
        result = _retained_result(store_fd, reservation, False)
        assert_named_private_directory_identity(
            request.lock.root_fd, STORE_NAME, store_fd
        )
        validate_active_fence_lock_v1(request.lock)
        return result
    except FenceAdmissionReservationConflictV1:
        raise
    except FenceAdmissionReservationError:
        raise
    except (
        ActiveFenceLockError,
        AuthorityRecordError,
        DurableFileError,
        FenceAdmissionReservationSchemaError,
        UnitEnrollmentStoreError,
        OSError,
    ) as exc:
        raise FenceAdmissionReservationError(
            "fence admission reservation reobservation failed"
        ) from exc
    finally:
        if store_fd is not None:
            os.close(store_fd)
