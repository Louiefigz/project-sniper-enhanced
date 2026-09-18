"""Durability, replay, and concurrency tests for prospective enrollment."""

from __future__ import annotations

import dataclasses
import multiprocessing
import os
import tempfile
import unittest

from _common import pl  # noqa: F401
from _operation_admission_fixture import quality_operation
from _unit_enrollment_fixture import (
    EXPERIMENT_IDENTITY,
    OTHER_ENROLLMENT_KEY,
    enrollment_proposal,
)
from headless.unit_enrollment_binding import (
    build_prospective_unit_enrollment_v1,
)
from headless.unit_enrollment_store import (
    UnitEnrollmentKeyConflictV1,
    UnitEnrollmentStoreError,
    UnitEnrollmentUnitConflictV1,
    persist_or_replay_prospective_unit_enrollment_v1,
    reobserve_prospective_unit_enrollment_v1,
    require_durable_unit_enrollment_execution_authorized,
)
from headless.unit_enrollment_store_types import (
    DURABLE_UNIT_ENROLLMENT_STATUS,
    UnitEnrollmentReadRequestV1,
    UnitEnrollmentStoreRequestV1,
)


def _request(
    root: str, proposed: object = None
) -> UnitEnrollmentStoreRequestV1:
    operation = quality_operation()
    selected = proposed or enrollment_proposal(operation)
    return UnitEnrollmentStoreRequestV1(
        root, build_prospective_unit_enrollment_v1(selected)
    )


def _concurrent_enroll(
    root: str, queue: object, key: str | None = None
) -> None:
    try:
        proposed = (
            enrollment_proposal(quality_operation(), key) if key else None
        )
        result = persist_or_replay_prospective_unit_enrollment_v1(
            _request(root, proposed)
        )
        queue.put(("ok", result.created, result.record_id))
    except Exception as exc:  # pragma: no cover - returned to parent assertion
        queue.put(("error", type(exc).__name__, str(exc)))


class UnitEnrollmentStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.temporary.name)
        os.chmod(self.root, 0o700)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_create_exact_replay_and_read_reobserve_original(self) -> None:
        request = _request(self.root)
        created = persist_or_replay_prospective_unit_enrollment_v1(request)
        replayed = persist_or_replay_prospective_unit_enrollment_v1(request)
        read = reobserve_prospective_unit_enrollment_v1(
            UnitEnrollmentReadRequestV1(
                self.root,
                request.enrollment.authority_id,
                request.enrollment.enrollment_key,
            )
        )
        self.assertTrue(created.created)
        self.assertFalse(replayed.created)
        self.assertFalse(read.created)
        self.assertEqual(
            {created.record_id, replayed.record_id, read.record_id},
            {created.record_id},
        )
        self.assertEqual(read.status, DURABLE_UNIT_ENROLLMENT_STATUS)
        self.assertTrue(read.enrollment_bytes_reobserved)
        self.assertTrue(read.replay_arbitrated)
        self.assertTrue(read.global_unit_uniqueness_verified)
        self.assertFalse(read.operation_admission_bound)
        self.assertFalse(read.execution_authorized)
        self.assertFalse(read.publication_authorized)
        for value in (
            read,
            dataclasses.replace(read, execution_authorized=True),
        ):
            with self.assertRaises(UnitEnrollmentStoreError):
                require_durable_unit_enrollment_execution_authorized(value)

    def test_store_retains_exact_private_enrollment_bytes(self) -> None:
        request = _request(self.root)
        result = persist_or_replay_prospective_unit_enrollment_v1(request)
        directory = os.path.join(
            self.root, "unit-enrollments-v1", result.record_id
        )
        path = os.path.join(directory, "enrollment.json")
        with open(path, "rb") as handle:
            self.assertEqual(
                handle.read(), request.enrollment.document_json
            )
        self.assertEqual(os.stat(directory).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_same_key_changed_identity_and_duplicate_unit_conflict(
        self,
    ) -> None:
        first = _request(self.root)
        persist_or_replay_prospective_unit_enrollment_v1(first)
        changed_project = dataclasses.replace(
            enrollment_proposal(quality_operation()),
            project=dataclasses.replace(
                enrollment_proposal(quality_operation()).project,
                experiment_identity_digest="4" * 64,
            ),
        )
        with self.assertRaises(UnitEnrollmentKeyConflictV1):
            persist_or_replay_prospective_unit_enrollment_v1(
                _request(self.root, changed_project)
            )
        duplicate_unit = enrollment_proposal(
            quality_operation(), OTHER_ENROLLMENT_KEY
        )
        with self.assertRaises(UnitEnrollmentUnitConflictV1):
            persist_or_replay_prospective_unit_enrollment_v1(
                _request(self.root, duplicate_unit)
            )
        self.assertEqual(
            first.enrollment.project.experiment_identity_digest,
            EXPERIMENT_IDENTITY,
        )

    def test_concurrent_exact_submissions_create_one_record(self) -> None:
        context = multiprocessing.get_context("fork")
        queue = context.Queue()
        workers = [
            context.Process(target=_concurrent_enroll, args=(self.root, queue))
            for _index in range(6)
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(10)
            self.assertEqual(worker.exitcode, 0)
        outcomes = [queue.get(timeout=2) for _index in workers]
        self.assertTrue(all(row[0] == "ok" for row in outcomes), outcomes)
        self.assertEqual(sum(row[1] for row in outcomes), 1)
        self.assertEqual(len({row[2] for row in outcomes}), 1)

    def test_concurrent_distinct_keys_cannot_duplicate_global_unit(
        self,
    ) -> None:
        context = multiprocessing.get_context("fork")
        queue = context.Queue()
        workers = [
            context.Process(
                target=_concurrent_enroll,
                args=(self.root, queue, key),
            )
            for key in (
                "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
                OTHER_ENROLLMENT_KEY,
            )
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(10)
            self.assertEqual(worker.exitcode, 0)
        outcomes = [queue.get(timeout=2) for _index in workers]
        self.assertEqual(sorted(row[0] for row in outcomes), ["error", "ok"])
        self.assertIn(
            "UnitEnrollmentUnitConflictV1", {row[1] for row in outcomes}
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
