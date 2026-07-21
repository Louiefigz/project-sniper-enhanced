"""Writer-only recovery tests for unit-enrollment pending records."""

from __future__ import annotations

import dataclasses
import os
import tempfile
import unittest
import uuid
from unittest import mock

from _common import pl  # noqa: F401
from _operation_admission_fixture import quality_operation
from _unit_enrollment_fixture import enrollment_proposal
from headless import unit_enrollment_store as store_module
from headless.unit_enrollment_binding import (
    build_prospective_unit_enrollment_v1,
)
from headless.unit_enrollment_store import (
    UnitEnrollmentStoreError,
    persist_or_replay_prospective_unit_enrollment_v1,
)
from headless.unit_enrollment_store_types import UnitEnrollmentStoreRequestV1


class UnitEnrollmentPendingRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = os.path.realpath(self.temporary.name)
        os.chmod(self.root, 0o700)

    def _request(self) -> UnitEnrollmentStoreRequestV1:
        base = enrollment_proposal(quality_operation())
        proposal = dataclasses.replace(
            base,
            enrollment_key=str(uuid.UUID(int=1002)),
            unit_id=str(uuid.UUID(int=10_002)),
        )
        enrollment = build_prospective_unit_enrollment_v1(proposal)
        return UnitEnrollmentStoreRequestV1(self.root, enrollment)

    def _interrupt(self) -> tuple[UnitEnrollmentStoreRequestV1, str]:
        request = self._request()
        with mock.patch.object(
            store_module.os, "rename", side_effect=OSError("crash")
        ), self.assertRaises(UnitEnrollmentStoreError):
            persist_or_replay_prospective_unit_enrollment_v1(request)
        store = os.path.join(self.root, "unit-enrollments-v1")
        return request, store

    def test_interrupted_pending_write_is_recovered_by_next_writer(
        self,
    ) -> None:
        request, store = self._interrupt()
        self.assertTrue(
            any(name.startswith(".pending-") for name in os.listdir(store))
        )
        recovered = persist_or_replay_prospective_unit_enrollment_v1(request)
        self.assertTrue(recovered.created)
        self.assertFalse(
            any(name.startswith(".pending-") for name in os.listdir(store))
        )

    def test_valid_pending_with_wrong_target_fails_closed(self) -> None:
        request, store = self._interrupt()
        pending = next(
            name for name in os.listdir(store) if name.startswith(".pending-")
        )
        nonce = pending.rsplit("-", 1)[1]
        changed = f".pending-{'0' * 64}-{nonce}"
        os.rename(os.path.join(store, pending), os.path.join(store, changed))
        with self.assertRaises(UnitEnrollmentStoreError):
            persist_or_replay_prospective_unit_enrollment_v1(request)
        self.assertTrue(os.path.exists(os.path.join(store, changed)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
