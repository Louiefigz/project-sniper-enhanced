"""Cross-protocol authority attacks against the durable V3 admission store."""

from __future__ import annotations

import dataclasses
import json
import multiprocessing
import os
import tempfile
import unittest
from threading import BrokenBarrierError
from unittest import mock

from _common import pl  # noqa: F401
from test_operation_admission_v3_store import _request
from headless import authority_record
from headless.admission_registry import AdmissionError, AdmissionRequest, admit
from headless.operation_admission_store import (
    OperationAdmissionStoreError,
    persist_or_replay_operation_admission_v3,
)


class _AlwaysEqual(str):
    def __eq__(self, other: object) -> bool:
        return True

    def __ne__(self, other: object) -> bool:
        return False

    __hash__ = str.__hash__


def _legacy_request(root: str) -> AdmissionRequest:
    return AdmissionRequest(
        root,
        "authority-legacy-v2",
        "12345678-1234-4234-8234-123456789012",
        "f" * 64,
        "23456789-2345-4345-8345-234567890123",
        "34567890-3456-4456-8456-345678901234",
        "2026-07-19T12:34:56+00:00",
        "release-legacy-v2",
        "build-legacy-v2",
        "policy-legacy-v2",
        None,
    )


class OperationAdmissionV3AuthorityAdversarialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.temporary.name)
        os.chmod(self.root, 0o700)
        self.request = _request(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_missing_authority_cannot_adopt_legacy_orphan_state(self) -> None:
        admit(_legacy_request(self.root))
        os.unlink(os.path.join(self.root, "authority.json"))
        with self.assertRaisesRegex(OperationAdmissionStoreError, "authority"):
            persist_or_replay_operation_admission_v3(self.request)
        self.assertFalse(
            os.path.exists(os.path.join(self.root, "authority.json"))
        )

    def test_hostile_string_equality_cannot_cross_retained_authority(
        self,
    ) -> None:
        persist_or_replay_operation_admission_v3(self.request)
        forged = dataclasses.replace(
            _legacy_request(self.root),
            authority_id=_AlwaysEqual("authority-other"),
        )
        with self.assertRaises(AdmissionError):
            admit(forged)
        self.assertFalse(os.path.exists(os.path.join(self.root, "admissions")))

    def test_allowed_lock_name_must_still_be_a_safe_lock_inode(self) -> None:
        os.symlink("/dev/null", os.path.join(self.root, ".admission.lock"))
        with self.assertRaisesRegex(OperationAdmissionStoreError, "authority"):
            persist_or_replay_operation_admission_v3(self.request)
        self.assertFalse(
            os.path.exists(os.path.join(self.root, "authority.json"))
        )
        self.assertFalse(
            os.path.exists(os.path.join(self.root, "operation-admissions-v3"))
        )

    def _assert_single_authority_winner(
        self, outcomes: list[tuple[str, str]]
    ) -> None:
        winners = [label for label, status in outcomes if status == "ok"]
        self.assertEqual(len(winners), 1, outcomes)
        with open(
            os.path.join(self.root, "authority.json"), encoding="ascii"
        ) as handle:
            retained = json.load(handle)
        expected = (
            "authority-legacy-v2"
            if winners == ["legacy"]
            else "authority-mp4-v1"
        )
        self.assertEqual(retained["authorityId"], expected)
        loser = (
            "operation-admissions-v3"
            if winners == ["legacy"]
            else "admissions"
        )
        self.assertFalse(os.path.exists(os.path.join(self.root, loser)))

    def test_cross_protocol_authority_initialization_is_serialized(
        self,
    ) -> None:
        context = multiprocessing.get_context("fork")
        rendezvous = context.Barrier(2)
        queue = context.Queue()
        original = authority_record.write_pending_replace

        def delayed_write(
            dir_fd: int, names: tuple[str, str], raw: bytes
        ) -> None:
            try:
                rendezvous.wait(timeout=0.25)
            except BrokenBarrierError:
                pass
            original(dir_fd, names, raw)

        def run(label: str) -> None:
            try:
                if label == "legacy":
                    admit(_legacy_request(self.root))
                else:
                    persist_or_replay_operation_admission_v3(self.request)
                queue.put((label, "ok"))
            except Exception as exc:  # pragma: no cover - asserted in parent
                queue.put((label, type(exc).__name__))

        with mock.patch.object(
            authority_record,
            "write_pending_replace",
            side_effect=delayed_write,
        ):
            processes = [
                context.Process(target=run, args=(label,))
                for label in ("legacy", "v3")
            ]
            for process in processes:
                process.start()
            for process in processes:
                process.join(timeout=3)
                self.assertEqual(process.exitcode, 0)
        outcomes = [queue.get(timeout=2) for _index in processes]
        self._assert_single_authority_winner(outcomes)


if __name__ == "__main__":
    unittest.main(verbosity=2)
