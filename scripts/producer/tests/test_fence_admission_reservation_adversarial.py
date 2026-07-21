"""Filesystem and cross-record role attacks on fence reservations."""

from __future__ import annotations

import dataclasses
import multiprocessing
import os
import shutil
import unittest
from unittest.mock import patch

from _common import pl  # noqa: F401
from _fence_admission_reservation_fixture import (
    FenceAdmissionReservationFixture,
    reservation_identity,
)
from _operation_admission_fixture import admission, proposal, quality_operation
from _unit_enrollment_fixture import (
    ENROLLMENT_KEY,
    OTHER_ENROLLMENT_KEY,
    OTHER_UNIT,
    enrollment,
    enrollment_proposal,
)
from headless import fence_admission_reservation_records as records_io
from headless.active_fence_lock import (
    ActiveFenceLockError,
    locked_publish_mutex_v1,
)
from headless.cross_ledger_order_schema import (
    build_cross_ledger_order_identity_v1,
)
from headless.fence_admission_reservation_store import (
    STORE_NAME,
    FenceAdmissionReservationConflictV1,
    FenceAdmissionReservationError,
    FenceAdmissionReservationRequestV1,
    persist_or_replay_fence_admission_reservation_v1,
)
from headless.fence_admission_reservation_schema import (
    build_fence_admission_reservation_v1,
)
from headless.operation_admission_store_reader import (
    operation_admission_record_name_v3,
)
from headless.unit_enrollment_store import (
    persist_or_replay_prospective_unit_enrollment_v1,
    reobserve_prospective_unit_enrollment_v1,
)
from headless.unit_enrollment_store_types import (
    UnitEnrollmentReadRequestV1,
    UnitEnrollmentStoreRequestV1,
)

SECOND_ATTEMPT = "babababa-baba-4bab-8bab-babababababa"
SECOND_CHILD = "bcbcbcbc-bcbc-4bcb-8bcb-bcbcbcbcbcbc"


def _persist_worker(
    root: str,
    payload: tuple[object, object, object],
    output: object,
) -> None:
    identity, admitted, enrolled = payload
    try:
        with locked_publish_mutex_v1(root) as lock:
            request = FenceAdmissionReservationRequestV1(
                lock, identity, admitted, enrolled
            )
            result = persist_or_replay_fence_admission_reservation_v1(request)
        output.put(("ok", result.reservation.admission_digest))
    except FenceAdmissionReservationConflictV1:
        output.put(("conflict", admitted.admission_digest))
    except Exception as exc:  # pragma: no cover - reported by parent
        output.put((type(exc).__name__, str(exc)))


def _second_identity(enrolled: object, admitted: object):
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


class FenceAdmissionReservationAdversarialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = FenceAdmissionReservationFixture()
        self.addCleanup(self.fixture.close)

    def test_unsafe_and_conflicting_pending_files_fail_closed(self) -> None:
        attacks = ("nonprefix", "oversize", "symlink", "hardlink", "fifo")
        for attack in attacks:
            with self.subTest(attack=attack):
                fixture = FenceAdmissionReservationFixture()
                self.addCleanup(fixture.close)
                store = os.path.join(fixture.root, STORE_NAME)
                os.mkdir(store, 0o700)
                name = records_io.fence_admission_reservation_record_name_v1(
                    fixture.admitted.attempt_id
                )
                pending = os.path.join(store, f".pending-{name}")
                target = os.path.join(fixture.root, f"target-{attack}")
                if attack in {"nonprefix", "oversize"}:
                    raw = b"not-a-canonical-prefix"
                    if attack == "oversize":
                        raw = b"x" * (records_io.MAX_RESERVATION_BYTES + 1)
                    with open(pending, "wb") as output:
                        output.write(raw)
                    os.chmod(pending, 0o600)
                elif attack == "fifo":
                    os.mkfifo(pending, 0o600)
                else:
                    with open(target, "wb") as output:
                        output.write(b"target")
                    os.chmod(target, 0o600)
                    if attack == "symlink":
                        os.symlink(target, pending)
                    else:
                        os.link(target, pending)
                with self.assertRaises(FenceAdmissionReservationError):
                    fixture.persist()
                self.assertTrue(os.path.lexists(pending))

    def test_complete_pending_with_wrong_target_name_is_preserved(
        self,
    ) -> None:
        store = os.path.join(self.fixture.root, STORE_NAME)
        os.mkdir(store, 0o700)
        admitted = self.fixture.admitted
        reservation = build_fence_admission_reservation_v1(
            reservation_identity(self.fixture.cross, admitted),
            admitted,
            self.fixture.cross.durable_enrollment,
        )
        wrong = os.path.join(store, f".pending-{'f' * 64}")
        with open(wrong, "wb") as output:
            output.write(reservation.document_json)
        os.chmod(wrong, 0o600)
        with self.assertRaises(FenceAdmissionReservationConflictV1):
            self.fixture.persist()
        self.assertTrue(os.path.isfile(wrong))

    def test_unknown_symlink_hardlink_and_oversize_finals_fail(self) -> None:
        for attack in ("unknown", "symlink", "hardlink", "oversize"):
            with self.subTest(attack=attack):
                fixture = FenceAdmissionReservationFixture()
                self.addCleanup(fixture.close)
                created = fixture.persist()
                store = os.path.join(fixture.root, STORE_NAME)
                final = os.path.join(store, created.record_name)
                archived = os.path.join(fixture.root, f"archive-{attack}")
                if attack == "unknown":
                    with open(os.path.join(store, "surprise"), "wb"):
                        pass
                    os.chmod(os.path.join(store, "surprise"), 0o600)
                else:
                    os.rename(final, archived)
                    if attack == "symlink":
                        os.symlink(archived, final)
                    elif attack == "hardlink":
                        os.link(archived, final)
                    else:
                        with open(final, "wb") as output:
                            output.write(
                                b"x" * (records_io.MAX_RESERVATION_BYTES + 1)
                            )
                        os.chmod(final, 0o600)
                with self.assertRaises(FenceAdmissionReservationError):
                    fixture.persist()

    def test_named_inode_swap_during_replay_is_detected(self) -> None:
        created = self.fixture.persist()
        store = os.path.join(self.fixture.root, STORE_NAME)
        final = os.path.join(store, created.record_name)
        archived = os.path.join(self.fixture.root, "archived-reservation")
        original = records_io.assert_named_private_file_identity
        calls = 0

        def attack(parent_fd: int, name: str, child_fd: int) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                os.rename(final, archived)
                shutil.copy2(archived, final)
                os.chmod(final, 0o600)
            original(parent_fd, name, child_fd)

        with patch.object(
            records_io,
            "assert_named_private_file_identity",
            side_effect=attack,
        ), self.assertRaises(FenceAdmissionReservationError):
            self.fixture.persist()

    def test_forged_lock_cannot_create_store_via_exported_helper(self) -> None:
        store = os.path.join(self.fixture.root, STORE_NAME)
        with locked_publish_mutex_v1(self.fixture.root) as lock:
            forged = dataclasses.replace(lock)
            with self.assertRaises(ActiveFenceLockError):
                records_io.open_fence_admission_reservation_store_v1(forged)
        self.assertFalse(os.path.exists(store))

    def test_enrollment_key_cannot_alias_later_idempotency_role(self) -> None:
        self.fixture.persist()
        operation = quality_operation(OTHER_UNIT)
        proposed_enrollment = enrollment_proposal(
            operation,
            enrollment_key=OTHER_ENROLLMENT_KEY,
            unit_id=OTHER_UNIT,
        )
        prospective = enrollment(operation, proposed_enrollment)
        persist_or_replay_prospective_unit_enrollment_v1(
            UnitEnrollmentStoreRequestV1(self.fixture.root, prospective)
        )
        enrolled = reobserve_prospective_unit_enrollment_v1(
            UnitEnrollmentReadRequestV1(
                self.fixture.root,
                prospective.authority_id,
                prospective.enrollment_key,
            )
        )
        proposed_admission = dataclasses.replace(
            proposal(operation),
            idempotency_key=ENROLLMENT_KEY,
            attempt_id=SECOND_ATTEMPT,
            intended_child_generation_id=SECOND_CHILD,
        )
        admitted = admission(operation, proposed_admission)
        with locked_publish_mutex_v1(self.fixture.root) as lock:
            request = FenceAdmissionReservationRequestV1(
                lock,
                _second_identity(enrolled, admitted),
                admitted,
                enrolled,
            )
            with self.assertRaises(FenceAdmissionReservationConflictV1):
                persist_or_replay_fence_admission_reservation_v1(request)

    def test_concurrent_same_attempt_equivocation_has_one_winner(self) -> None:
        base = self.fixture.cross.request().admission.proposal
        changed = admission(
            self.fixture.cross.operation,
            dataclasses.replace(
                base,
                intended_child_generation_id=SECOND_CHILD,
            ),
        )
        enrolled = self.fixture.cross.durable_enrollment
        submissions = (self.fixture.admitted, changed)
        context = multiprocessing.get_context("fork")
        output = context.Queue()
        processes = [
            context.Process(
                target=_persist_worker,
                args=(
                    self.fixture.root,
                    (
                        _second_identity(enrolled, admitted),
                        admitted,
                        enrolled,
                    ),
                    output,
                ),
            )
            for admitted in submissions
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(5)
            self.assertEqual(process.exitcode, 0)
        results = [output.get(timeout=2) for _ in processes]
        self.assertEqual({item[0] for item in results}, {"ok", "conflict"})
        store = os.path.join(self.fixture.root, STORE_NAME)
        self.assertEqual(len(os.listdir(store)), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
