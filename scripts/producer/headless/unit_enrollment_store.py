"""Authority-owned durable store for prospective unit enrollments."""

from __future__ import annotations

import os
from dataclasses import dataclass

from . import quality_receipt_json as wire
from .authority_record import (
    AuthorityRecordError,
    read_authority_record,
)
from .durable_files import (
    DurableFileError,
    locked_existing_private_dir,
    open_private_child_dir,
)
from .unit_enrollment_binding import (
    UnitEnrollmentBindingError,
    bind_prospective_unit_enrollment_v1,
)
from .unit_enrollment_authority import (  # noqa: F401
    require_durable_unit_enrollment_execution_authorized,
)
from .unit_enrollment_schema import ProspectiveUnitEnrollmentV1
from .unit_enrollment_lock import (
    UnitEnrollmentWriterLockError,
    locked_unit_enrollment_writer_v1,
)
from .unit_enrollment_durability import (
    UnitEnrollmentDurabilityError,
    pinned_durable_unit_enrollment_record_v1,
)
from .unit_enrollment_pending import (
    UnitEnrollmentPendingError,
    cleanup_abandoned_unit_enrollment_pending_v1,
)
from .unit_enrollment_record import unit_enrollment_record_name_v1
from .unit_enrollment_store_types import (
    DurableUnitEnrollmentV1,
    UnitEnrollmentReadRequestV1,
    UnitEnrollmentStoreRequestV1,
)
from .unit_enrollment_store_result import durable_unit_enrollment_result
from .unit_enrollment_store_persistence import (
    persist_unit_enrollment_record_v1,
)
from .unit_enrollment_store_errors import (
    UnitEnrollmentKeyConflictV1,
    UnitEnrollmentStoreError,
    UnitEnrollmentUnitConflictV1,
)
from .unit_enrollment_store_snapshot import (
    UnitEnrollmentSnapshotError,
    pinned_unit_enrollment_set,
    require_unit_enrollment_store_entry,
    unit_enrollment_record_names,
)

_LOCK_NAME = ".unit-enrollment-v1.lock"
_STORE_NAME = "unit-enrollments-v1"
_MAX_ENROLLMENT_RECORDS = 4096
_MAX_ENROLLMENT_BYTES = 16_384


@dataclass(frozen=True)
class _StoredEnrollment:
    name: str
    enrollment: ProspectiveUnitEnrollmentV1


def _load_all(
    store_fd: int, authority_id: str
) -> tuple[_StoredEnrollment, ...]:
    try:
        names = unit_enrollment_record_names(store_fd, _MAX_ENROLLMENT_RECORDS)
        with pinned_unit_enrollment_set(
            store_fd, names, _MAX_ENROLLMENT_BYTES
        ) as snapshots:
            records = tuple(
                _StoredEnrollment(item.name, item.enrollment)
                for item in snapshots
            )
            if any(
                record.name
                != unit_enrollment_record_name_v1(
                    record.enrollment.enrollment_key
                )
                for record in records
            ):
                raise UnitEnrollmentStoreError(
                    "stored unit enrollment name is invalid"
                )
            if any(
                record.enrollment.authority_id != authority_id
                for record in records
            ):
                raise UnitEnrollmentStoreError(
                    "unit enrollment store crosses authorities"
                )
            units = [record.enrollment.unit_id for record in records]
            if len(units) != len(set(units)):
                raise UnitEnrollmentStoreError(
                    "unit enrollment store duplicates a unit ID"
                )
            return records
    except UnitEnrollmentSnapshotError as exc:
        raise UnitEnrollmentStoreError(str(exc)) from exc


def _result(
    created: bool, record: _StoredEnrollment
) -> DurableUnitEnrollmentV1:
    return durable_unit_enrollment_result(
        created, record.name, record.enrollment
    )


def _replay_existing(
    store_fd: int, name: str, enrollment: ProspectiveUnitEnrollmentV1
) -> DurableUnitEnrollmentV1:
    with pinned_durable_unit_enrollment_record_v1(store_fd, name) as durable:
        retained = _load_all(store_fd, enrollment.authority_id)
        confirmed = next((row for row in retained if row.name == name), None)
        exact = durable.document_json == enrollment.document_json
        if (
            confirmed is None
            or not exact
            or (confirmed.enrollment.document_json != durable.document_json)
        ):
            raise UnitEnrollmentStoreError(
                "unit enrollment changed during durability recovery"
            )
        return _result(False, _StoredEnrollment(name, durable))


