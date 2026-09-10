"""Actual cold caption checks at range read boundaries; A/V observations are stubs."""
from __future__ import annotations

from dataclasses import replace
import unittest
from unittest.mock import patch

from _presenter_caption_read_fixture import CaptionReadFixture
from audio.program_master_excerpt import sample_range
from guided_opening_result import read_ranges
from guided_presenter_opening_read import PresenterOpeningReadLane


class PresenterCaptionReadRouteTests(unittest.TestCase):
    """Whole-cue evidence cannot be replaced by a successful video-decode result."""

    def setUp(self) -> None:
        """Use tiny genuine held caption files and explicitly synthetic picture rows."""
        self.fixture = CaptionReadFixture()
        self.addCleanup(self.fixture.close)
        item = self.fixture
        pictures = {**item.pictures, "policy": "global-composition-then-half-open-frame-trim-v1",
            "candidateOrder": [], "executedOrder": [], "orderPolicy": "ordinary-outStart-ascending-stable-candidate-ties",
            "placementScope": "declared-own-screen-full-canvas-not-free-space-or-perceptual-proof"}
        self.record = {"profile": item.inputs.value["profile"], "pictures": pictures,
                       "media": {"core": {"TEST": "no AAC"}, "review": {"TEST": "no AAC"}}}
        self.lane = PresenterOpeningReadLane(item.read, item.held, item.layers)
        authority = item.inputs.documents["authority"]
        self.audio = {name: sample_range((authority[name]["startFrame"], authority[name]["endFrameExclusive"]),
                      (authority["frameRate"], authority["totalFrames"])) for name in ("core", "review")}
        self.context = item.fixture.root, authority, {"TEST": "no media tools invoked"}

    def test_real_caption_read_brackets_av_without_duplicate_direct_graph_reader(self) -> None:
        """Caption verification already includes the complete original graph check."""
        with self.fixture.selected(), patch("guided_opening_result._read_pair") as av, \
                patch("guided_presenter_opening_read.verify_opening_presenter_layers",
                      side_effect=AssertionError("duplicate direct graph read")), \
                patch("guided_presenter_observation.run_text", side_effect=AssertionError("no new decode")):
            read_ranges(self.record, self.audio, self.context, self.lane)
        self.assertEqual(av.call_count, 2)
        proof = self.record["pictures"]["presenterCaptionClearance"]
        self.assertIs(proof["pictureEvidenceBound"], True)
        self.assertIs(proof["qcPassed"], False)
        self.assertIs(proof["precompositionReport"]["pictureProofBound"], False)

    def test_missing_clearance_or_held_captions_refuses_before_any_av_read(self) -> None:
        """New captioned picture fields require both actual original dependencies."""
        with self.fixture.selected(), patch("guided_opening_result._read_pair") as av:
            with self.assertRaises(RuntimeError):
                read_ranges(self.record, self.audio, self.context, replace(self.lane, captions=None))
            self.record["pictures"].pop("presenterCaptionClearance")
            with self.assertRaises(RuntimeError):
                read_ranges(self.record, self.audio, self.context, self.lane)
        av.assert_not_called()

    def test_approval_flag_changed_during_last_av_read_is_rejected(self) -> None:
        """An earlier valid cold report cannot cover later in-memory substitutions."""
        calls = []

        def change(_record: dict, _pcm: dict, _context: tuple, _completed: set) -> None:
            """Fault only this fixture's Python record after the second AV stub."""
            calls.append(True)
            if len(calls) == 2:
                self.record["pictures"]["presenterCaptionClearance"]["creativeApproved"] = True

        with self.fixture.selected(), patch("guided_opening_result._read_pair", side_effect=change), \
                self.assertRaisesRegex(RuntimeError, "original arguments changed"):
            read_ranges(self.record, self.audio, self.context, self.lane)
        self.assertEqual(len(calls), 2)

    def test_original_deadline_expiring_during_av_never_returns_cold_success(self) -> None:
        """Completed AV stubs cannot restart the same caller-owned read budget."""
        calls = []

        def expire(_record: dict, _pcm: dict, _context: tuple, _completed: set) -> None:
            """Expire the existing TEST clock without touching any shared files."""
            calls.append(True)
            if len(calls) == 2:
                self.fixture.fixture.probe.deadline.expired = True

        with self.fixture.selected(), patch("guided_opening_result._read_pair", side_effect=expire), \
                self.assertRaisesRegex(RuntimeError, "expired"):
            read_ranges(self.record, self.audio, self.context, self.lane)
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
