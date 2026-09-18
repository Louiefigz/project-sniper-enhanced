"""Crash-window and durability-barrier tests for fence reservations."""

from __future__ import annotations

import os
import unittest
import dataclasses
from unittest.mock import patch

from _common import pl  # noqa: F401
from _fence_admission_reservation_fixture import (
    FenceAdmissionReservationFixture,
    reservation_identity,
    reservation_request,
    same_file,
)
from _operation_admission_fixture import admission
from headless import fence_admission_reservation_pending as pending_io
from headless import fence_admission_reservation_records as records_io
from headless.active_fence_lock import locked_publish_mutex_v1
from headless.fence_admission_reservation_schema import (
    build_fence_admission_reservation_v1,
)
from headless.fence_admission_reservation_store import (
    STORE_NAME,
    FenceAdmissionReservationConflictV1,
    FenceAdmissionReservationError,
    reobserve_fence_admission_reservation_v1,
)

OTHER_IDEMPOTENCY = "cececece-cece-4cec-8cec-cececececece"
OTHER_ATTEMPT = "cfcfcfcf-cfcf-4fcf-8fcf-cfcfcfcfcfcf"
OTHER_CHILD = "dededede-dede-4ded-8ded-dededededede"


class FenceAdmissionReservationRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = FenceAdmissionReservationFixture()
        self.addCleanup(self.fixture.close)

    def _paths(self) -> tuple[str, str, str]:
        name = records_io.fence_admission_reservation_record_name_v1(
            self.fixture.admitted.attempt_id
        )
        store = os.path.join(self.fixture.root, STORE_NAME)
        return store, os.path.join(store, name), f".pending-{name}"

    def _expected(self) -> bytes:
        admitted = self.fixture.admitted
        reservation = build_fence_admission_reservation_v1(
            reservation_identity(self.fixture.cross, admitted),
            admitted,
            self.fixture.cross.durable_enrollment,
        )
        return reservation.document_json

    def _make_pending(self, raw: bytes) -> str:
        store, _, pending = self._paths()
        os.mkdir(store, 0o700)
        os.chmod(store, 0o700)
        path = os.path.join(store, pending)
        with open(path, "wb") as output:
            output.write(raw)
        os.chmod(path, 0o600)
        return path

    def test_visible_final_after_failed_store_fsync_replays_barrier(
        self,
    ) -> None:
        store, final, _ = self._paths()
        original = os.fsync
        failed = False

        def interrupt(fd: int) -> None:
            nonlocal failed
            if not failed and os.path.exists(final) and same_file(fd, store):
                failed = True
                raise OSError("simulated final directory fsync failure")
            original(fd)

        with patch.object(pending_io.os, "fsync", side_effect=interrupt):
            with self.assertRaises(FenceAdmissionReservationError):
                self.fixture.persist()
        self.assertTrue(failed)
        self.assertTrue(os.path.isfile(final))
        synced = {"file": False, "store": False}

        def track(fd: int) -> None:
            synced["file"] |= same_file(fd, final)
            synced["store"] |= same_file(fd, store)
            original(fd)

        with patch.object(records_io.os, "fsync", side_effect=track):
            replayed = self.fixture.persist()
        self.assertFalse(replayed.created)
        self.assertEqual(synced, {"file": True, "store": True})

    def test_crash_before_no_overwrite_link_recovers_pending(self) -> None:
        store, final, pending = self._paths()
        with patch.object(
            pending_io.os, "link", side_effect=OSError("crash before link")
        ):
            with self.assertRaises(FenceAdmissionReservationError):
                self.fixture.persist()
        self.assertTrue(os.path.isfile(os.path.join(store, pending)))
        self.assertFalse(os.path.exists(final))
        replayed = self.fixture.persist()
        self.assertFalse(replayed.created)
        self.assertTrue(os.path.isfile(final))
        self.assertFalse(os.path.exists(os.path.join(store, pending)))

    def test_other_complete_pending_is_safely_discarded(self) -> None:
        store, first_final, first_pending = self._paths()
        with patch.object(
            pending_io.os, "link", side_effect=OSError("crash before link")
        ):
            with self.assertRaises(FenceAdmissionReservationError):
                self.fixture.persist()
        base = self.fixture.cross.request().admission.proposal
        second = admission(
            self.fixture.cross.operation,
            dataclasses.replace(
                base,
                idempotency_key=OTHER_IDEMPOTENCY,
                attempt_id=OTHER_ATTEMPT,
                intended_child_generation_id=OTHER_CHILD,
            ),
        )
        created = self.fixture.persist(second)
        self.assertTrue(created.created)
        self.assertFalse(os.path.exists(first_final))
        self.assertFalse(os.path.exists(os.path.join(store, first_pending)))

    def test_other_partial_pending_requires_its_exact_request(self) -> None:
        expected = self._expected()
        pending_path = self._make_pending(expected[:40])
        base = self.fixture.cross.request().admission.proposal
        second = admission(
            self.fixture.cross.operation,
            dataclasses.replace(
                base,
                idempotency_key=OTHER_IDEMPOTENCY,
                attempt_id=OTHER_ATTEMPT,
                intended_child_generation_id=OTHER_CHILD,
            ),
        )
        with self.assertRaises(FenceAdmissionReservationError):
            self.fixture.persist(second)
        self.assertTrue(os.path.isfile(pending_path))
        recovered = self.fixture.persist()
        self.assertFalse(recovered.created)

    def test_crash_after_visible_link_recovers_same_inode_pair(self) -> None:
        store, final, pending = self._paths()
        original = os.link

        def visible_then_fail(*args: object, **kwargs: object) -> None:
            original(*args, **kwargs)
            raise OSError("crash after link became visible")

        with patch.object(
            pending_io.os, "link", side_effect=visible_then_fail
        ):
            with self.assertRaises(FenceAdmissionReservationError):
                self.fixture.persist()
        pending_path = os.path.join(store, pending)
        self.assertEqual(os.stat(final).st_ino, os.stat(pending_path).st_ino)
        recovered = self.fixture.persist()
        self.assertFalse(recovered.created)
        self.assertFalse(os.path.exists(pending_path))
        self.assertEqual(os.stat(final).st_nlink, 1)

    def test_strict_prefix_pending_is_reconstructed_and_published(
        self,
    ) -> None:
        expected = self._expected()
        pending_path = self._make_pending(expected[: len(expected) // 2])
        replayed = self.fixture.persist()
        _, final, _ = self._paths()
        self.assertFalse(replayed.created)
        self.assertFalse(os.path.exists(pending_path))
        with open(final, "rb") as source:
            self.assertEqual(source.read(), expected)

    def test_read_only_reobservation_does_not_heal_prefix_pending(
        self,
    ) -> None:
        expected = self._expected()
        pending_path = self._make_pending(expected[:40])
        _, final, _ = self._paths()
        with locked_publish_mutex_v1(self.fixture.root) as lock:
            request = reservation_request(
                self.fixture.cross, lock, self.fixture.admitted
            )
            with self.assertRaises(FenceAdmissionReservationError):
                reobserve_fence_admission_reservation_v1(request)
        self.assertTrue(os.path.isfile(pending_path))
        self.assertFalse(os.path.exists(final))

    def test_conflicting_final_is_never_overwritten_by_pending(self) -> None:
        store, final, pending = self._paths()
        original = os.link
        marker = b"attacker-retained-final"

        def install_conflict(*args: object, **kwargs: object) -> None:
            destination = args[1]
            dir_fd = kwargs["dst_dir_fd"]
            fd = os.open(
                destination,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=dir_fd,
            )
            try:
                os.write(fd, marker)
            finally:
                os.close(fd)
            original(*args, **kwargs)

        with patch.object(pending_io.os, "link", side_effect=install_conflict):
            with self.assertRaises(FenceAdmissionReservationConflictV1):
                self.fixture.persist()
        with open(final, "rb") as source:
            self.assertEqual(source.read(), marker)
        self.assertTrue(os.path.isfile(os.path.join(store, pending)))
        with self.assertRaises(FenceAdmissionReservationConflictV1):
            self.fixture.persist()
        with open(final, "rb") as source:
            self.assertEqual(source.read(), marker)

    def test_global_scan_does_not_fsync_every_reservation_file(self) -> None:
        first = self.fixture.persist()
        store = os.path.join(self.fixture.root, STORE_NAME)
        final = os.path.join(store, first.record_name)
        original = os.fsync
        file_syncs = 0

        def track(fd: int) -> None:
            nonlocal file_syncs
            file_syncs += int(same_file(fd, final))
            original(fd)

        with patch.object(records_io.os, "fsync", side_effect=track):
            self.fixture.reobserve()
        self.assertEqual(file_syncs, 1)

    def test_record_name_rejects_noncanonical_attempt(self) -> None:
        with self.assertRaises(RuntimeError):
            records_io.fence_admission_reservation_record_name_v1("not-a-uuid")


if __name__ == "__main__":
    unittest.main(verbosity=2)
