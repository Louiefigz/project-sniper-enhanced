"""Native-leaf-stub tests of the actual pre-lossy guard, not source/color qualification."""
from __future__ import annotations

import unittest
from contextlib import ExitStack, nullcontext
from fractions import Fraction
from unittest.mock import Mock, patch

import cut_speed as cut
from compile_timeline import Segment


class CutPictureGuardTests(unittest.TestCase):
    """The same original hook must surround every source-picture encode."""

    def setUp(self) -> None:
        """Create argument objects only; no file, source, FFmpeg or daemon is touched."""
        self.segment = Segment(0, "TEST-source", 1.0, 2.0, 1.0, 0.0, 1.0)
        self.profile = cut.Profile(160, 90, Fraction(24), "yuv420p")

    def job(self, guard: object = None) -> cut.EncodeJob:
        """Return a synthetic code-only hook context, never claimed source evidence."""
        return cut.EncodeJob("/TEST-nonexistent/source.mp4", self.profile, before_encode=guard)

    def test_entry_expiry_prevents_actual_encode_and_audio_clamp(self) -> None:
        """A valid command builder cannot erase original owner expiry before FFmpeg."""
        guard = Mock(side_effect=RuntimeError("TEST original expired"))
        with patch.object(cut, "run_ff") as native, patch.object(cut, "_clamp_part_audio") as clamp:
            with self.assertRaisesRegex(RuntimeError, "original expired"):
                cut.encode_segment(self.segment, self.job(guard), "/TEST-nonexistent/part.mp4")
        guard.assert_called_once()
        native.assert_not_called()
        clamp.assert_not_called()

    def test_guard_surrounds_actual_native_boundary_and_preserves_command(self) -> None:
        """Guarded and legacy branches build identical picture/audio arguments."""
        commands, order = [], []

        def native(command: list[str]) -> None:
            """Record the actual built command without running any executable."""
            commands.append(command)
            order.append("native")

        with patch.object(cut, "run_ff", side_effect=native), patch.object(cut, "_clamp_part_audio", return_value=24):
            cut.encode_segment(self.segment, self.job(), "/TEST-nonexistent/part.mp4")
            order.clear()
            cut.encode_segment(self.segment, self.job(lambda: order.append("guard")), "/TEST-nonexistent/part.mp4")
        self.assertEqual(order, ["guard", "native", "guard"])
        self.assertEqual(commands[0], commands[1])
        self.assertEqual(commands[1][commands[1].index("-i") + 1], "/TEST-nonexistent/source.mp4")

    def test_post_native_expiry_cannot_reach_clamp_or_return_success(self) -> None:
        """The intermediate is not a selectable result after its actual owner expires."""
        guard = Mock(side_effect=[None, RuntimeError("TEST post-native expired")])
        with patch.object(cut, "run_ff") as native, patch.object(cut, "_clamp_part_audio") as clamp:
            with self.assertRaisesRegex(RuntimeError, "post-native expired"):
                cut.encode_segment(self.segment, self.job(guard), "/TEST-nonexistent/part.mp4")
        self.assertEqual(guard.call_count, 2)
        native.assert_called_once()
        clamp.assert_not_called()

    def test_native_callback_cannot_replace_the_original_post_guard(self) -> None:
        """Retain the initial callback rather than dispatching a changed job method."""
        guard = Mock(side_effect=[None, RuntimeError("TEST original guard retained")])
        job = self.job(guard)

        def native(command: list[str]) -> None:
            """Mutate only this synthetic argument object, never files or sources."""
            object.__setattr__(job, "before_encode", lambda: None)

        with patch.object(cut, "run_ff", side_effect=native), patch.object(cut, "_clamp_part_audio") as clamp:
            with self.assertRaisesRegex(RuntimeError, "original guard retained"):
                cut.encode_segment(self.segment, job, "/TEST-nonexistent/part.mp4")
        clamp.assert_not_called()

    def test_real_options_loop_transports_same_guard_to_each_part_without_audio_changes(self) -> None:
        """Actual compiler/part loop/command builder execute; every native leaf is stubbed."""
        plan = {"cutTrack": [{"sourceId": "TEST-source", "start": start, "end": start + 1} for start in (0, 2)]}
        manifest = {"sources": [{"id": "TEST-source", "path": "/TEST-nonexistent/source.mp4"}]}
        guard = Mock()
        stubs = {"observe_cut_source_set": {"/TEST-nonexistent/source.mp4": None}, "decide_profile": self.profile,
                 "_warn_off_profile": None, "run_ff": None, "_clamp_part_audio": 24, "concat_parts": None,
                 "probe_video_frames": 48, "assert_cut_sources_stable": None, "assert_duration": {"videoFrames": 48},
                 "cut_source_receipts": [], "emit": None}
        with ExitStack() as stack:
            recorder = Mock()
            recorder.publish.return_value = {"TEST": "native leaves stubbed"}
            stack.enter_context(patch.object(cut, "execution_scope", return_value=nullcontext(recorder)))
            mocks = {name: stack.enter_context(patch.object(cut, name, return_value=result)) for name, result in stubs.items()}
            result = cut.render_cut_speed_opts(plan, manifest, "/TEST-nonexistent/out.mp4",
                                              cut.CutSpeedOptions("/TEST-nonexistent/work", before_encode=guard))
        self.assertEqual(result["videoFrames"], 48)
        self.assertEqual(guard.call_count, 6)
        self.assertEqual(mocks["run_ff"].call_count, 2)
        mocks["observe_cut_source_set"].assert_called_once_with({"/TEST-nonexistent/source.mp4"})

    def test_options_guard_refusal_precedes_all_probes(self) -> None:
        """No probe/encode can precede the original owner's entry check."""
        options = cut.CutSpeedOptions("/TEST-nonexistent/work", before_encode=Mock(side_effect=RuntimeError("TEST refused")))
        with patch.object(cut, "observe_cut_source_set") as probe, patch.object(cut, "run_ff") as native:
            with self.assertRaisesRegex(RuntimeError, "TEST refused"):
                cut.render_cut_speed_opts({}, {}, "/TEST-nonexistent/out.mp4", options)
        probe.assert_not_called()
        native.assert_not_called()


if __name__ == "__main__":
    unittest.main()
