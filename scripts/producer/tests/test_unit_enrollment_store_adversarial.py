"""Filesystem and authority attacks against prospective unit enrollment."""

from __future__ import annotations

import dataclasses
import json
import multiprocessing
import os
import shutil
import tempfile
import unittest

from _common import pl  # noqa: F401
from _operation_admission_fixture import quality_operation
from _unit_enrollment_fixture import OTHER_ENROLLMENT_KEY, enrollment_proposal
from test_unit_enrollment_store import _request
from headless.unit_enrollment_store import (
    UnitEnrollmentStoreError,
    persist_or_replay_prospective_unit_enrollment_v1,
    reobserve_prospective_unit_enrollment_v1,
)
from headless.unit_enrollment_store_types import UnitEnrollmentReadRequestV1
from headless import unit_enrollment_store as enrollment_store_module


class _AlwaysEqual(str):
    def __eq__(self, other: object) -> bool:
        return True

    def __ne__(self, other: object) -> bool:
        return False

    __hash__ = str.__hash__


def _concurrent_authority(root: str, authority_id: str, queue: object) -> None:
    proposed = dataclasses.replace(
        enrollment_proposal(quality_operation()), authority_id=authority_id
    )
    try:
        persist_or_replay_prospective_unit_enrollment_v1(
            _request(root, proposed)
        )
        queue.put((authority_id, "ok"))
    except Exception as exc:  # pragma: no cover - returned to parent assertion
        queue.put((authority_id, type(exc).__name__))


class UnitEnrollmentStoreAdversarialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.temporary.name)
        os.chmod(self.root, 0o700)
        self.request = _request(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _create(self) -> tuple[object, str, str]:
        result = persist_or_replay_prospective_unit_enrollment_v1(self.request)
        store = os.path.join(self.root, "unit-enrollments-v1")
        return result, store, os.path.join(store, result.record_id)

    def _read_request(self) -> UnitEnrollmentReadRequestV1:
        return UnitEnrollmentReadRequestV1(
            self.root,
            self.request.enrollment.authority_id,
            self.request.enrollment.enrollment_key,
        )

    def test_unknown_and_torn_store_entries_fail_closed(self) -> None:
        result, store, _record = self._create()
        names = ("unexpected", f".pending-{result.record_id}-torn")
        for name in names:
            path = os.path.join(store, name)
            os.mkdir(path, 0o700)
            with self.subTest(name=name), self.assertRaises(
                UnitEnrollmentStoreError
            ):
                reobserve_prospective_unit_enrollment_v1(self._read_request())
            os.rmdir(path)

    def test_valid_looking_entry_flood_hits_bounded_store_limit(self) -> None:
        _result, store, _record = self._create()
        names = set(os.listdir(store))
        index = 0
        target = enrollment_store_module._MAX_ENROLLMENT_RECORDS + 1
        while len(names) < target:
            name = f"{index:064x}"
            index += 1
            if name in names:
                continue
            os.mkdir(os.path.join(store, name), 0o700)
            names.add(name)
        with self.assertRaisesRegex(UnitEnrollmentStoreError, "record limit"):
            reobserve_prospective_unit_enrollment_v1(self._read_request())

    def test_unknown_record_members_and_byte_mutation_fail_closed(
        self,
    ) -> None:
        _result, _store, record = self._create()
        unexpected = os.path.join(record, "outcome.json")
        with open(unexpected, "wb") as handle:
            handle.write(b"{}")
        os.chmod(unexpected, 0o600)
        with self.assertRaises(UnitEnrollmentStoreError):
            reobserve_prospective_unit_enrollment_v1(self._read_request())
        os.unlink(unexpected)
        enrollment_path = os.path.join(record, "enrollment.json")
        with open(enrollment_path, "rb") as handle:
            document = json.loads(handle.read())
        document["enrollmentClock"]["sequence"] += 1
        with open(enrollment_path, "wb") as handle:
            handle.write(
                json.dumps(
                    document,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("ascii")
            )
        with self.assertRaises(UnitEnrollmentStoreError):
            reobserve_prospective_unit_enrollment_v1(self._read_request())

    def test_unsafe_modes_hardlinks_and_symlinks_fail_closed(self) -> None:
        _result, _store, record = self._create()
        enrollment_path = os.path.join(record, "enrollment.json")
        os.chmod(enrollment_path, 0o644)
        with self.assertRaises(UnitEnrollmentStoreError):
            reobserve_prospective_unit_enrollment_v1(self._read_request())
        os.chmod(enrollment_path, 0o600)
        with open(enrollment_path, "rb") as handle:
            raw = handle.read()
        with tempfile.NamedTemporaryFile() as external:
            external.write(raw)
            external.flush()
            os.chmod(external.name, 0o600)
            os.unlink(enrollment_path)
            os.link(external.name, enrollment_path)
            with self.assertRaises(UnitEnrollmentStoreError):
                reobserve_prospective_unit_enrollment_v1(self._read_request())

    def test_retained_set_duplicate_unit_is_rejected_on_replay(self) -> None:
        self._create()
        with tempfile.TemporaryDirectory() as source:
            source_root = os.path.realpath(source)
            os.chmod(source_root, 0o700)
            proposed = enrollment_proposal(
                quality_operation(), OTHER_ENROLLMENT_KEY
            )
            request = _request(source_root, proposed)
            result = persist_or_replay_prospective_unit_enrollment_v1(request)
            source_record = os.path.join(
                source_root, "unit-enrollments-v1", result.record_id
            )
            target = os.path.join(
                self.root, "unit-enrollments-v1", result.record_id
            )
            shutil.copytree(source_record, target)
        with self.assertRaisesRegex(UnitEnrollmentStoreError, "duplicates"):
            reobserve_prospective_unit_enrollment_v1(self._read_request())

    def test_cross_authority_adoption_and_orphan_state_are_rejected(
        self,
    ) -> None:
        other = dataclasses.replace(
            enrollment_proposal(quality_operation()),
            authority_id="authority-other",
        )
        persist_or_replay_prospective_unit_enrollment_v1(
            _request(self.root, other)
        )
        with self.assertRaisesRegex(UnitEnrollmentStoreError, "authority"):
            persist_or_replay_prospective_unit_enrollment_v1(self.request)

        with tempfile.TemporaryDirectory() as orphan:
            orphan_root = os.path.realpath(orphan)
            os.chmod(orphan_root, 0o700)
            os.mkdir(os.path.join(orphan_root, "unit-enrollments-v1"), 0o700)
            with self.assertRaisesRegex(UnitEnrollmentStoreError, "authority"):
                persist_or_replay_prospective_unit_enrollment_v1(
                    _request(orphan_root)
                )
            self.assertFalse(
                os.path.exists(os.path.join(orphan_root, "authority.json"))
            )

    def test_missing_read_is_noncreating_and_hostile_equality_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(UnitEnrollmentStoreError):
            reobserve_prospective_unit_enrollment_v1(self._read_request())
        self.assertEqual(os.listdir(self.root), [])
        self._create()
        hostile = dataclasses.replace(
            self._read_request(), authority_id=_AlwaysEqual("authority-other")
        )
        with self.assertRaises(UnitEnrollmentStoreError):
            reobserve_prospective_unit_enrollment_v1(hostile)

    def test_unsafe_never_unlinked_lock_inode_is_rejected(self) -> None:
        lock_path = os.path.join(self.root, ".unit-enrollment-v1.lock")
        os.symlink("/dev/null", lock_path)
        with self.assertRaises(UnitEnrollmentStoreError):
            persist_or_replay_prospective_unit_enrollment_v1(self.request)
        self.assertFalse(
            os.path.exists(os.path.join(self.root, "authority.json"))
        )

    def test_concurrent_cross_authority_initialization_has_one_winner(
        self,
    ) -> None:
        context = multiprocessing.get_context("fork")
        queue = context.Queue()
        workers = [
            context.Process(
                target=_concurrent_authority,
                args=(self.root, authority, queue),
            )
            for authority in ("authority-mp4-v1", "authority-other")
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(10)
            self.assertEqual(worker.exitcode, 0)
        outcomes = [queue.get(timeout=2) for _index in workers]
        self.assertEqual(
            sorted(status for _authority, status in outcomes),
            [
                "UnitEnrollmentStoreError",
                "ok",
            ],
        )
        with open(
            os.path.join(self.root, "authority.json"), encoding="ascii"
        ) as handle:
            retained = json.load(handle)
        winner = next(
            authority for authority, status in outcomes if status == "ok"
        )
        self.assertEqual(retained["authorityId"], winner)


if __name__ == "__main__":
    unittest.main(verbosity=2)
