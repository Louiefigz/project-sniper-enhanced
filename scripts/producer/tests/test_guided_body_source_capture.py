"""Pure body entry/read clock wiring; no media or approval-shaped publication."""
from __future__ import annotations

import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from guided_body_work import read_original_inputs
from headless.external_media_verification import SourceVerificationRuntime


class GuidedBodySourceCaptureTests(unittest.TestCase):
    """Each actual body entry forwards one original clock to its single initial read."""

    def setUp(self) -> None:
        """Keep all work/ownership callbacks inert in this API wiring test."""
        self.control = SimpleNamespace(value={"schemaVersion": 1, "references": {"openingInput":
            {"path": "/TEST/input.json", "sha256": "a" * 64}}}, documents={"openingResult": {"schemaVersion": 1}})
        self.clock = Mock()
        self.clock.end = 1025.0
        self.clock.remaining.return_value = 25.0
        self.clock.phase.side_effect = lambda _name, operation: operation()
        for name in ("capture_body_control_origin", "assert_body_control_origin"):
            leaf = patch("guided_body_work." + name)
            leaf.start()
            self.addCleanup(leaf.stop)

    def test_original_reader_opt_in_preserves_default_and_uses_exact_clock_callback(self) -> None:
        """Legacy callers stay two-argument; opting in creates no independent deadline."""
        with patch("guided_body_work.read_current_inputs") as reader:
            read_original_inputs(self.control)
            self.assertEqual(reader.call_args.args, (Path("/TEST/input.json"), "a" * 64))
            reader.reset_mock()
            read_original_inputs(self.control, self.clock)
        reader.assert_called_once()
        runtime = reader.call_args.args[2]
        self.assertIs(type(runtime), SourceVerificationRuntime)
        self.assertIs(runtime.remaining, self.clock.remaining)

    def test_media_entry_passes_same_original_clock_once(self) -> None:
        """Stop before execution; no actual body receipt, tool, or source work occurs."""
        import guided_body_media as media
        invocation = SimpleNamespace(activation_path=Path("/TEST/activation"),
                                     activation_sha256="b" * 64, input_sha256="c" * 64)
        with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
            with patch.object(media, "body_clock", return_value=self.clock) as clock, \
                    patch.object(media, "use_process_deadline", return_value=nullcontext()), \
                    patch.object(media, "_directory"), patch.object(media, "read_body_control", return_value=self.control), \
                    patch.object(media, "bind_body_budget"), patch.object(media, "write_new"), \
                    patch("guided_body_work.read_current_inputs", return_value=Mock()) as reader, \
                    patch.object(media, "replay_body_source_color"), \
                    patch.object(media, "prepare_body_work"), patch.object(media, "_execute", return_value={}):
                media.run(invocation, Path(directory), 25.0)
        clock.assert_called_once_with(25.0)
        reader.assert_called_once()
        self.assertIs(reader.call_args.args[2].remaining, self.clock.remaining)

    def test_cold_read_passes_original_clock_before_any_retained_media_work(self) -> None:
        """Readback does not reuse a stale capture or silently start an independent timer."""
        import guided_body_read as read
        held = SimpleNamespace(invocation=object())
        with patch.object(read, "body_clock", return_value=self.clock) as clock, \
                patch.object(read, "use_process_deadline", return_value=nullcontext()), \
                patch.object(read, "BodyReadLifetime"), \
                patch.object(read, "read_body_control", return_value=self.control), patch.object(read, "bind_body_budget"), \
                patch("guided_body_work.read_current_inputs", return_value=Mock()) as reader, \
                patch.object(read, "read_body_record", side_effect=RuntimeError("TEST stop before media")), \
                self.assertRaisesRegex(RuntimeError, "stop before media"):
            read.read_result(Path("/TEST/output"), held, 25.0)
        clock.assert_called_once_with(25.0)
        reader.assert_called_once()
        self.assertIs(reader.call_args.args[2].remaining, self.clock.remaining)


if __name__ == "__main__":
    unittest.main()
