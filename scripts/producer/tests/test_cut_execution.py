"""Stale traps for complete cut execution keys and actual decode evidence."""
from __future__ import annotations

import copy
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from cut_decode import decoder_evidence, eligible_source, execute, hardware_command
from cut_execution import CutExecution, digest, execution_scope, run_command
from cut_speed import EncodeJob, Profile, Segment, TailLead, encode_segment


class CutExecutionTests(unittest.TestCase):
    """Key inputs include seeks, both seam sources, the sample clock and runtime."""

    def setUp(self) -> None:
        """Small byte files stand in for outputs; command assembly remains real."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.part = str(Path(self.temp.name) / "part.mp4")
        Path(self.part).write_bytes(b"completed-clamped-part")
        self.environment = {"hostCpuCount": 8, "tools": {"ffmpeg": {"version": "test", "sha256": "a" * 64}},
                            "code": [{"path": "cut_speed.py", "sha256": "b" * 64}]}
        self.sources = {"source": {"path": "source", "sha256": "c" * 64},
                        "incoming": {"path": "incoming", "sha256": "d" * 64}}
        self.profile = Profile(160, 90, Fraction(30000, 1001), "yuv420p")

    def render_record(self, offset: float = 0, frames_before: int = 0) -> dict:
        """Execute actual argv assembly, mocking only the native encoder and clamp."""
        recorder = CutExecution(self.environment, self.sources, {}, set())
        channel = Mock()
        channel.filter_for.return_value = "anull"
        job = EncodeJob("source", self.profile, TailLead(.12, "incoming", 10 + offset, 1), channel, channel)
        segment = Segment(0, "s", 3, 4, 1, 0, 1)
        recorder.begin(job, frames_before)
        with patch("cut_execution._ACTIVE", Mock(get=Mock(return_value=recorder))), \
                patch("cut_speed.run_ff"), patch("cut_speed._clamp_part_audio", return_value=30):
            encode_segment(segment, job, self.part, frames_before)
        recorder.finish(self.part, 30)
        return recorder.parts[0]

    def test_jcut_seek_changes_key_even_when_filter_is_identical(self) -> None:
        """The original plan's cache trap changes only the incoming input seek."""
        first, shifted = self.render_record(), self.render_record(.08)
        argv1 = first["commands"][0]["attempts"][0]["argv"]
        argv2 = shifted["commands"][0]["attempts"][0]["argv"]
        self.assertEqual(argv1[argv1.index("-filter_complex") + 1], argv2[argv2.index("-filter_complex") + 1])
        self.assertNotEqual(first["executionKey"], shifted["executionKey"])
        self.assertNotEqual(argv1, argv2)

    def test_cumulative_clock_changes_key_even_when_command_is_identical(self) -> None:
        """NTSC upstream ripples are dependencies before native PCM clamping."""
        first, shifted = self.render_record(), self.render_record(frames_before=1)
        self.assertEqual(first["commands"], shifted["commands"])
        self.assertNotEqual(first["executionKey"], shifted["executionKey"])

    def test_host_tools_code_and_both_source_bytes_change_keys(self) -> None:
        """No stale environment or source can share an execution identity."""
        baseline = self.render_record()["executionKey"]
        for field in ("hostCpuCount", "tools", "code"):
            original = copy.deepcopy(self.environment)
            self.environment[field] = "changed"
            self.assertNotEqual(baseline, self.render_record()["executionKey"])
            self.environment = original
        for path in self.sources:
            original = self.sources[path]["sha256"]
            self.sources[path]["sha256"] = "e" * 64
            self.assertNotEqual(baseline, self.render_record()["executionKey"])
            self.sources[path]["sha256"] = original

    def test_scope_restores_context_after_failure_and_binds_silent_source(self) -> None:
        """A failed run cannot contaminate later requests in the same process."""
        with patch("cut_execution.tool_record", return_value={}), patch("cut_execution.code_records", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "deliberate"):
                with execution_scope({self.part: None}, False) as recorder:
                    self.assertEqual(len(recorder.sources[self.part]["sha256"]), 64)
                    raise RuntimeError("deliberate")
        runner = Mock(return_value="native-output")
        self.assertEqual(run_command(["ffmpeg"], runner), "native-output")

    def test_source_drift_refuses_publication(self) -> None:
        """An observation never seals a render after the held source changed."""
        with patch("cut_execution.tool_record", return_value={}), patch("cut_execution.code_records", return_value=[]):
            with execution_scope({self.part: None}, False) as recorder:
                Path(self.part).write_bytes(b"changed")
                with self.assertRaisesRegex(RuntimeError, "source changed"):
                    recorder.publish(self.part)


class DecodeEvidenceTests(unittest.TestCase):
    """Acceleration never earns a hardware label merely by exiting zero."""

    def test_failed_initialization_overrides_selected_hardware_format(self) -> None:
        """The real sandbox failure selected a format before falling back."""
        chosen = "Format videotoolbox_vld chosen by get_format()"
        self.assertEqual(decoder_evidence(chosen), "videotoolbox")
        self.assertEqual(decoder_evidence(chosen + " hwaccel initialisation returned error"), "software-fallback")
        self.assertEqual(decoder_evidence("exit zero"), "unverified")

    def test_unverified_and_failed_hardware_rerun_explicit_software(self) -> None:
        """Record failed attempts and the actual software command which completed."""
        command = ["ffmpeg", "-loglevel", "error", "-i", "source", "output"]
        for code in (0, 1):
            result = SimpleNamespace(returncode=code, stderr="unverified")
            runner = Mock()
            with patch("cut_decode.subprocess.run", return_value=result):
                observed = execute(command, runner, True)
            runner.assert_called_once_with(command)
            self.assertEqual(observed["decoder"], "software")
            self.assertEqual(len(observed["attempts"]), 2)

    def test_acceleration_is_scoped_to_first_input_and_qualified_source_family(self) -> None:
        """Small, other-codec and other-platform inputs keep ordinary decoding."""
        command = ["ffmpeg", "-loglevel", "error", "-ss", "2", "-i", "s", "-i", "tail", "out"]
        native = hardware_command(command)
        self.assertEqual(native.count("-hwaccel"), 1)
        self.assertLess(native.index("-hwaccel"), native.index("-i"))
        with patch("cut_decode.platform.system", return_value="Linux"), patch("cut_decode.run_ff") as probe:
            self.assertFalse(eligible_source("s"))
            probe.assert_not_called()
        with patch("cut_decode.platform.system", return_value="Darwin"), patch("cut_decode.run_ff", return_value='{"streams":[{"codec_name":"h264","width":3840,"height":2160,"pix_fmt":"yuv420p"}]}'):
            self.assertFalse(eligible_source("s"))