def _enroll_locked(
    store_fd: int, enrollment: ProspectiveUnitEnrollmentV1
) -> DurableUnitEnrollmentV1:
    records = _load_all(store_fd, enrollment.authority_id)
    name = unit_enrollment_record_name_v1(enrollment.enrollment_key)
    existing = next(
        (record for record in records if record.name == name), None
    )
    if existing is not None:
        if existing.enrollment.document_json != enrollment.document_json:
            raise UnitEnrollmentKeyConflictV1(
                "enrollment key is bound to different exact identity"
            )
        return _replay_existing(store_fd, name, enrollment)
    if len(records) >= _MAX_ENROLLMENT_RECORDS:
        raise UnitEnrollmentStoreError(
            "unit enrollment store exceeds its record limit"
        )
    if any(
        record.enrollment.unit_id == enrollment.unit_id for record in records
    ):
        raise UnitEnrollmentUnitConflictV1("unit ID is already enrolled")
    persist_unit_enrollment_record_v1(store_fd, name, enrollment)
    retained = _load_all(store_fd, enrollment.authority_id)
    created = next(
        (record for record in retained if record.name == name), None
    )
    if (
        created is None
        or created.enrollment.document_json != enrollment.document_json
    ):
        raise UnitEnrollmentStoreError(
            "created unit enrollment is not retained"
        )
    return _result(True, created)


def _require_authority(root_fd: int, authority_id: str) -> None:
    try:
        retained = read_authority_record(root_fd)
    except AuthorityRecordError as exc:
        raise UnitEnrollmentStoreError(
            "unit enrollment authority is invalid"
        ) from exc
    if retained != {"authorityId": authority_id, "schemaVersion": 1}:
        raise UnitEnrollmentStoreError("unit enrollment authority is invalid")


def persist_or_replay_prospective_unit_enrollment_v1(
    request: object,
) -> DurableUnitEnrollmentV1:
    """Persist or replay exact enrollment under global unit arbitration."""
    if type(request) is not UnitEnrollmentStoreRequestV1:
        raise UnitEnrollmentStoreError(
            "unit enrollment store request is invalid"
        )
    try:
        bind_prospective_unit_enrollment_v1(request.enrollment)
        with locked_unit_enrollment_writer_v1(
            request.authority_root, request.enrollment.authority_id
        ) as writer:
            cleanup_abandoned_unit_enrollment_pending_v1(writer)
            result = _enroll_locked(writer.store_fd, request.enrollment)
            require_unit_enrollment_store_entry(
                writer.root_fd, writer.store_fd
            )
            _require_authority(writer.root_fd, request.enrollment.authority_id)
            return result
    except UnitEnrollmentStoreError:
        raise
    except (
        UnitEnrollmentDurabilityError,
        UnitEnrollmentWriterLockError,
        UnitEnrollmentPendingError,
    ) as exc:
        raise UnitEnrollmentStoreError(str(exc)) from exc
    except (DurableFileError, UnitEnrollmentBindingError, RuntimeError) as exc:
        raise UnitEnrollmentStoreError(
            "unit enrollment persistence failed"
        ) from exc


def _reobserve_locked(
    root_fd: int, store_fd: int, authority_id: str, enrollment_key: str
) -> DurableUnitEnrollmentV1:
    records = _load_all(store_fd, authority_id)
    name = unit_enrollment_record_name_v1(enrollment_key)
    selected = next((row for row in records if row.name == name), None)
    if selected is None:
        raise UnitEnrollmentStoreError("unit enrollment record is unknown")
    require_unit_enrollment_store_entry(root_fd, store_fd)
    with pinned_durable_unit_enrollment_record_v1(store_fd, name) as durable:
        records = _load_all(store_fd, authority_id)
        record = next((row for row in records if row.name == name), None)
        if record is None or record.enrollment.document_json != (
            durable.document_json
        ):
            raise UnitEnrollmentStoreError(
                "unit enrollment changed during reobservation"
            )
        require_unit_enrollment_store_entry(root_fd, store_fd)
        _require_authority(root_fd, authority_id)
        return _result(False, _StoredEnrollment(name, durable))


def reobserve_prospective_unit_enrollment_v1(
    request: object,
) -> DurableUnitEnrollmentV1:
    """Read retained enrollment without creating authority or store state."""
    if type(request) is not UnitEnrollmentReadRequestV1:
        raise UnitEnrollmentStoreError(
            "unit enrollment read request is invalid"
        )
    try:
        authority_id = wire.authority(request.authority_id)
        enrollment_key = wire.canonical_uuid(
            request.enrollment_key, "enrollment key"
        )
        with locked_existing_private_dir(
            request.authority_root, _LOCK_NAME
        ) as root_fd:
            _require_authority(root_fd, authority_id)
            store_fd = open_private_child_dir(root_fd, _STORE_NAME)
            try:
                result = _reobserve_locked(
                    root_fd, store_fd, authority_id, enrollment_key
                )
            finally:
                os.close(store_fd)
        return result
    except UnitEnrollmentStoreError:
        raise
    except (
        DurableFileError,
        UnitEnrollmentDurabilityError,
        RuntimeError,
    ) as exc:
        raise UnitEnrollmentStoreError(
            "unit enrollment reobservation failed"
        ) from exc
