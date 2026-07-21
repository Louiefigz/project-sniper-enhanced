"""Caller-forged scan and append-capacity attacks on active-fence storage."""

from __future__ import annotations

import uuid
import unittest
from unittest.mock import patch

from _active_fence_fixture import ActiveFenceFixture
from _common import pl  # noqa: F401
from headless import active_fence_journal as journal
from headless import active_fence_journal_scan as scanner
from headless.active_fence_frames import (
    build_active_fence_bootstrap_v1,
    build_active_fence_reserve_v1,
)
from headless.active_fence_lock import locked_existing_publish_mutex_v1
from headless.active_fence_types import ActiveFenceJournalScanV1


class _AlwaysEqual:
    def __eq__(self, _other: object) -> bool:
        return True


class ActiveFenceScanBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ActiveFenceFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_forged_empty_torn_scan_cannot_truncate_valid_journal(
        self,
    ) -> None:
        self.fixture.bootstrap()
        before = self.fixture.journal_bytes()
        forged = ActiveFenceJournalScanV1((), 0, len(before))
        with locked_existing_publish_mutex_v1(self.fixture.root) as lock:
            session = journal.open_active_fence_journal_v1(lock, False)
            try:
                with self.assertRaises(journal.ActiveFenceJournalError):
                    journal.repair_torn_active_fence_tail_v1(session, forged)
            finally:
                journal.close_active_fence_journal_v1(session)
        self.assertEqual(self.fixture.journal_bytes(), before)

    def test_forged_prior_and_valid_bytes_cannot_poison_journal(
        self,
    ) -> None:
        self.fixture.bootstrap()
        before = self.fixture.journal_bytes()
        prior = build_active_fence_bootstrap_v1(
            self.fixture.authority_id, str(uuid.uuid4())
        )
        transition = build_active_fence_reserve_v1(
            prior, self.fixture.attempt_a, str(uuid.uuid4())
        )
        forged = ActiveFenceJournalScanV1((prior,), len(before), 0)
        with locked_existing_publish_mutex_v1(self.fixture.root) as lock:
            session = journal.open_active_fence_journal_v1(lock, False)
            try:
                with self.assertRaises(journal.ActiveFenceJournalError):
                    journal.append_active_fence_transition_v1(
                        session, forged, transition
                    )
            finally:
                journal.close_active_fence_journal_v1(session)
        self.assertEqual(self.fixture.journal_bytes(), before)

    def test_hostile_inner_equality_and_bool_int_scan_fail_closed(
        self,
    ) -> None:
        self.fixture.bootstrap()
        before = self.fixture.journal_bytes()
        with locked_existing_publish_mutex_v1(self.fixture.root) as lock:
            session = journal.open_active_fence_journal_v1(lock, False)
            try:
                scan = journal.scan_active_fence_journal_v1(session)
                transition = build_active_fence_reserve_v1(
                    scan.transitions[-1],
                    self.fixture.attempt_a,
                    str(uuid.uuid4()),
                )
                for forged in (
                    ActiveFenceJournalScanV1(
                        (_AlwaysEqual(),), scan.valid_bytes, 0
                    ),
                    ActiveFenceJournalScanV1(
                        scan.transitions, scan.valid_bytes, False
                    ),
                ):
                    with self.subTest(forged=forged):
                        with self.assertRaises(
                            journal.ActiveFenceJournalError
                        ):
                            journal.append_active_fence_transition_v1(
                                session, forged, transition
                            )
                        self.assertEqual(self.fixture.journal_bytes(), before)
            finally:
                journal.close_active_fence_journal_v1(session)

    def test_byte_and_transition_caps_reject_before_write(self) -> None:
        self.fixture.bootstrap()
        before = self.fixture.journal_bytes()
        with locked_existing_publish_mutex_v1(self.fixture.root) as lock:
            session = journal.open_active_fence_journal_v1(lock, False)
            try:
                scan = journal.scan_active_fence_journal_v1(session)
                transition = build_active_fence_reserve_v1(
                    scan.transitions[-1],
                    self.fixture.attempt_a,
                    str(uuid.uuid4()),
                )
                cases = (
                    (
                        "MAX_ACTIVE_FENCE_TRANSITIONS",
                        len(scan.transitions),
                    ),
                    (
                        "MAX_ACTIVE_FENCE_JOURNAL_BYTES",
                        len(before) + len(transition.frame_json),
                    ),
                )
                for name, limit in cases:
                    with self.subTest(limit=name), patch.object(
                        scanner, name, limit
                    ), patch.object(journal, "write_all") as writer:
                        with self.assertRaises(
                            journal.ActiveFenceJournalError
                        ):
                            journal.append_active_fence_transition_v1(
                                session, scan, transition
                            )
                        writer.assert_not_called()
                        self.assertEqual(self.fixture.journal_bytes(), before)
            finally:
                journal.close_active_fence_journal_v1(session)


if __name__ == "__main__":
    unittest.main(verbosity=2)
