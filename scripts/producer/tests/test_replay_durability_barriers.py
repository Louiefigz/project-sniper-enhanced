"""Crash ambiguity tests for final-record durability recovery barriers."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from collections.abc import Callable
from unittest import mock

from _common import pl  # noqa: F401
from test_operation_admission_v3_store import _request as admission_request
from test_unit_enrollment_store import _request as enrollment_request
from headless import operation_admission_recovery as admission_recovery
from headless import operation_admission_store_persistence as admission_writer
from headless import unit_enrollment_durability as enrollment_durability
from headless import unit_enrollment_store as enrollment_store
from headless.operation_admission_store import (
    OperationAdmissionStoreError,
    persist_or_replay_operation_admission_v3,
)
from headless.operation_admission_store_reader import (
    operation_admission_record_name_v3,
)
from headless.unit_enrollment_store import (
    UnitEnrollmentStoreError,
    persist_or_replay_prospective_unit_enrollment_v1,
    reobserve_prospective_unit_enrollment_v1,
)
from headless.unit_enrollment_record import unit_enrollment_record_name_v1
from headless.unit_enrollment_store_types import (
    UnitEnrollmentReadRequestV1,
    UnitEnrollmentStoreRequestV1,
)


def _same_file(fd: int, path: str) -> bool:
    try:
        held = os.fstat(fd)
        named = os.stat(path, follow_symlinks=False)
    except OSError:
        return False
    return (held.st_dev, held.st_ino) == (named.st_dev, named.st_ino)


def _fail_once_after_visible(
    store: str, final: str, real_fsync: Callable[[int], None]
) -> tuple[Callable[[int], None], list[bool]]:
    failed = [False]

    def injected(fd: int) -> None:
        final_visible = os.path.exists(final)
        if not failed[0] and final_visible and _same_file(fd, store):
            failed[0] = True
            raise OSError("simulated parent fsync failure")
        real_fsync(fd)

    return injected, failed


def _tracking_fsync(
    store: str, real_fsync: Callable[[int], None]
) -> tuple[Callable[[int], None], list[int]]:
    calls: list[int] = []

    def tracked(fd: int) -> None:
        if _same_file(fd, store):
            calls.append(fd)
        real_fsync(fd)

    return tracked, calls


class ReplayDurabilityBarrierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = os.path.realpath(self.temporary.name)
        os.chmod(self.root, 0o700)

    def test_operation_replay_refsyncs_final_record_parent(self) -> None:
        request = admission_request(self.root)
        store = os.path.join(self.root, "operation-admissions-v3")
        name = operation_admission_record_name_v3(
            request.admission.idempotency_key
        )
        final = os.path.join(store, name)
        real_fsync = os.fsync
        injected, failed = _fail_once_after_visible(store, final, real_fsync)
        with mock.patch.object(admission_writer.os, "fsync", injected):
            with self.assertRaises(OperationAdmissionStoreError):
                persist_or_replay_operation_admission_v3(request)
        self.assertEqual(failed, [True])
        tracked, calls = _tracking_fsync(store, real_fsync)
        with mock.patch.object(admission_writer.os, "fsync", tracked):
            replayed = persist_or_replay_operation_admission_v3(request)
        self.assertFalse(replayed.created)
        self.assertGreaterEqual(len(calls), 1)

    def test_operation_replay_rejects_record_directory_swap(self) -> None:
        request = admission_request(self.root)
        created = persist_or_replay_operation_admission_v3(request)
        store = os.path.join(self.root, "operation-admissions-v3")
        final = os.path.join(store, created.record_id)
        archived = os.path.join(self.root, "archived-admission")
        original = admission_writer.assert_named_private_directory_identity
        calls = 0

        def attacked(parent_fd: int, name: str, child_fd: int) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                os.rename(final, archived)
                shutil.copytree(archived, final)
            original(parent_fd, name, child_fd)

        with mock.patch.object(
            admission_writer,
            "assert_named_private_directory_identity",
            side_effect=attacked,
        ), self.assertRaises(OperationAdmissionStoreError):
            persist_or_replay_operation_admission_v3(request)

    def test_operation_replay_rejects_swap_during_named_reload(self) -> None:
        request = admission_request(self.root)
        created = persist_or_replay_operation_admission_v3(request)
        store = os.path.join(self.root, "operation-admissions-v3")
        final = os.path.join(store, created.record_id)
        archived = os.path.join(self.root, "reload-archived-admission")
        original = admission_recovery.load_operation_admission_record_v3
        swapped = False

        def attacked(store_fd: int, name: str) -> object:
            nonlocal swapped
            if not swapped:
                swapped = True
                os.rename(final, archived)
                shutil.copytree(archived, final)
            return original(store_fd, name)

        with mock.patch.object(
            admission_recovery,
            "load_operation_admission_record_v3",
            side_effect=attacked,
        ), self.assertRaises(OperationAdmissionStoreError):
            persist_or_replay_operation_admission_v3(request)
        self.assertTrue(swapped)

    def _leave_visible_enrollment_after_fsync_error(
        self,
    ) -> tuple[UnitEnrollmentStoreRequestV1, str, Callable[[int], None]]:
        request = enrollment_request(self.root)
        store = os.path.join(self.root, "unit-enrollments-v1")
        name = unit_enrollment_record_name_v1(
            request.enrollment.enrollment_key
        )
        final = os.path.join(store, name)
        real_fsync = os.fsync
        injected, failed = _fail_once_after_visible(store, final, real_fsync)
        with mock.patch.object(enrollment_store.os, "fsync", injected):
            with self.assertRaises(UnitEnrollmentStoreError):
                persist_or_replay_prospective_unit_enrollment_v1(request)
        self.assertEqual(failed, [True])
        return request, store, real_fsync

    def test_unit_replay_refsyncs_final_record_parent(self) -> None:
        request, store, real_fsync = (
            self._leave_visible_enrollment_after_fsync_error()
        )
        tracked, calls = _tracking_fsync(store, real_fsync)
        with mock.patch.object(enrollment_durability.os, "fsync", tracked):
            replayed = persist_or_replay_prospective_unit_enrollment_v1(
                request
            )
        self.assertFalse(replayed.created)
        self.assertGreaterEqual(len(calls), 1)

    def test_unit_replay_rejects_record_directory_swap(self) -> None:
        request = enrollment_request(self.root)
        created = persist_or_replay_prospective_unit_enrollment_v1(request)
        store = os.path.join(self.root, "unit-enrollments-v1")
        final = os.path.join(store, created.record_id)
        archived = os.path.join(self.root, "archived-enrollment")
        original = (
            enrollment_durability.assert_named_private_directory_identity
        )
        calls = 0

        def attacked(parent_fd: int, name: str, child_fd: int) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                os.rename(final, archived)
                shutil.copytree(archived, final)
            original(parent_fd, name, child_fd)

        with mock.patch.object(
            enrollment_durability,
            "assert_named_private_directory_identity",
            side_effect=attacked,
        ), self.assertRaises(UnitEnrollmentStoreError):
            persist_or_replay_prospective_unit_enrollment_v1(request)

    def test_unit_replay_rejects_swap_during_named_reload(self) -> None:
        request = enrollment_request(self.root)
        created = persist_or_replay_prospective_unit_enrollment_v1(request)
        store = os.path.join(self.root, "unit-enrollments-v1")
        final = os.path.join(store, created.record_id)
        archived = os.path.join(self.root, "reload-archived-enrollment")
        original = enrollment_store._load_all
        calls = 0

        def attacked(store_fd: int, authority_id: str) -> object:
            nonlocal calls
            calls += 1
            if calls == 2:
                os.rename(final, archived)
                shutil.copytree(archived, final)
            return original(store_fd, authority_id)

        with mock.patch.object(
            enrollment_store, "_load_all", side_effect=attacked
        ), self.assertRaises(UnitEnrollmentStoreError):
            persist_or_replay_prospective_unit_enrollment_v1(request)
        self.assertEqual(calls, 2)

    def test_unit_read_refsyncs_visible_final_before_return(self) -> None:
        request, store, real_fsync = (
            self._leave_visible_enrollment_after_fsync_error()
        )
        read = UnitEnrollmentReadRequestV1(
            self.root,
            request.enrollment.authority_id,
            request.enrollment.enrollment_key,
        )
        tracked, calls = _tracking_fsync(store, real_fsync)
        with mock.patch.object(enrollment_durability.os, "fsync", tracked):
            observed = reobserve_prospective_unit_enrollment_v1(read)
        self.assertFalse(observed.created)
        self.assertGreaterEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
