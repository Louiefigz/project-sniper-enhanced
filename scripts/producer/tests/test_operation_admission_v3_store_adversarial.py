"""Filesystem attacks against the durable V3 operation-admission store."""

from __future__ import annotations

import dataclasses
import json
import multiprocessing
import os
import shutil
import tempfile
import unittest
from unittest import mock

from _common import pl  # noqa: F401
from _operation_admission_fixture import proposal, quality_operation
from test_operation_admission_v3_store import _request
from headless import operation_admission_transaction as store_module
from headless.artifact_contract import (
    ArtifactContractError,
    ArtifactRefV1,
    validate_artifact_ref,
)
from headless.operation_admission_binding import (
    OperationAdmissionBindingError,
    build_operation_admission_v3,
)
from headless.operation_admission_store import (
    OperationAdmissionAttemptConflictV3,
    OperationAdmissionStoreError,
    persist_or_replay_operation_admission_v3,
)
from headless.operation_admission_store_types import (
    OperationAdmissionStoreRequestV3,
)


class OperationAdmissionV3StoreAdversarialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.temporary.name)
        os.chmod(self.root, 0o700)
        self.request = _request(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _create(self) -> tuple[object, str]:
        result = persist_or_replay_operation_admission_v3(self.request)
        directory = os.path.join(
            self.root, "operation-admissions-v3", result.record_id
        )
        return result, directory

    def _inject_valid_record(self, proposed: object) -> None:
        with tempfile.TemporaryDirectory() as source:
            source_root = os.path.realpath(source)
            os.chmod(source_root, 0o700)
            request = _request(source_root, proposed)
            result = persist_or_replay_operation_admission_v3(request)
            source_record = os.path.join(
                source_root, "operation-admissions-v3", result.record_id
            )
            target_store = os.path.join(self.root, "operation-admissions-v3")
            shutil.copytree(
                source_record, os.path.join(target_store, result.record_id)
            )

    def test_unknown_and_torn_pending_entries_fail_closed(self) -> None:
        result, _directory = self._create()
        store = os.path.join(self.root, "operation-admissions-v3")
        for name in ("unexpected", f".pending-{result.record_id}-torn"):
            path = os.path.join(store, name)
            os.mkdir(path, 0o700)
            with self.subTest(name=name), self.assertRaises(
                OperationAdmissionStoreError
            ):
                persist_or_replay_operation_admission_v3(self.request)
            os.rmdir(path)

    def test_changed_operation_bytes_are_reobserved_and_rejected(self) -> None:
        _result, directory = self._create()
        operation_path = os.path.join(
            directory,
            "artifacts",
            self.request.admission.operation.artifact.relative_path,
        )
        raw = bytearray(open(operation_path, "rb").read())
        raw[-1] ^= 1
        with open(operation_path, "wb") as handle:
            handle.write(raw)
        with self.assertRaises(OperationAdmissionStoreError):
            persist_or_replay_operation_admission_v3(self.request)

    def test_unsafe_mode_and_hardlink_are_rejected(self) -> None:
        _result, directory = self._create()
        admission_path = os.path.join(directory, "admission.json")
        os.chmod(admission_path, 0o644)
        with self.assertRaises(OperationAdmissionStoreError):
            persist_or_replay_operation_admission_v3(self.request)
        os.chmod(admission_path, 0o600)
        hardlink = os.path.join(self.root, "linked-admission.json")
        os.link(admission_path, hardlink)
        with self.assertRaises(OperationAdmissionStoreError):
            persist_or_replay_operation_admission_v3(self.request)

    def test_record_closure_rejects_extra_or_missing_files(self) -> None:
        _result, directory = self._create()
        extra = os.path.join(directory, "extra.json")
        with open(extra, "wb") as handle:
            handle.write(b"{}")
        os.chmod(extra, 0o600)
        with self.assertRaises(OperationAdmissionStoreError):
            persist_or_replay_operation_admission_v3(self.request)

    def test_authority_record_cannot_be_rebound_around_retained_records(
        self,
    ) -> None:
        self._create()
        authority_path = os.path.join(self.root, "authority.json")
        replacement = {
            "authorityId": "authority-other",
            "schemaVersion": 1,
        }
        raw = (
            json.dumps(
                replacement,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("ascii")
        with open(authority_path, "wb") as handle:
            handle.write(raw)
        os.chmod(authority_path, 0o600)
        with self.assertRaises(OperationAdmissionStoreError):
            persist_or_replay_operation_admission_v3(self.request)

    def test_store_with_records_but_no_authority_binding_is_rejected(
        self,
    ) -> None:
        self._create()
        os.unlink(os.path.join(self.root, "authority.json"))
        with self.assertRaisesRegex(OperationAdmissionStoreError, "authority"):
            persist_or_replay_operation_admission_v3(self.request)

    def test_replay_rejects_retained_duplicate_attempt_identity(self) -> None:
        self._create()
        proposed = dataclasses.replace(
            self.request.proposal,
            idempotency_key="88888888-8888-4888-8888-888888888888",
            intended_child_generation_id=(
                "99999999-9999-4999-8999-999999999999"
            ),
        )
        self._inject_valid_record(proposed)
        with self.assertRaisesRegex(OperationAdmissionStoreError, "attempt"):
            persist_or_replay_operation_admission_v3(self.request)

    def test_replay_rejects_retained_duplicate_child_identity(self) -> None:
        self._create()
        proposed = dataclasses.replace(
            self.request.proposal,
            idempotency_key="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            attempt_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        )
        self._inject_valid_record(proposed)
        with self.assertRaisesRegex(OperationAdmissionStoreError, "child"):
            persist_or_replay_operation_admission_v3(self.request)

    def test_late_change_to_earlier_record_fails_second_scan(self) -> None:
        self._create()
        proposed = dataclasses.replace(
            self.request.proposal,
            idempotency_key="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            attempt_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            intended_child_generation_id=(
                "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
            ),
        )
        self._inject_valid_record(proposed)
        store = os.path.join(self.root, "operation-admissions-v3")
        first = sorted(os.listdir(store))[0]
        admission = os.path.join(store, first, "admission.json")
        original = store_module._load_record
        calls = 0

        def mutate_after_second(record_fd: int, name: str):
            nonlocal calls
            result = original(record_fd, name)
            calls += 1
            if calls == 2:
                with open(admission, "ab") as handle:
                    handle.write(b"late mutation")
            return result

        with mock.patch.object(
            store_module, "_load_record", side_effect=mutate_after_second
        ), self.assertRaises(OperationAdmissionStoreError):
            persist_or_replay_operation_admission_v3(self.request)

    def test_unrepresentable_artifact_path_cannot_poison_store(self) -> None:
        operation = quality_operation()
        proposed = proposal(operation)
        with self.assertRaises(
            (OperationAdmissionBindingError, OperationAdmissionStoreError)
        ):
            admission = build_operation_admission_v3(
                operation, proposed, "x" * 256
            )
            request = OperationAdmissionStoreRequestV3(
                self.root, operation, admission, proposed
            )
            persist_or_replay_operation_admission_v3(request)
        self.assertFalse(
            os.path.exists(os.path.join(self.root, "operation-admissions-v3"))
        )
        self.assertTrue(
            persist_or_replay_operation_admission_v3(self.request).created
        )

    def test_artifact_path_byte_depth_and_nfc_boundaries(self) -> None:
        def reference(path: str) -> ArtifactRefV1:
            return ArtifactRefV1(path, "a" * 64, 1)

        exactly_4096 = "/".join(["a" * 255] * 15 + ["b" * 254, "c"])
        over_4096 = "/".join(["a" * 255] * 16 + ["b"])
        valid = ("a" * 255, "é" * 127, "/".join(["a"] * 32), exactly_4096)
        invalid = (
            "a" * 256,
            "é" * 128,
            "e\u0301.json",
            "bad\u0085path.json",
            "bad\ud800path.json",
            "/".join(["a"] * 33),
            over_4096,
        )
        for path in valid:
            with self.subTest(valid_path_length=len(path)):
                validate_artifact_ref(reference(path))
        for path in invalid:
            with self.subTest(
                invalid_path_length=len(path)
            ), self.assertRaises(ArtifactContractError):
                validate_artifact_ref(reference(path))

    def test_concurrent_duplicate_attempt_creates_only_one_record(
        self,
    ) -> None:
        second = dataclasses.replace(
            self.request.proposal,
            idempotency_key="88888888-8888-4888-8888-888888888888",
            intended_child_generation_id=(
                "99999999-9999-4999-8999-999999999999"
            ),
        )
        requests = (self.request, _request(self.root, second))
        context = multiprocessing.get_context("fork")
        rendezvous = context.Barrier(2)
        queue = context.Queue()

        def submit(request: OperationAdmissionStoreRequestV3) -> None:
            rendezvous.wait(timeout=2)
            try:
                persist_or_replay_operation_admission_v3(request)
                queue.put("created")
            except OperationAdmissionAttemptConflictV3:
                queue.put("attempt-conflict")

        processes = [
            context.Process(target=submit, args=(item,)) for item in requests
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=3)
            self.assertEqual(process.exitcode, 0)
        outcomes = [queue.get(timeout=2) for _request_value in requests]
        self.assertEqual(sorted(outcomes), ["attempt-conflict", "created"])
        store = os.path.join(self.root, "operation-admissions-v3")
        self.assertEqual(len(os.listdir(store)), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
