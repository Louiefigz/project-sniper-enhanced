"""Durability and exact replay tests for the V3 operation-admission store."""

from __future__ import annotations

import dataclasses
import multiprocessing
import os
import tempfile
import unittest
from pathlib import Path

from _common import pl  # noqa: F401
from _operation_admission_fixture import proposal, quality_operation
from headless.operation_admission_binding import build_operation_admission_v3
from headless.operation_admission_store import (
    OperationAdmissionAttemptConflictV3,
    OperationAdmissionChildConflictV3,
    OperationAdmissionIdempotencyConflictV3,
    OperationAdmissionStoreError,
    persist_or_replay_operation_admission_v3,
    require_durable_operation_admission_execution_authorized,
)
from headless.operation_admission_store_types import (
    DURABLE_OPERATION_ADMISSION_STATUS,
    OperationAdmissionStoreRequestV3,
)

OTHER_KEY = "88888888-8888-4888-8888-888888888888"
OTHER_CHILD = "99999999-9999-4999-8999-999999999999"
THIRD_KEY = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OTHER_ATTEMPT = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def _request(
    root: str, proposed: object = None
) -> OperationAdmissionStoreRequestV3:
    operation = quality_operation()
    selected = proposed or proposal(operation)
    value = build_operation_admission_v3(
        operation, selected, "operations/headless-mp4-operation.json"
    )
    return OperationAdmissionStoreRequestV3(root, operation, value, selected)


def _concurrent_admit(root: str, queue: object) -> None:
    try:
        result = persist_or_replay_operation_admission_v3(_request(root))
        queue.put(("ok", result.created, result.record_id))
    except (
        Exception
    ) as exc:  # pragma: no cover - returned to the parent assertion
        queue.put(("error", type(exc).__name__, str(exc)))


class OperationAdmissionV3StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.temporary.name)
        os.chmod(self.root, 0o700)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_create_then_exact_replay_returns_original_durable_record(
        self,
    ) -> None:
        request = _request(self.root)
        created = persist_or_replay_operation_admission_v3(request)
        replayed = persist_or_replay_operation_admission_v3(request)
        self.assertTrue(created.created)
        self.assertFalse(replayed.created)
        self.assertEqual(created.record_id, replayed.record_id)
        self.assertEqual(created.status, DURABLE_OPERATION_ADMISSION_STATUS)
        self.assertTrue(replayed.durable_admission_bytes_reobserved)
        self.assertTrue(replayed.durable_operation_bytes_reobserved)
        self.assertTrue(replayed.replay_arbitrated)
        self.assertFalse(replayed.unit_enrollment_verified)
        self.assertFalse(replayed.execution_authorized)
        self.assertFalse(replayed.publication_authorized)
        with self.assertRaises(OperationAdmissionStoreError):
            require_durable_operation_admission_execution_authorized(replayed)
        forged = dataclasses.replace(replayed, execution_authorized=True)
        with self.assertRaises(OperationAdmissionStoreError):
            require_durable_operation_admission_execution_authorized(forged)

    def test_store_retains_exact_admission_and_nested_operation_bytes(
        self,
    ) -> None:
        request = _request(self.root)
        result = persist_or_replay_operation_admission_v3(request)
        directory = os.path.join(
            self.root, "operation-admissions-v3", result.record_id
        )
        admission_path = os.path.join(directory, "admission.json")
        operation_path = os.path.join(
            directory,
            "artifacts",
            request.admission.operation.artifact.relative_path,
        )
        self.assertEqual(
            Path(admission_path).read_bytes(),
            request.admission.document_json,
        )
        self.assertEqual(
            Path(operation_path).read_bytes(),
            request.operation.document_json,
        )
        self.assertEqual(os.stat(directory).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(admission_path).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(operation_path).st_mode & 0o777, 0o600)

    def test_same_key_with_changed_exact_identity_conflicts(self) -> None:
        first = _request(self.root)
        persist_or_replay_operation_admission_v3(first)
        changed = dataclasses.replace(
            first.proposal, build_id="build-headless-other"
        )
        with self.assertRaises(OperationAdmissionIdempotencyConflictV3):
            persist_or_replay_operation_admission_v3(
                _request(self.root, changed)
            )

    def test_attempt_and_child_are_unique_across_idempotency_keys(
        self,
    ) -> None:
        first = _request(self.root)
        persist_or_replay_operation_admission_v3(first)
        duplicate_attempt = dataclasses.replace(
            first.proposal,
            idempotency_key=OTHER_KEY,
            intended_child_generation_id=OTHER_CHILD,
        )
        with self.assertRaises(OperationAdmissionAttemptConflictV3):
            persist_or_replay_operation_admission_v3(
                _request(self.root, duplicate_attempt)
            )
        duplicate_child = dataclasses.replace(
            first.proposal,
            idempotency_key=THIRD_KEY,
            attempt_id=OTHER_ATTEMPT,
        )
        with self.assertRaises(OperationAdmissionChildConflictV3):
            persist_or_replay_operation_admission_v3(
                _request(self.root, duplicate_child)
            )

    def test_concurrent_exact_submissions_create_one_record(self) -> None:
        context = multiprocessing.get_context("fork")
        queue = context.Queue()
        workers = [
            context.Process(target=_concurrent_admit, args=(self.root, queue))
            for _index in range(6)
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(10)
            self.assertEqual(worker.exitcode, 0)
        outcomes = [queue.get(timeout=2) for _index in workers]
        self.assertTrue(
            all(outcome[0] == "ok" for outcome in outcomes), outcomes
        )
        self.assertEqual(sum(outcome[1] for outcome in outcomes), 1)
        self.assertEqual(len({outcome[2] for outcome in outcomes}), 1)
        names = os.listdir(os.path.join(self.root, "operation-admissions-v3"))
        self.assertEqual(len(names), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
