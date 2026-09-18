"""Original preflight retention after synthetic TEST observation completion.

The existing fixture uses actual job readers/publication and typed sealing,
but admission and native observation are explicit inert TEST leaves. Faults
target only the fixture's named private files, never implementation dependencies.
"""
from __future__ import annotations

import copy
import unittest
import weakref
from unittest.mock import patch

from _source_color_batch_fixture import current_batch_test_pins
from _source_color_execution_fixture import SourceColorExecutionFixture
from headless.grade_launch_files import HeldLaunchFile


class SourceColorExecutionPreflightTests(unittest.TestCase):
    """Completed evidence retains original preflight data, not a renewed launch."""

    @classmethod
    def setUpClass(cls) -> None:
        """Capture actual current implementation pins once for this TEST cohort."""
        cls.pins = current_batch_test_pins()

    def setUp(self) -> None:
        """Use one exact private TEST tree and existing synthetic worker leaves."""
        self.fixture = SourceColorExecutionFixture(self.pins)
        self.addCleanup(self.fixture.cleanup)

    def _rewrite(self, name: str) -> None:
        """Change only a named already-allowlisted original TEST job metadata file."""
        result = self.fixture.execute()
        path = self.fixture.batch.jobs[0].directory / name
        self.fixture.change(path, path.read_bytes())
        with self.assertRaisesRegex(RuntimeError, "held metadata identity changed|held publication or evidence changed"):
            result.assert_current()

    def test_original_implementation_file_rewrite_remains_detectable(self) -> None:
        """Same bytes with changed original identity cannot become a fresh code proof."""
        self._rewrite("implementation.json")

    def test_original_launch_claim_rewrite_remains_detectable(self) -> None:
        """The historical preclaim stays held without reviving its resource guard."""
        self._rewrite("launch-claim.json")

    def test_original_input_rewrite_remains_detectable(self) -> None:
        """Both original preflight and published observation retain the exact input."""
        self._rewrite("input.json")

    def test_actual_preflight_survives_loss_of_external_batch_reference(self) -> None:
        """No future reader must rebuild original job refs from later file stats."""
        original = weakref.ref(self.fixture.batch)
        result = self.fixture.execute()
        self.fixture.batch = None
        self.assertIs(result._preflight, original())
        self.assertIs(result._preflight.preparation, result.preparation)
        files = {row.path for row, _held in result._preflight._read.retained if type(row) is HeldLaunchFile}
        for job in result._preflight.jobs:
            self.assertTrue({job.directory / name for name in ("input.json", "implementation.json", "launch-claim.json")} <= files)
        result.assert_current()

    def test_retired_launch_guards_and_expired_phases_do_not_block_data(self) -> None:
        """Only the same overall cutoff and persistent preparation are consulted."""
        result = self.fixture.execute()
        self.fixture.now = max(row.phase_deadline for row in result.observations) + 1
        for ref in self.fixture.refs:
            ref.launch.guard.side_effect = AssertionError("TEST transient reservation retired")
        result.assert_current()
        for ref in self.fixture.refs:
            ref.launch.guard.assert_not_called()
        self.fixture.now = self.fixture.context.deadline
        with self.assertRaisesRegex(RuntimeError, "deadline exceeded"):
            result.assert_current()

    def test_completion_does_not_reparse_or_rehash_original_preflight(self) -> None:
        """Later checks use original raw holds and code stat identities only."""
        result = self.fixture.execute()
        with patch("guided_source_color_batch.hold_launch_file", side_effect=AssertionError("no reread")), \
                patch("guided_source_color_batch.verify_grade_project_implementation", side_effect=AssertionError("no rehash")):
            result.assert_current()
        self.assertEqual(self.fixture.worker.call_count, 2)

    def test_equal_valued_preflight_clone_is_not_original_completion(self) -> None:
        """A copied private object cannot substitute for the actual preflight hold."""
        result = self.fixture.execute()
        object.__setattr__(result, "_preflight", copy.copy(result._preflight))
        with self.assertRaisesRegex(RuntimeError, "original references or metadata changed"):
            result.assert_current()

    def test_last_persistent_callback_cannot_change_original_job_projection(self) -> None:
        """Final callback-free metadata validation covers every original parsed input."""
        result = self.fixture.execute()
        self.fixture.guard.reset_mock()
        result.assert_current()
        total = self.fixture.guard.call_count
        self.fixture.guard.reset_mock()

        def mutate() -> None:
            """Change only the synthetic TEST parsed first-source input at the last callback."""
            if self.fixture.guard.call_count == total:
                self.fixture.batch.jobs[0].value["declaration"]["historyState"] = "unknown"

        self.fixture.guard.side_effect = mutate
        with self.assertRaisesRegex(RuntimeError, "original held record changed"):
            result.assert_current()

    def test_last_persistent_callback_cannot_rewrite_original_preclaim(self) -> None:
        """The final original file sweep catches mutation after earlier job checks."""
        result = self.fixture.execute()
        path = self.fixture.batch.jobs[0].directory / "launch-claim.json"
        original = path.read_bytes()
        self.fixture.guard.reset_mock()
        result.assert_current()
        total = self.fixture.guard.call_count
        self.fixture.guard.reset_mock()

        def mutate() -> None:
            """Rewrite only the original explicitly allowlisted TEST preclaim."""
            if self.fixture.guard.call_count == total:
                self.fixture.change(path, original)

        self.fixture.guard.side_effect = mutate
        with self.assertRaisesRegex(RuntimeError, "held metadata identity changed"):
            result.assert_current()


if __name__ == "__main__":
    unittest.main()
