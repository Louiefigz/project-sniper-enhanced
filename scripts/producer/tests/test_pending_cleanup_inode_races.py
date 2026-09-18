"""Adversarial inode-swap tests for writer-only pending cleanup."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from _common import pl  # noqa: F401
from _cross_ledger_order_fixture import CrossLedgerOrderFixture
from _operation_admission_fixture import quality_operation
from _unit_enrollment_fixture import enrollment, enrollment_proposal
from headless import cross_ledger_order_store_write as order_writer
from headless import operation_admission_store_persistence as admission_writer
from headless import pending_cleanup_fs as cleanup
from headless import unit_enrollment_store as enrollment_writer
from headless.cross_ledger_order_types import CrossLedgerOrderError
from headless.operation_admission_store import (
    OperationAdmissionStoreError,
    persist_or_replay_operation_admission_v3,
)
from headless.unit_enrollment_store import (
    UnitEnrollmentStoreError,
    persist_or_replay_prospective_unit_enrollment_v1,
)
from headless.unit_enrollment_store_types import UnitEnrollmentStoreRequestV1

_REPLACEMENT = b"conflicting-replacement-must-survive"


def _fail_pending_rename(src: str, dst: str, **kwargs: object) -> None:
    if src.startswith(".pending-"):
        raise OSError("simulated crash before pending rename")
    os.rename(src, dst, **kwargs)


def _only_pending(store: str) -> str:
    names = os.listdir(store)
    if len(names) != 1 or not names[0].startswith(".pending-"):
        raise AssertionError("test fixture did not retain one pending record")
    return os.path.join(store, names[0])


def _read(path: str) -> bytes:
    with open(path, "rb") as source:
        return source.read()


class _ReplacementRace:
    def __init__(self, target: str) -> None:
        self.target = target
        self.triggered = False
        self.target_checks = 0
        self.original = cleanup._assert_named_unlink_target

    def __call__(self, *args: object) -> None:
        parent_fd, name, fd, baseline = args
        if (
            type(parent_fd) is not int
            or type(name) is not str
            or type(fd) is not int
            or type(baseline) is not os.stat_result
        ):
            raise AssertionError("pending unlink seam arguments are invalid")
        if name == self.target:
            self.target_checks += 1
        if self.target_checks == 2 and not self.triggered:
            self.triggered = True
            displaced = f".validated-{name}"
            os.rename(
                name,
                displaced,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            replacement_fd = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=parent_fd,
            )
            try:
                os.fchmod(replacement_fd, 0o600)
                os.write(replacement_fd, _REPLACEMENT)
            finally:
                os.close(replacement_fd)
        self.original(parent_fd, name, fd, baseline)


def _assert_replacement_survived(
    case: unittest.TestCase, race: _ReplacementRace, path: str
) -> None:
    case.assertTrue(race.triggered)
    case.assertEqual(_read(path), _REPLACEMENT)


class PendingCleanupInodeRaceTests(unittest.TestCase):
    def test_cross_ledger_replacement_survives_validation_unlink_race(
        self,
    ) -> None:
        fixture = CrossLedgerOrderFixture()
        self.addCleanup(fixture.close)
        with patch.object(
            order_writer.os, "rename", side_effect=_fail_pending_rename
        ), self.assertRaises(CrossLedgerOrderError):
            fixture.persist()
        store = os.path.join(fixture.root, order_writer.STORE_NAME)
        pending = _only_pending(store)
        path = os.path.join(pending, order_writer.INTENT_NAME)
        race = _ReplacementRace(order_writer.INTENT_NAME)
        with patch.object(
            cleanup, "_assert_named_unlink_target", side_effect=race
        ), self.assertRaises(CrossLedgerOrderError):
            fixture.persist()
        _assert_replacement_survived(self, race, path)

    def test_unit_replacement_survives_validation_unlink_race(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = os.path.realpath(temporary.name)
        os.chmod(root, 0o700)
        operation = quality_operation()
        proposed = enrollment_proposal(operation)
        request = UnitEnrollmentStoreRequestV1(
            root, enrollment(operation, proposed)
        )
        with patch.object(
            enrollment_writer.os,
            "rename",
            side_effect=_fail_pending_rename,
        ), self.assertRaises(UnitEnrollmentStoreError):
            persist_or_replay_prospective_unit_enrollment_v1(request)
        pending = _only_pending(os.path.join(root, "unit-enrollments-v1"))
        path = os.path.join(pending, "enrollment.json")
        race = _ReplacementRace("enrollment.json")
        with patch.object(
            cleanup, "_assert_named_unlink_target", side_effect=race
        ), self.assertRaises(UnitEnrollmentStoreError):
            persist_or_replay_prospective_unit_enrollment_v1(request)
        _assert_replacement_survived(self, race, path)

    def test_operation_replacement_survives_validation_unlink_race(
        self,
    ) -> None:
        fixture = CrossLedgerOrderFixture()
        self.addCleanup(fixture.close)
        request = fixture.request().admission
        with patch.object(
            admission_writer.os,
            "rename",
            side_effect=_fail_pending_rename,
        ), self.assertRaises(OperationAdmissionStoreError):
            persist_or_replay_operation_admission_v3(request)
        store = os.path.join(fixture.root, "operation-admissions-v3")
        pending = _only_pending(store)
        path = os.path.join(pending, "admission.json")
        race = _ReplacementRace("admission.json")
        with patch.object(
            cleanup, "_assert_named_unlink_target", side_effect=race
        ), self.assertRaises(OperationAdmissionStoreError):
            persist_or_replay_operation_admission_v3(request)
        _assert_replacement_survived(self, race, path)

    def test_missing_unlink_transition_is_rejected(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = os.path.realpath(temporary.name)
        os.chmod(root, 0o700)
        path = os.path.join(root, "pending.json")
        with open(path, "wb") as output:
            output.write(b"pending")
        os.chmod(path, 0o600)
        parent_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, parent_fd)
        with patch.object(cleanup.os, "unlink", return_value=None):
            with self.assertRaises(cleanup.PendingCleanupFileError):
                cleanup.remove_private_pending_file(
                    parent_fd, "pending.json", 128
                )
        self.assertEqual(_read(path), b"pending")


if __name__ == "__main__":
    unittest.main(verbosity=2)
