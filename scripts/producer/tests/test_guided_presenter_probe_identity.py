"""Incoming byte/stat/tool/deadline faults; no real process, decode or source admission."""
from __future__ import annotations

import os
import subprocess
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from _guided_presenter_observation_fixture import ObservationFixture
from guided_presenter_observation import _current, observe_presenter_asset
from guided_presenter_probe_identity import PresenterProbePin
from headless.process_runner import ProcessOutputLimitError


class PresenterProbeIdentityTests(unittest.TestCase):
    """Actual inode faults cannot be repaired by reholding the currently visible path."""

    def setUp(self) -> None:
        """Make one tiny fake-media input with an explicit original identity."""
        self.fixture = ObservationFixture()
        self.addCleanup(self.fixture.close)

    def observe(self) -> object:
        """Run the real owner; each caller must install its explicit leaf stub."""
        value = self.fixture
        return observe_presenter_asset(value.selected, value.source, "30000/1001", value.runtime)

    def test_wrong_incoming_stat_and_size_fail_without_process(self) -> None:
        """The owner compares the incoming identity, not one minted on entry."""
        runner = Mock()
        original = self.fixture.source
        identity = original.stat_identity
        variants = [replace(original, stat_identity=identity[:1] + (identity[1] + 1,) + identity[2:]),
            replace(original, size_bytes=original.size_bytes + 1),
            replace(original, stat_identity=list(identity))]
        for changed in variants:
            self.fixture.source = changed
            with patch("guided_presenter_observation.run_text", runner), self.assertRaises(ValueError):
                self.observe()
        runner.assert_not_called()

    def test_source_path_symlink_replacement_is_not_followed(self) -> None:
        """Even a link pointing at the same bytes cannot replace the original source."""
        path = self.fixture.path
        moved = path.with_name("TEST-original")
        path.rename(moved)
        path.symlink_to(moved)
        runner = Mock()
        with patch("guided_presenter_observation.run_text", runner), self.assertRaises((ValueError, OSError)):
            self.observe()
        runner.assert_not_called()

    def test_added_hardlink_changes_incoming_single_link_identity(self) -> None:
        """A source with a new alias cannot pass the original single-link pin."""
        os.link(self.fixture.path, self.fixture.root / "TEST-alias")
        runner = Mock()
        with patch("guided_presenter_observation.run_text", runner), self.assertRaises(ValueError):
            self.observe()
        runner.assert_not_called()

    def test_tool_replacement_after_actual_return_is_terminal(self) -> None:
        """A code0 JSON return cannot validate against a different executable inode."""
        def changed(request: object) -> subprocess.CompletedProcess:
            """Mutate only the held tool during the first fake child execution."""
            Path(self.fixture.runtime.ffprobe.path).write_bytes(b"TEST changed tool")
            return subprocess.CompletedProcess(request.command, 0, self.fixture.raw()[0], "")

        with patch("guided_presenter_observation.run_text", side_effect=changed) as runner:
            with self.assertRaisesRegex(ValueError, "identity changed"):
                self.observe()
        self.assertEqual(runner.call_count, 1)

    def test_original_expiry_during_final_inode_check_cannot_return_success(self) -> None:
        """Final source checks may consume time; the original clock is checked afterwards."""
        pin = Mock(spec=PresenterProbePin)
        pin.assert_current.side_effect = lambda: setattr(self.fixture.deadline, "expired", True)
        with self.assertRaisesRegex(RuntimeError, "expired"):
            _current((pin,), self.fixture.runtime)

    def test_pin_descriptor_is_closed_after_identity_failure(self) -> None:
        """A rejected source does not leak the descriptor opened before validation."""
        real_open, opened = os.open, []

        def record_open(path: object, flags: int) -> int:
            """Capture the real source descriptor for post-error closure assertion."""
            descriptor = real_open(path, flags)
            opened.append(descriptor)
            return descriptor

        with patch("guided_presenter_probe_identity.os.open", side_effect=record_open):
            with patch.object(PresenterProbePin, "assert_current", side_effect=ValueError("TEST mismatch")):
                with self.assertRaises(ValueError):
                    PresenterProbePin(self.fixture.source, self.fixture.runtime)
        self.assertEqual(len(opened), 1)
        with self.assertRaises(OSError):
            os.fstat(opened[0])

    def test_nonexecutable_or_writable_tool_class_rejects_before_child(self) -> None:
        """Malformed held tool metadata is not repaired using the current executable."""
        runner = Mock()
        for mode in (0o100644, 0o100777):
            tool = self.fixture.runtime.ffprobe
            identity = tool.stat_identity[:2] + (mode,) + tool.stat_identity[3:]
            runtime = replace(self.fixture.runtime, ffprobe=replace(tool, stat_identity=identity))
            with patch("guided_presenter_observation.run_text", runner), self.assertRaises(ValueError):
                observe_presenter_asset(self.fixture.selected, self.fixture.source, "30000/1001", runtime)
        runner.assert_not_called()

    def test_unvalidated_operation_index_is_not_observed(self) -> None:
        """A caller-constructed frozen selection still needs its closed operation index."""
        runner = Mock()
        for index in (True, -1, 128, 1.5):
            selected = replace(self.fixture.selected, operation_index=index)
            with patch("guided_presenter_observation.run_text", runner), self.assertRaises(ValueError):
                observe_presenter_asset(selected, self.fixture.source, "30000/1001", self.fixture.runtime)
        runner.assert_not_called()

    def test_output_budget_error_has_no_second_decode_or_retry(self) -> None:
        """Existing owned-runner terminal failure propagates without a new work clock."""
        with patch("guided_presenter_observation.run_text", side_effect=ProcessOutputLimitError("TEST limit")) as runner:
            with self.assertRaises(ProcessOutputLimitError):
                self.observe()
        self.assertEqual(runner.call_count, 1)


if __name__ == "__main__":
    unittest.main()
