"""Pure initial workload and source-audio correction transport; no media or owners."""
from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from audio.channel_normalization import ChannelAuthority, ChannelRequest, ChannelTools, SourceIdentity
from audio.render_audio_bus import _segment_command
import guided_source_color_consumption_records as records
from guided_source_color_base_context import assert_source_color_plan
from guided_opening_inputs import OpeningInputs
from producer_config import MOTION


class ConsumptionMetadataBoundTests(unittest.TestCase):
    """The compiler TEST seam proves refusals precede unbounded compilation, not media quality."""

    def test_invalid_initial_count_refuses_before_compilation(self) -> None:
        """Booleans/fractions/over-limit frames are not authoritative native frame counts."""
        with patch.object(records, "compile_plan") as compile_plan:
            for count in (True, 1.0, 0, 72001, None):
                self.assertRaisesRegex(RuntimeError, "initial", records.bounded_timeline,
                    {"cutTrack": [{}]}, {"totalFrames": count})
        compile_plan.assert_not_called()

    def test_invalid_initial_cut_count_refuses_before_compilation(self) -> None:
        """Reject both omitted work and an over-limit list before growing compiled state."""
        with patch.object(records, "compile_plan") as compile_plan:
            for rows in ([], [{}] * 10001, ({},)):
                self.assertRaisesRegex(RuntimeError, "initial", records.bounded_timeline,
                    {"cutTrack": rows}, {"totalFrames": 18})
        compile_plan.assert_not_called()

    def test_exact_initial_and_compiled_boundary_is_retained(self) -> None:
        """The exact 10,000-cut/72,000-frame boundary remains data-valid, not executable approval."""
        timeline = {"segments": [{}] * 10000}
        compiler = Mock(to_dict=Mock(return_value=timeline))
        with patch.object(records, "compile_plan", return_value=compiler):
            self.assertIs(records.bounded_timeline({"cutTrack": [{}] * 10000}, {"totalFrames": 72000}), timeline)

    def test_compiler_expansion_or_empty_result_is_refused(self) -> None:
        """An input count does not permit a larger returned occurrence list."""
        compiler = Mock()
        with patch.object(records, "compile_plan", return_value=compiler):
            for rows in ([], [{}] * 10001):
                compiler.to_dict.return_value = {"segments": rows}
                self.assertRaisesRegex(RuntimeError, "compiled", records.bounded_timeline,
                    {"cutTrack": [{}]}, {"totalFrames": 18})

    def test_original_source_float_command_keeps_dead_channel_receipt_filter(self) -> None:
        """Actual bus filter composition keeps correction even when mezzanine AAC is unused."""
        source = {"id": "TEST-source", "path": "/TEST-unopened/source.mp4", "audioStreamIndex": 0}
        tools = ChannelTools("/TEST/ffmpeg", "a" * 64, "/TEST/ffprobe", "b" * 64)
        authority = ChannelAuthority(ChannelRequest(source["path"], "c" * 64, "a:0", tools),
            SourceIdentity(1, 2, 3, 4, 5), {"decision": {"stereoFilter": "pan=stereo|c0=c1|c1=c1"}})
        job = SimpleNamespace(admission=SimpleNamespace(sources=(source,), tools={"ffmpeg": {"path": tools.ffmpeg_path}}))
        segment = SimpleNamespace(source_id="TEST-source", src_start=0, src_end=.25, speed=1)
        argv, filters = _segment_command(job, (segment, None), {source["path"]: authority})
        self.assertIn(source["path"], argv)
        self.assertIn("aformat=sample_fmts=fltp,pan=stereo|c0=c1|c1=c1", filters)
        self.assertRaisesRegex(RuntimeError, "missing.*channel receipt", _segment_command, job, (segment, None), {})

    def test_graphic_derived_rail_refuses_before_any_source_callback_or_cut(self) -> None:
        """The existing rail predicate closes generated punch intent, not only authored punchIns."""
        plan = {"target": {"mode": "longform"}, "graphicsTrack": [
            {"kind": next(iter(MOTION["recompose"]["geometry"])), "anchor": "free-band"}]}
        inputs = OpeningInputs(Path("/TEST/unopened.json"), "a" * 64, {}, {"candidatePlan": plan})
        with patch("guided_source_color_base_context._profile"):
            self.assertRaisesRegex(RuntimeError, "rail recompose", assert_source_color_plan, inputs)


if __name__ == "__main__":
    unittest.main()
