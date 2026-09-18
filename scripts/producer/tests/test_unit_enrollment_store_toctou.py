"""TOCTOU, resource, and crash attacks on unit-enrollment storage."""

from __future__ import annotations

import contextlib
import dataclasses
import json
import os
import shutil
import tempfile
import unittest
import uuid
from unittest import mock

from _common import pl  # noqa: F401
from _operation_admission_fixture import quality_operation
from _unit_enrollment_fixture import enrollment_proposal
from headless import unit_enrollment_store as store_module
from headless import unit_enrollment_store_snapshot as snapshot_module
from headless.unit_enrollment_binding import (
    build_prospective_unit_enrollment_v1,
)
from headless.unit_enrollment_store import (
    UnitEnrollmentStoreError,
    persist_or_replay_prospective_unit_enrollment_v1,
    reobserve_prospective_unit_enrollment_v1,
)
from headless.unit_enrollment_store_types import (
    UnitEnrollmentReadRequestV1,
    UnitEnrollmentStoreRequestV1,
)


class _AlwaysEqual(str):
    def __eq__(self, other: object) -> bool:
        return True

    def __ne__(self, other: object) -> bool:
        return False

    __hash__ = str.__hash__


class UnitEnrollmentStoreToctouTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = os.path.realpath(self.temporary.name)
        os.chmod(self.root, 0o700)
        self.first = self._persist(1)

    def _proposal(self, index: int):
        base = enrollment_proposal(quality_operation())
        return dataclasses.replace(
            base,
            enrollment_key=str(uuid.UUID(int=1000 + index)),
            unit_id=str(uuid.UUID(int=10_000 + index)),
        )

    def _persist(self, index: int):
        enrollment = build_prospective_unit_enrollment_v1(
            self._proposal(index)
        )
        return persist_or_replay_prospective_unit_enrollment_v1(
            UnitEnrollmentStoreRequestV1(self.root, enrollment)
        )

    def _read(self) -> UnitEnrollmentReadRequestV1:
        enrollment = self.first.structural_binding.enrollment
        return UnitEnrollmentReadRequestV1(
            self.root, enrollment.authority_id, enrollment.enrollment_key
        )

    def _record(self, record_id: str) -> str:
        return os.path.join(self.root, "unit-enrollments-v1", record_id)

    def test_late_record_after_name_scan_invalidates_global_uniqueness(
        self,
    ) -> None:
        source = tempfile.TemporaryDirectory()
        self.addCleanup(source.cleanup)
        source_root = os.path.realpath(source.name)
        os.chmod(source_root, 0o700)
        enrollment = build_prospective_unit_enrollment_v1(self._proposal(2))
        created = persist_or_replay_prospective_unit_enrollment_v1(
            UnitEnrollmentStoreRequestV1(source_root, enrollment)
        )
        source_record = os.path.join(
            source_root, "unit-enrollments-v1", created.record_id
        )
        target_record = self._record(created.record_id)
        original = store_module.pinned_unit_enrollment_set

        @contextlib.contextmanager
        def attacked(store_fd: int, names: tuple[str, ...], limit: int):
            with original(store_fd, names, limit) as rows:
                shutil.copytree(source_record, target_record)
                yield rows

        with mock.patch.object(
            store_module, "pinned_unit_enrollment_set", attacked
        ), self.assertRaises(UnitEnrollmentStoreError):
            reobserve_prospective_unit_enrollment_v1(self._read())

    def test_earlier_row_same_inode_mutation_is_caught_after_later_row(
        self,
    ) -> None:
        self._persist(2)
        store = os.path.join(self.root, "unit-enrollments-v1")
        first_name = sorted(os.listdir(store))[0]
        target = os.path.join(store, first_name, "enrollment.json")
        original = snapshot_module._open_snapshot
        calls = 0

        def attacked(store_fd: int, name: str, limit: int):
            nonlocal calls
            result = original(store_fd, name, limit)
            calls += 1
            if calls == 2:
                with open(target, "ab") as handle:
                    handle.write(b" ")
            return result

        with mock.patch.object(
            snapshot_module, "_open_snapshot", side_effect=attacked
        ), self.assertRaises(UnitEnrollmentStoreError):
            reobserve_prospective_unit_enrollment_v1(self._read())

    def test_late_member_and_identical_byte_replacement_are_caught(
        self,
    ) -> None:
        record = self._record(self.first.record_id)
        enrollment_path = os.path.join(record, "enrollment.json")
        original = snapshot_module._open_snapshot
        attacks = ("member", "replacement")
        for attack in attacks:
            calls = 0

            def attacked(store_fd: int, name: str, limit: int):
                nonlocal calls
                result = original(store_fd, name, limit)
                calls += 1
                if calls != 1:
                    return result
                if attack == "member":
                    path = os.path.join(record, "outcome.json")
                    with open(path, "wb") as handle:
                        handle.write(b"{}")
                    os.chmod(path, 0o600)
                else:
                    replacement = os.path.join(self.root, "replacement.json")
                    shutil.copyfile(enrollment_path, replacement)
                    os.chmod(replacement, 0o600)
                    os.replace(replacement, enrollment_path)
                return result

            with self.subTest(attack=attack), mock.patch.object(
                snapshot_module, "_open_snapshot", side_effect=attacked
            ), self.assertRaises(UnitEnrollmentStoreError):
                reobserve_prospective_unit_enrollment_v1(self._read())
            if attack == "member":
                os.unlink(os.path.join(record, "outcome.json"))

    def test_store_directory_replacement_is_caught_before_return(self) -> None:
        store = os.path.join(self.root, "unit-enrollments-v1")
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        archived = os.path.join(outside.name, "old-store")
        original = store_module.pinned_unit_enrollment_set

        @contextlib.contextmanager
        def attacked(store_fd: int, names: tuple[str, ...], limit: int):
            with original(store_fd, names, limit) as rows:
                yield rows
            os.rename(store, archived)
            shutil.copytree(archived, store)

        with mock.patch.object(
            store_module, "pinned_unit_enrollment_set", attacked
        ), self.assertRaises(UnitEnrollmentStoreError):
            reobserve_prospective_unit_enrollment_v1(self._read())

    def test_snapshot_file_descriptor_budget_is_constant(self) -> None:
        for index in range(2, 14):
            self._persist(index)
        active: set[int] = set()
        peak = 0
        real_child = snapshot_module.open_private_child_dir
        real_file = snapshot_module.open_private_file
        real_close = os.close

        def tracked(open_function):
            def opened(*args: object, **kwargs: object) -> int:
                nonlocal peak
                descriptor = open_function(*args, **kwargs)
                active.add(descriptor)
                peak = max(peak, len(active))
                return descriptor

            return opened

        def closed(descriptor: int) -> None:
            active.discard(descriptor)
            real_close(descriptor)

        with mock.patch.object(
            snapshot_module, "open_private_child_dir", tracked(real_child)
        ), mock.patch.object(
            snapshot_module, "open_private_file", tracked(real_file)
        ), mock.patch.object(
            snapshot_module.os, "close", side_effect=closed
        ):
            reobserve_prospective_unit_enrollment_v1(self._read())
        self.assertEqual(active, set())
        self.assertLessEqual(
            peak, snapshot_module.UNIT_ENROLLMENT_SNAPSHOT_FD_BUDGET
        )

    def test_lock_replacement_and_hostile_root_type_fail_closed(self) -> None:
        original = store_module._load_all

        def replaced_lock(store_fd: int, authority_id: str):
            rows = original(store_fd, authority_id)
            path = os.path.join(self.root, ".unit-enrollment-v1.lock")
            os.unlink(path)
            with open(path, "wb"):
                pass
            os.chmod(path, 0o600)
            return rows

        with mock.patch.object(
            store_module, "_load_all", side_effect=replaced_lock
        ), self.assertRaises(UnitEnrollmentStoreError):
            reobserve_prospective_unit_enrollment_v1(self._read())
        hostile = dataclasses.replace(
            self._read(),
            authority_root=_AlwaysEqual(
                os.path.join(self.root, "..", os.path.basename(self.root))
            ),
        )
        with self.assertRaises(UnitEnrollmentStoreError):
            reobserve_prospective_unit_enrollment_v1(hostile)

    def test_late_authority_byte_change_is_caught_before_return(self) -> None:
        original = store_module._load_all

        def changed_authority(store_fd: int, authority_id: str):
            rows = original(store_fd, authority_id)
            path = os.path.join(self.root, "authority.json")
            raw = json.dumps(
                {"authorityId": "authority-other", "schemaVersion": 1},
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
            with open(path, "w", encoding="ascii") as handle:
                handle.write(raw + "\n")
            return rows

        with mock.patch.object(
            store_module, "_load_all", side_effect=changed_authority
        ), self.assertRaises(UnitEnrollmentStoreError):
            reobserve_prospective_unit_enrollment_v1(self._read())


if __name__ == "__main__":
    unittest.main(verbosity=2)
