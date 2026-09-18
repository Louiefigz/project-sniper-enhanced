"""Nominal identity, replay, conflict, and non-authority reservation tests."""

from __future__ import annotations

import dataclasses
import json
import os
import unittest

from _common import pl  # noqa: F401
from _fence_admission_reservation_fixture import (
    FenceAdmissionReservationFixture,
    reservation_identity,
    reservation_request,
)
from _operation_admission_fixture import admission
from headless.active_fence_lock import locked_publish_mutex_v1
from headless.fence_admission_reservation_store import (
    STORE_NAME,
    FenceAdmissionReservationConflictV1,
    FenceAdmissionReservationError,
    FenceAdmissionReservationRequestV1,
    persist_or_replay_fence_admission_reservation_v1,
    reobserve_fence_admission_reservation_v1,
)
from headless.fence_admission_reservation_validation import (
    DurableFenceAdmissionReservationValidationError,
    validate_durable_fence_admission_reservation_v1,
)
from headless.operation_contract import parse_headless_mp4_operation_v1
from headless.operation_wire import canonical

CHANGED_CHILD = "abababab-abab-4bab-8bab-abababababab"
CHANGED_ATTEMPT = "acacacac-acac-4cac-8cac-acacacacacac"
CHANGED_IDEMPOTENCY = "adadadad-adad-4dad-8dad-adadadadadad"
OTHER_UNIT = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
OTHER_AUTHORITY = "authority-other-mp4-v1"


class FenceAdmissionReservationStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = FenceAdmissionReservationFixture()
        self.addCleanup(self.fixture.close)

    def test_exact_create_replay_and_read_are_nonauthorizing(self) -> None:
        created = self.fixture.persist()
        path = os.path.join(self.fixture.root, STORE_NAME, created.record_name)
        before = os.stat(path)
        replayed = self.fixture.persist()
        observed = self.fixture.reobserve()
        after = os.stat(path)
        self.assertTrue(created.created)
        self.assertFalse(replayed.created)
        self.assertFalse(observed.created)
        self.assertEqual(created.reservation, observed.reservation)
        self.assertEqual(
            (before.st_ino, before.st_mtime_ns),
            (after.st_ino, after.st_mtime_ns),
        )
        for value in (created, replayed, observed):
            validate_durable_fence_admission_reservation_v1(value)
            self.assertTrue(value.reservation_bytes_reobserved)
            self.assertTrue(value.replay_arbitrated)
            self.assertFalse(value.execution_authorized)
            self.assertFalse(value.publication_authorized)
        self.assertFalse(
            os.path.exists(os.path.join(self.fixture.root, "CURRENT"))
        )
        row = json.loads(observed.reservation.document_json)
        self.assertIn("enrollmentKey", row)
        self.assertNotIn("workAuthorized", row)
        self.assertNotIn("palmier", str(row).lower())

    def test_forged_result_dataclasses_do_not_compare_as_authority(
        self,
    ) -> None:
        created = self.fixture.persist()
        cases = (
            dataclasses.replace(created, created=1),
            dataclasses.replace(created, execution_authorized=True),
            dataclasses.replace(
                created,
                reservation=dataclasses.replace(
                    created.reservation, reservation_digest="0" * 64
                ),
            ),
        )
        for forged in cases:
            with self.subTest(forged=forged), self.assertRaises(
                DurableFenceAdmissionReservationValidationError
            ):
                validate_durable_fence_admission_reservation_v1(forged)

    def test_noncreating_read_cannot_heal_missing_binding(self) -> None:
        self.assertFalse(
            os.path.exists(os.path.join(self.fixture.root, STORE_NAME))
        )
        with locked_publish_mutex_v1(self.fixture.root) as lock:
            request = reservation_request(
                self.fixture.cross, lock, self.fixture.admitted
            )
            with self.assertRaises(FenceAdmissionReservationError):
                reobserve_fence_admission_reservation_v1(request)
        self.assertFalse(
            os.path.exists(os.path.join(self.fixture.root, STORE_NAME))
        )

    def test_same_attempt_changed_child_and_admission_conflicts(self) -> None:
        self.fixture.persist()
        base = self.fixture.cross.request().admission
        proposed = dataclasses.replace(
            base.proposal,
            intended_child_generation_id=CHANGED_CHILD,
        )
        changed = admission(self.fixture.cross.operation, proposed)
        self.assertNotEqual(
            changed.admission_digest, self.fixture.admitted.admission_digest
        )
        with self.assertRaises(FenceAdmissionReservationConflictV1):
            self.fixture.persist(changed)

    def test_same_attempt_changed_operation_request_conflicts(self) -> None:
        self.fixture.persist()
        document = json.loads(self.fixture.cross.operation.document_json)
        document["qualityPass"]["repairIntent"]["value"] = "#FF0000"
        changed_operation = parse_headless_mp4_operation_v1(
            canonical(document)
        )
        proposed = self.fixture.cross.request().admission.proposal
        changed = admission(changed_operation, proposed)
        self.assertNotEqual(
            changed.request_identity_digest,
            self.fixture.admitted.request_identity_digest,
        )
        with self.assertRaises(FenceAdmissionReservationConflictV1):
            self.fixture.persist(changed)

    def test_idempotency_and_child_reuse_are_typed_conflicts(self) -> None:
        self.fixture.persist()
        base = self.fixture.cross.request().admission.proposal
        cases = (
            dataclasses.replace(
                base,
                attempt_id=CHANGED_ATTEMPT,
                intended_child_generation_id=CHANGED_CHILD,
            ),
            dataclasses.replace(
                base,
                idempotency_key=CHANGED_IDEMPOTENCY,
                attempt_id=CHANGED_ATTEMPT,
            ),
        )
        for proposed in cases:
            changed = admission(self.fixture.cross.operation, proposed)
            with self.subTest(proposed=proposed), self.assertRaises(
                FenceAdmissionReservationConflictV1
            ):
                self.fixture.persist(changed)

    def test_same_enrollment_and_unit_allow_a_distinct_operation(self) -> None:
        self.fixture.persist()
        base = self.fixture.cross.request().admission.proposal
        proposed = dataclasses.replace(
            base,
            idempotency_key=CHANGED_IDEMPOTENCY,
            attempt_id=CHANGED_ATTEMPT,
            intended_child_generation_id=CHANGED_CHILD,
        )
        changed = admission(self.fixture.cross.operation, proposed)
        created = self.fixture.persist(changed)
        self.assertTrue(created.created)
        self.assertEqual(
            os.listdir(os.path.join(self.fixture.root, STORE_NAME)).__len__(),
            2,
        )

    def test_cross_unit_and_cross_authority_are_rejected(self) -> None:
        base = self.fixture.cross.request().admission.proposal
        cross_unit_row = json.loads(self.fixture.cross.operation.document_json)
        cross_unit_row["unitId"] = OTHER_UNIT
        cross_unit_operation = parse_headless_mp4_operation_v1(
            canonical(cross_unit_row)
        )
        cross_unit = admission(
            cross_unit_operation,
            dataclasses.replace(base, unit_id=OTHER_UNIT),
        )
        authority_row = json.loads(self.fixture.cross.operation.document_json)
        authority_row["expectedParent"]["authorityId"] = OTHER_AUTHORITY
        repair = authority_row["qualityPass"]["repairIntent"]
        repair["expectedParent"]["authorityId"] = OTHER_AUTHORITY
        cross_operation = parse_headless_mp4_operation_v1(
            canonical(authority_row)
        )
        cross_authority = admission(
            cross_operation,
            dataclasses.replace(
                base,
                authority_id=OTHER_AUTHORITY,
                expected_parent=cross_operation.expected_parent,
            ),
        )
        for admitted in (cross_unit, cross_authority):
            with self.subTest(admitted=admitted), self.assertRaises(
                FenceAdmissionReservationError
            ):
                self.fixture.persist(admitted)

    def test_forged_values_and_stale_publish_witness_fail(self) -> None:
        admitted = self.fixture.admitted
        forged_identity = dataclasses.replace(
            reservation_identity(self.fixture.cross, admitted),
            order_identity_digest="0" * 64,
        )
        forged_admission = dataclasses.replace(
            admitted, admission_digest="0" * 64
        )
        forged_enrollment = dataclasses.replace(
            self.fixture.cross.durable_enrollment, created=1
        )
        with locked_publish_mutex_v1(self.fixture.root) as lock:
            exact_identity = reservation_identity(self.fixture.cross, admitted)
            requests = (
                FenceAdmissionReservationRequestV1(
                    lock,
                    forged_identity,
                    admitted,
                    self.fixture.cross.durable_enrollment,
                ),
                FenceAdmissionReservationRequestV1(
                    lock,
                    reservation_identity(self.fixture.cross, forged_admission),
                    forged_admission,
                    self.fixture.cross.durable_enrollment,
                ),
                FenceAdmissionReservationRequestV1(
                    lock, exact_identity, admitted, forged_enrollment
                ),
                dataclasses.replace(
                    reservation_request(self.fixture.cross, lock, admitted),
                    lock=dataclasses.replace(lock),
                ),
            )
            for request in requests:
                with self.subTest(request=request), self.assertRaises(
                    FenceAdmissionReservationError
                ):
                    persist_or_replay_fence_admission_reservation_v1(request)
            stale = reservation_request(self.fixture.cross, lock, admitted)
        with self.assertRaises(FenceAdmissionReservationError):
            persist_or_replay_fence_admission_reservation_v1(stale)


if __name__ == "__main__":
    unittest.main(verbosity=2)
