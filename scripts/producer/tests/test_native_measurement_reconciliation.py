"""Process turnover must not erase live memory or misclassify confirmed exits."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from native_render_processes import MissingProcessFootprint
from native_render_resources import (
    GIB, ProcessIdentity, ProcessRequest, ResourceMeasurementError, ResourceSnapshot,
    read_snapshot, stop_reasons,
)
from test_native_render_resources import IDENTITY, REQUEST, START, raw_sample


class MeasurementReconciliationTests(unittest.TestCase):
    """Use exact synthetic ps/top ordering; never launch a media process."""

    def sample(self, raw: dict, after: str | BaseException,
               request: ProcessRequest = REQUEST) -> ResourceSnapshot:
        """Return one bracketed sample with the real parsing and selection code."""
        outputs = [raw[name] for name in ("sysctl", "pressure", "ps", "top")]
        with patch("native_render_resources._read_command", side_effect=outputs + [after]):
            return read_snapshot(Path("/private/tmp"), request)

    def test_confirmed_child_exit_does_not_require_a_missing_footprint(self) -> None:
        """A child absent after top has no current footprint to substitute."""
        raw = raw_sample()
        raw["top"] = raw["top"].replace("101 1G 512M\n", "")
        after = raw["ps"].replace(f"101 100 101 {START}\n", "")
        snapshot = self.sample(raw, after)
        self.assertEqual(snapshot.owned_pids, (100,))
        self.assertEqual(snapshot.owned_footprint_bytes, 2 * GIB)
        self.assertEqual(snapshot.missing_registered_pids, (101,))
        self.assertTrue(snapshot.identity_verified)

    def test_live_missing_process_still_fails_with_exact_identity(self) -> None:
        """A missing top row cannot be interpreted as an exited live process."""
        raw = raw_sample()
        raw["top"] = raw["top"].replace("101 1G 512M\n", "")
        with self.assertRaises(MissingProcessFootprint) as caught:
            self.sample(raw, raw["ps"])
        self.assertEqual(caught.exception.identities, (ProcessIdentity(101, START, 101),))
        self.assertEqual(str(caught.exception), "Owned process footprint missing; resample tree")

    def test_new_child_after_top_requires_another_measurement(self) -> None:
        """New live descendants must not disappear from the measured total."""
        raw = raw_sample()
        after = raw["ps"] + f"102 100 102 {START}\n"
        with self.assertRaises(MissingProcessFootprint) as caught:
            self.sample(raw, after)
        self.assertEqual(caught.exception.identities, (ProcessIdentity(102, START, 102),))
        self.assertEqual(caught.exception.reason, "identity-not-stable-across-footprint-read")

    def test_new_identity_is_not_trusted_even_when_top_has_its_pid(self) -> None:
        """A PID-only top row cannot bind a process missing from the first ps."""
        raw = raw_sample()
        raw["top"] += "102 3G 0B\n"
        after = raw["ps"] + f"102 100 102 {START}\n"
        with self.assertRaises(MissingProcessFootprint) as caught:
            self.sample(raw, after)
        self.assertEqual(caught.exception.evidence["identities"],
                         [{"pid": 102, "started": START, "pgid": 102}])

    def test_reused_unrelated_pid_cannot_supply_new_child_memory(self) -> None:
        """Top's old unrelated PID row must not be charged as a new child's memory."""
        raw = raw_sample()
        after = raw["ps"].replace(f"500 1 500 {START}", "500 100 500 later start")
        with self.assertRaises(MissingProcessFootprint) as caught:
            self.sample(raw, after)
        self.assertEqual(caught.exception.identities,
                         (ProcessIdentity(500, "later start", 500),))

    def test_first_read_child_is_retained_after_reparenting(self) -> None:
        """Discovery within the first read must survive loss of that ancestry."""
        raw = raw_sample()
        after = raw["ps"].replace(f"101 100 101 {START}", f"101 1 101 {START}")
        snapshot = self.sample(raw, after)
        self.assertEqual(snapshot.owned_pids, (100, 101))
        self.assertEqual(snapshot.owned_footprint_bytes, 3 * GIB)
        self.assertEqual(snapshot.processes[1].parent_pid, 1)

    def test_newly_reparented_child_with_missing_memory_still_fails(self) -> None:
        """An orphan has the same measurement requirements as an attached child."""
        raw = raw_sample()
        raw["top"] = raw["top"].replace("101 1G 512M\n", "")
        after = raw["ps"].replace(f"101 100 101 {START}", f"101 1 101 {START}")
        with self.assertRaises(MissingProcessFootprint):
            self.sample(raw, after)

    def test_child_pid_reuse_never_uses_the_old_top_footprint(self) -> None:
        """Changed start identity is a failed identity check, not a healthy sample."""
        raw = raw_sample()
        after = raw["ps"].replace(f"101 100 101 {START}", "101 1 101 later start")
        snapshot = self.sample(raw, after)
        self.assertEqual(snapshot.owned_pids, (100,))
        self.assertEqual(snapshot.reused_registered_pids, (101,))
        self.assertFalse(snapshot.identity_verified)
        self.assertIn("owned root start identity was not bound", stop_reasons(snapshot, snapshot))

    def test_root_exit_preserves_a_discovered_live_child(self) -> None:
        """The owner can still account for a child after its parent terminates."""
        raw = raw_sample()
        after = raw["ps"].replace(f"100 1 100 {START}\n", "")
        after = after.replace(f"101 100 101 {START}", f"101 1 101 {START}")
        snapshot = self.sample(raw, after)
        self.assertEqual(snapshot.owned_pids, (101,))
        self.assertEqual(snapshot.missing_registered_pids, (100,))
        self.assertEqual(snapshot.owned_footprint_bytes, GIB)

    def test_unknown_after_table_is_not_a_confirmed_exit(self) -> None:
        """Missing, malformed and denied post-top reads all fail closed."""
        for after in ("", "100 bad row\n", PermissionError("denied")):
            with self.subTest(after=after):
                with self.assertRaises((ResourceMeasurementError, PermissionError)):
                    self.sample(raw_sample(), after)

    def test_original_registered_orphan_is_not_lost(self) -> None:
        """Preexisting remembered children remain anchors across both reads."""
        raw = raw_sample()
        raw["ps"] = raw["ps"].replace(f"101 100 101 {START}", f"101 1 101 {START}")
        request = ProcessRequest(IDENTITY, (ProcessIdentity(101, START, 101),))
        snapshot = self.sample(raw, raw["ps"], request)
        self.assertEqual(snapshot.owned_pids, (100, 101))


if __name__ == "__main__":
    unittest.main()
