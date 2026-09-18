"""Pre-decode presenter profile, full-program coexistence and workload checks."""
from __future__ import annotations

from copy import deepcopy
import unittest
from unittest.mock import patch

from _guided_presenter_capture_fixture import PresenterCaptureFixture, add_capture_graphic
import guided_presenter_capture as capture
from guided_presenter_capture_inputs import capture_selection
from guided_presenter_profile import PRESENTER_CAPTION_PROFILE
from guided_proposal_presenter import guided_presenter_policy


class PresenterCaptureAdmissionTests(unittest.TestCase):
    """Declare native1080 output; no actual output or selected asset decode is performed."""

    def setUp(self) -> None:
        """Use a valid real-shaped V8 packet over small owned TEST sentinel files."""
        self.fixture = PresenterCaptureFixture(repeated=True)
        self.addCleanup(self.fixture.close)
        self.inputs = self.fixture.inputs

    def reject(self, message: str) -> None:
        """Every known unsupported layout/workload must fail before tool acquisition."""
        with patch.object(capture, "pin_executable") as pin, patch.object(capture, "observe_presenter_asset") as observe, \
                self.assertRaisesRegex((RuntimeError, ValueError), message), \
                capture.acquire_presenter_execution(self.inputs, self.fixture.context):
            self.fail("Unsupported metadata cannot yield an owner")
        pin.assert_not_called()
        observe.assert_not_called()

    def test_supplied_invocation_and_authority_tokens_are_both_exact(self) -> None:
        """New metadata validation never implicitly activates or relabels a legacy input."""
        original = deepcopy(self.inputs.value)
        self.inputs.value["profile"] = "unity-source-float-own-screen-v1"
        self.reject("both exact supplied new profile")
        self.inputs.value.clear()
        self.inputs.value.update(original)
        self.inputs.documents["authority"]["profile"] = PRESENTER_CAPTION_PROFILE
        self.reject("both exact supplied new profile")

    def test_exact_adjacency_passes_but_future_body_overlap_rejects_before_probe(self) -> None:
        """Full-program half-open coexistence includes graphics absent from the opening."""
        add_capture_graphic(self.inputs.documents, (18, 26))
        add_capture_graphic(self.inputs.documents, (42, 48))
        self.assertEqual(len(capture_selection(self.inputs).selected), 2)
        add_capture_graphic(self.inputs.documents, (40, 43))
        self.reject("overlaps requested presenter")

    def test_known_extra_finishing_or_non_native_destination_fails_before_decode(self) -> None:
        """No chosen lane is dropped or downscaled to squeeze into this observer route."""
        original = deepcopy(self.inputs.documents)
        self.inputs.documents["candidatePlan"]["baselineLook"] = {"exposure": 1}
        self.reject("unqualified finishing")
        docs = self.inputs.documents
        docs.clear()
        docs.update(original)
        for target in (docs["acceptedPlan"]["target"], docs["candidatePlan"]["target"],
                       docs["readinessPacket"]["evidence"]["target"], docs["authority"]["target"]):
            target.update(width=1280, height=720)
        self.reject("exact native1080")

    def test_whole_graphics_plus_repeated_asset_workload_is_checked_without_dedup(self) -> None:
        """A reused asset is decoded once but consumes an input for each authored occurrence."""
        docs = self.inputs.documents
        docs["manifest"]["broll"][0]["resolution"] = [1920, 1080]
        docs["readinessPacket"]["evidence"]["presenterPolicy"] = guided_presenter_policy(docs["acceptedPlan"], docs["manifest"])
        for _index in range(30):
            add_capture_graphic(docs, (0, 2))
        # 1 base +30 graphics +2 selected occurrences exceeds64MiPixels.
        self.reject("combined graph exceeds existing workload")

    def test_caption_pages_count_before_any_selected_probe(self) -> None:
        """Held caption materialization is still later; preflight reserves complete pages."""
        docs = self.inputs.documents
        for plan in (docs["acceptedPlan"], docs["candidatePlan"]):
            plan.update(captions={"burn": True}, captionsTrack={"schemaVersion": 1,
                "source": "kept-transcript", "defaultPolicy": "line", "groups": []})
        for _index in range(31):
            add_capture_graphic(docs, (0, 2))
        docs["authority"]["profile"] = self.inputs.value["profile"] = PRESENTER_CAPTION_PROFILE
        self.reject("caption combined graph exceeds existing workload")


if __name__ == "__main__":
    unittest.main()
