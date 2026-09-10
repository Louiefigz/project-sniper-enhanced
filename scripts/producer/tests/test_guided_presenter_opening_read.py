"""Current opening read wiring with real tiny pins and explicitly stubbed A/V reads."""
from __future__ import annotations

from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from _guided_presenter_read_fixture import PresenterReadFixture
from audio.program_master_excerpt import sample_range
from guided_opening_read import _current_inputs
from guided_opening_result import read_ranges
from guided_presenter_frames import presenter_program_frames
from guided_presenter_opening_read import opening_presenter_read_lane
from headless.external_media_verification import SourceVerificationRuntime


class PresenterOpeningReadTests(unittest.TestCase):
    """Saved graph checks cannot be omitted merely because range media were decoded."""

    def setUp(self) -> None:
        """No native process; the inherited picture observations are explicit TEST stubs."""
        self.fixture = PresenterReadFixture()
        self.addCleanup(self.fixture.close)
        item = self.fixture
        pictures = {**item.pictures, "policy": "global-composition-then-half-open-frame-trim-v1",
            "candidateOrder": [], "executedOrder": [], "orderPolicy": "ordinary-outStart-ascending-stable-candidate-ties",
            "placementScope": "declared-own-screen-full-canvas-not-free-space-or-perceptual-proof"}
        base = item.base
        self.record = {"profile": item.inputs.value["profile"], "pictures": pictures, "graphics": [],
            "media": {"core": {"TEST": "no AAC"}, "review": {"TEST": "no AAC"}},
            "fullProgram": {"base": {"path": base.path, "sha256": base.sha256, "sizeBytes": base.size_bytes}}}
        authority = item.inputs.documents["authority"]
        self.audio = {name: sample_range((authority[name]["startFrame"], authority[name]["endFrameExclusive"]),
                       (authority["frameRate"], authority["totalFrames"])) for name in ("core", "review")}
        self.context = item.probe.root, authority, item.capture.context.tools

    def lane(self) -> object:
        """Only metadata frame routing is stubbed past the unreleased registry gate."""
        item = self.fixture
        return opening_presenter_read_lane(item.inputs, self.record, item.capture.context)

    def test_actual_read_scope_brackets_two_existing_av_reads_without_new_selected_decode(self) -> None:
        """The current reader API keeps mechanical A/V and presenter proofs separate."""
        with patch("guided_opening_frames.executable_frames", side_effect=presenter_program_frames), \
                patch("guided_opening_result._read_pair") as av, self.lane() as lane:
            read_ranges(self.record, self.audio, self.context, lane)
        self.assertEqual(av.call_count, 2)
        with self.assertRaisesRegex(RuntimeError, "lifetime is closed"):
            read_ranges(self.record, self.audio, self.context, lane)

    def test_new_profile_without_actual_lane_or_with_json_lane_rejects_before_av(self) -> None:
        """A true-looking result or metadata field is not the original read context."""
        for lane in (None, {"verified": True}):
            with patch("guided_opening_result._read_pair") as av, \
                    self.assertRaisesRegex(RuntimeError, "actual original read context"):
                read_ranges(self.record, self.audio, self.context, lane)
            av.assert_not_called()

    def test_changed_graph_is_rejected_before_any_media_read(self) -> None:
        """Existing graph hash mismatch cannot be replaced by decoder success."""
        self.record["pictures"]["presenterLayers"]["graphHash"] = "0" * 64
        with patch("guided_opening_frames.executable_frames", side_effect=presenter_program_frames), \
                patch("guided_opening_result._read_pair") as av, self.lane() as lane:
            with self.assertRaises(RuntimeError):
                read_ranges(self.record, self.audio, self.context, lane)
        av.assert_not_called()

    def test_legacy_context_cannot_acquire_new_saved_picture_fields(self) -> None:
        """Old results retain their closed historical field set."""
        item = self.fixture
        inputs = replace(item.noop_context().inputs, value={"profile": "unity-source-float-own-screen-v1"})
        with self.assertRaisesRegex(RuntimeError, "legacy opening"):
            with opening_presenter_read_lane(inputs, self.record, item.capture.context):
                self.fail("legacy read acquired new graph")

    def test_final_callback_cannot_change_the_record_profile_after_graph_verification(self) -> None:
        """The outer read scope freezes result identity as well as its nested graph."""
        calls, change_at = [0], [None]
        with patch("guided_opening_frames.executable_frames", side_effect=presenter_program_frames), self.lane() as lane:
            def guard() -> None:
                """Simulate a last-callback record mutation after the ordinary file check."""
                lane.context.guard()
                calls[0] += 1
                if calls[0] == change_at[0]:
                    self.record["profile"] = "TEST replaced"

            controlled = replace(lane, context=replace(lane.context, guard=guard))
            controlled.verify(self.record)
            change_at[0], calls[0] = calls[0], 0
            with self.assertRaisesRegex(RuntimeError, "original arguments changed"):
                controlled.verify(self.record)

    def test_only_new_input_read_captures_same_hash_sources_under_original_clock(self) -> None:
        """The old two-argument reader path remains unchanged; no clock is started here."""
        clock = SimpleNamespace(remaining=lambda: 3.0)
        with patch("guided_opening_read.read_current_inputs", return_value="TEST") as reader:
            self.assertEqual(_current_inputs(Path("/TEST/input"), "a" * 64, self.record, clock), "TEST")
            self.assertEqual(len(reader.call_args.args), 3)
            runtime = reader.call_args.args[2]
            self.assertIs(type(runtime), SourceVerificationRuntime)
            self.assertIs(runtime.remaining, clock.remaining)
            _current_inputs(Path("/TEST/input"), "a" * 64, {"profile": "unity-source-float-own-screen-v1"}, clock)
            self.assertEqual(len(reader.call_args.args), 2)

    def test_av_callbacks_cannot_rebaseline_media_audio_or_tools(self) -> None:
        """One original snapshot spans both verifications and every A/V callback."""
        targets = (self.record["media"]["review"], self.audio["review"], self.context[2])
        for target in targets:
            self.mutate_av_metadata(target)

    def mutate_av_metadata(self, target: dict) -> None:
        """Run one TEST-only fault without excessive nested fixture lifetimes."""
        calls = []

        def change(_record: dict, _pcm: dict, _context: tuple, _completed: set) -> None:
            """Fault only TEST Python metadata after the second A/V invocation."""
            calls.append(True)
            if len(calls) == 2:
                target["TEST-late-mutation"] = True

        with patch("guided_opening_frames.executable_frames", side_effect=presenter_program_frames), \
                patch("guided_opening_result._read_pair", side_effect=change), self.lane() as lane:
            with self.assertRaisesRegex(RuntimeError, "original arguments changed|original input/context changed"):
                read_ranges(self.record, self.audio, self.context, lane)
            target.pop("TEST-late-mutation")
        self.assertEqual(len(calls), 2)

    def test_av_callback_cannot_change_an_exact_sample_integer_to_equal_float(self) -> None:
        """Shared private snapshots keep Python types without changing receipt hashes."""
        calls = []

        def change(_record: dict, _pcm: dict, _context: tuple, _completed: set) -> None:
            """Mutate one TEST sample value after its actual exact-type range check."""
            calls.append(True)
            if len(calls) == 2:
                self.audio["review"]["startSample"] = float(self.audio["review"]["startSample"])

        with patch("guided_opening_frames.executable_frames", side_effect=presenter_program_frames), \
                patch("guided_opening_result._read_pair", side_effect=change), self.lane() as lane:
            with self.assertRaisesRegex(RuntimeError, "original arguments changed"):
                read_ranges(self.record, self.audio, self.context, lane)
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
