"""Late metadata/publication races; all admission and decoder work remains STUBBED."""
from __future__ import annotations

import time
import unittest
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from _grade_project_owned_fixture import OwnedGradeFixture
from color import grade_project as project
from color import grade_project_owned as owned_module
from color.grade_project_owned import OwnedProjectObservationError


class OwnedGradePublicationTests(unittest.TestCase):
    """No pending typed observation escapes after any final-boundary failure."""

    def setUp(self) -> None:
        """Use a new inert source and private output namespace for every case."""
        self.fixture = OwnedGradeFixture()
        self.addCleanup(self.fixture.cleanup)

    def _publish_hook(self, mutate: Callable[[Path], None]) -> AbstractContextManager:
        """Run one fault after actual new immutable-result bytes have been written."""
        original = project.write_new

        def publish(path: Path, result: dict) -> None:
            """Keep normal publication then inject only the selected late fault."""
            original(path, result)
            if path.name == "observation.json":
                mutate(path)

        return patch.object(project, "write_new", side_effect=publish)

    def _late_file_fault(self, relative: str) -> None:
        """Keep per-path cases independent; never retry one partially published job."""
        fixture = OwnedGradeFixture()
        self.addCleanup(fixture.cleanup)
        original = project.write_new

        def publish(path: Path, result: dict) -> None:
            """Alter exactly one current fixture artifact after result publication."""
            original(path, result)
            if path.name == "observation.json":
                target = fixture.job / relative[4:] if relative.startswith("job:") else fixture.producer / relative
                target.write_bytes(target.read_bytes() + b"\n")

        with patch.object(project, "write_new", side_effect=publish), self.assertRaisesRegex(RuntimeError, "changed"):
            fixture.execute()
        self.assertIsNotNone(fixture.returned)
        self.assertTrue((fixture.job / "observation.json").is_file())

    def test_all_parent_and_raw_evidence_late_changes_withhold_result(self) -> None:
        """Exact same-JSON/new-byte mutations cannot acquire the pending value."""
        for relative in ("edit_plan.json", "asset_manifest.json", "../project.json",
                         "job:execution/execution.json", "job:execution/result/probe.json", "job:execution/result/frames.ffprobe"):
            with self.subTest(relative=relative):
                self._late_file_fault(relative)

    def test_late_input_and_held_parent_publication_changes_withhold_result(self) -> None:
        """Small private input/parents records are independently held too."""
        for relative in ("job:input.json", "job:parents.json"):
            with self.subTest(relative=relative):
                self._late_file_fault(relative)

    def test_changed_source_during_publication_withholds_pending_result(self) -> None:
        """The final source stat recheck follows immutable JSON publication."""
        def mutate(_path: Path) -> None:
            """Replace only this inert fixture's originally held source."""
            Path(self.fixture.identity.path).write_bytes(b"different source bytes")

        with self._publish_hook(mutate), self.assertRaisesRegex(RuntimeError, "source identity changed"):
            self.fixture.execute()
        self.assertIsNotNone(self.fixture.returned)

    def test_changed_implementation_during_publication_withholds_result(self) -> None:
        """A clean reader does not cover source edits occurring during publication."""
        def mutate(_path: Path) -> None:
            """Make the later implementation observation differ from the held one."""
            self.fixture.code.return_value = [{"path": "TEST changed", "sha256": "0" * 64}]

        with self._publish_hook(mutate), self.assertRaisesRegex(RuntimeError, "implementation.*during publication"):
            self.fixture.execute()

    def test_lost_owner_or_guard_after_publication_never_returns_result(self) -> None:
        """Publication does not end the borrowed ownership lifetime early."""
        def mutate(_path: Path) -> None:
            """Fail the original borrowed ownership guard at the final boundary."""
            self.fixture.guard.side_effect = RuntimeError("original claim lost")

        with self._publish_hook(mutate), self.assertRaisesRegex(RuntimeError, "original claim lost"):
            self.fixture.execute()

    def test_changed_server_parent_after_publication_withholds_result(self) -> None:
        """The original process parent is checked again, without adopting another."""
        parent = [self.fixture.value["ownerPid"]]

        def mutate(_path: Path) -> None:
            """Expose a different server parent only after successful JSON write."""
            parent[0] += 1000

        with patch.object(project.os, "getppid", side_effect=lambda: parent[0]), \
                self._publish_hook(mutate), self.assertRaisesRegex(RuntimeError, "original server owner changed"):
            self.fixture.execute()

    def test_original_clock_expiry_during_publication_withholds_result(self) -> None:
        """No fresh 120-second budget is minted after a late phase exhausts it."""
        clock = [1000.0]
        self.fixture.context = replace(self.fixture.context, deadline=1120.0)

        def mutate(_path: Path) -> None:
            """Consume the original clock without installing a new allowance."""
            clock[0] = 1121.0

        with patch.object(time, "monotonic", side_effect=lambda: clock[0]), \
                self._publish_hook(mutate), self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
            self.fixture.execute()
        self.assertEqual(self.fixture.worker.call_args.args[3], 1120.0)

    def test_pending_hold_expiry_retains_failed_json_without_typed_observation(self) -> None:
        """The historical separate failure-write allowance cannot rescue success."""
        clock = [1000.0]
        self.fixture.context = replace(self.fixture.context, deadline=1120.0)
        original = owned_module._references

        def hold(*args: object) -> tuple:
            """Exhaust the clock after all expected evidence hashes are held."""
            rows = original(*args)
            clock[0] = 1121.0
            return rows

        with patch.object(time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(owned_module, "_references", side_effect=hold), self.assertRaises(OwnedProjectObservationError) as error:
            self.fixture.execute()
        self.assertNotIn("observation", error.exception.result)
        self.assertEqual(error.exception.result["elapsedMs"], 121000)
        self.assertTrue(error.exception.result["cleanupVerified"])

    def test_failed_chmod_cannot_return_observation_before_immutable_publication(self) -> None:
        """A successful write alone is not the final publication boundary."""
        with patch.object(project.os, "chmod", side_effect=OSError("TEST chmod failure")), self.assertRaises(OSError):
            self.fixture.execute()
        self.assertIsNotNone(self.fixture.returned)

    def test_changed_result_bytes_cannot_replace_the_expected_publication_sha(self) -> None:
        """Never compute a fresh accepted digest from mutated published bytes."""
        def mutate(path: Path) -> None:
            """Keep equivalent JSON but alter the exact expected raw bytes."""
            path.write_bytes(path.read_bytes() + b"\n")

        with self._publish_hook(mutate), self.assertRaisesRegex(RuntimeError, "differs from its actual returned observation"):
            self.fixture.execute()

    def test_symlinked_evidence_parent_cannot_reuse_original_child_inode(self) -> None:
        """Cold current checks reject directory aliases despite unchanged file stats."""
        owned = self.fixture.execute()
        path = self.fixture.job / "execution/result"
        moved = self.fixture.job / "execution/elsewhere"
        path.rename(moved)
        path.symlink_to(moved, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "canonical"):
            owned.assert_current()

    def test_mismatched_project_directory_rejects_before_io_or_worker(self) -> None:
        """Parent references must name the same actual input project, not copies."""
        with self.assertRaisesRegex(ValueError, "exact original project job directory"):
            project.run_project_observation_owned(self.fixture.value, self.fixture.job / "elsewhere", self.fixture.context)
        self.fixture.guard.assert_not_called()
        self.fixture.worker.assert_not_called()


if __name__ == "__main__":
    unittest.main()
