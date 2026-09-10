"""Full-body cold caption proof tests, with synthetic prefix/picture attestations."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import patch

from _presenter_caption_body_read_fixture import CaptionBodyReadFixture
from guided_caption_screen import held_cues
from guided_presenter_caption_body_read import verify_presenter_body_picture
from guided_presenter_caption_body_record import body_presenter_caption_picture_record
from guided_presenter_caption_picture import presenter_caption_picture_record
from guided_caption_layers import caption_page_clips


class PresenterCaptionBodyReadTests(unittest.TestCase):
    """One whole-cue read checks both ranges; no serialized object becomes executable."""

    def setUp(self) -> None:
        """Retain original tiny held files and explicit non-video picture bytes."""
        self.fixture = CaptionBodyReadFixture()
        self.addCleanup(self.fixture.close)

    def verify(self, value: CaptionBodyReadFixture | None = None) -> None:
        """Use the production cold body route without rendering or mocking its checks."""
        item = self.fixture if value is None else value
        with item.selected():
            verify_presenter_body_picture(item.composition, item.request, item.context, item.original.held)

    def test_full_and_opening_binding_share_one_actual_whole_caption_read(self) -> None:
        """Read count stays one; no source admission, decoded media or approval follows."""
        before = deepcopy(self.fixture.composition)
        with patch("guided_presenter_caption_read.held_cues", wraps=held_cues) as cues, \
                patch("guided_presenter_observation.run_text", side_effect=AssertionError("no decode")), \
                patch("guided_presenter_execution.OwnedPresenterExecution", side_effect=AssertionError("no live owner")):
            self.verify()
        cues.assert_called_once()
        self.assertEqual(self.fixture.composition, before)
        binding = before["presenterCaptionClearance"]
        self.assertEqual(binding["coverage"], {"startFrame": 0, "endFrameExclusive": 960})
        self.assertIs(binding["precompositionReport"]["pictureProofBound"], False)
        self.assertTrue(all(binding[key] is False for key in ("qcPassed", "creativeApproved", "deliveryApproved")))

    def test_later_body_intersections_are_not_covered_by_safe_opening(self) -> None:
        """Original future windows require actual whole-body report intersections."""
        item = CaptionBodyReadFixture((900, 960))
        self.addCleanup(item.close)
        opening = item.original.pictures["presenterCaptionClearance"]["precompositionReport"]
        self.assertEqual(opening["state"], "not-applicable")
        report = item.composition["presenterCaptionClearance"]["precompositionReport"]
        self.assertTrue(report["intersections"])
        self.verify(item)
        report["intersections"] = []
        item.composition["presenterCaptionClearance"] = body_presenter_caption_picture_record(
            report, item.proof, item.composition["retainedPicture"], caption_page_clips(item.original.held))
        with self.assertRaisesRegex(RuntimeError, "body presenter caption binding.*reconstructed"):
            self.verify(item)

    def test_original_opening_clearance_cannot_be_omitted_or_resealed(self) -> None:
        """Body graph equality does not grant the opening's separate caption proof."""
        pictures = self.fixture.context.opening_pictures
        original = deepcopy(pictures["presenterCaptionClearance"])
        pictures.pop("presenterCaptionClearance")
        with self.assertRaises(RuntimeError):
            self.verify()
        pictures["presenterCaptionClearance"] = original
        report = pictures["presenterCaptionClearance"]["precompositionReport"]
        report["intersections"] = []
        pictures["presenterCaptionClearance"] = presenter_caption_picture_record(report, pictures)
        with self.assertRaises(RuntimeError):
            self.verify()

    def test_unknown_original_proof_fields_and_retained_output_drift_reject(self) -> None:
        """Only the three exact body-owner fields may augment the original proof."""
        item = self.fixture
        item.composition["TEST-unknown"] = False
        with self.assertRaisesRegex(RuntimeError, "composition"):
            self.verify()
        item.composition.pop("TEST-unknown")
        item.composition["retainedPicture"]["sha256"] = "f" * 64
        with self.assertRaisesRegex(RuntimeError, "retained body picture"):
            self.verify()

    def test_missing_pages_or_body_binding_reject_instead_of_omitting_captions(self) -> None:
        """A saved body needs its full held caption choice and complete closed binding."""
        item = self.fixture
        with self.assertRaisesRegex(RuntimeError, "actual original held captions"):
            verify_presenter_body_picture(item.composition, item.request, item.context, None)
        original = item.request
        item.request = replace(original, caption_tail=(1, original.caption_tail[1]))
        with self.assertRaises(RuntimeError):
            self.verify()
        item.request = original
        item.composition.pop("presenterCaptionClearance")
        with self.assertRaises(RuntimeError):
            self.verify()

    def test_changed_caption_metadata_after_final_projection_cannot_return_success(self) -> None:
        """The original whole read scope outlives the final report constructor."""
        item = self.fixture

        def mutate(report: dict, proof: dict, retained: dict, pages: tuple) -> dict:
            """Fault only TEST in-memory caption metadata after genuine projection."""
            result = body_presenter_caption_picture_record(report, proof, retained, pages)
            item.original.held.data["TEST-late"] = True
            return result

        with patch("guided_presenter_caption_body_record.body_presenter_caption_picture_record", side_effect=mutate), \
                self.assertRaisesRegex(RuntimeError, "original dependencies changed"):
            self.verify()

    def test_original_deadline_and_false_scope_flags_remain_mandatory(self) -> None:
        """Neither an earlier prefix proof nor local rehashing grants a new lifetime."""
        item = self.fixture
        item.composition["presenterCaptionClearance"]["qcPassed"] = True
        with self.assertRaises(RuntimeError):
            self.verify()
        item.composition["presenterCaptionClearance"]["qcPassed"] = False
        item.original.fixture.probe.deadline.expired = True
        with self.assertRaisesRegex(RuntimeError, "expired"):
            self.verify()

    def test_separate_body_worker_attestations_do_not_rewrite_original_opening_report(self) -> None:
        """Each phase retains its own stdout hashes even when source/graph facts match."""
        item = self.fixture
        old = deepcopy(item.original.pictures)
        item.proof = deepcopy(item.proof)
        observations = item.proof["prefixOracle"]["presenterObservations"]
        observations[0]["framesSha256"] = "e" * 64
        item.composition["prefixOracle"] = item.proof["prefixOracle"]
        report = deepcopy(item.composition["presenterCaptionClearance"]["precompositionReport"])
        report["binding"]["presenterObservations"] = deepcopy(observations)
        item.composition["presenterCaptionClearance"] = body_presenter_caption_picture_record(
            report, item.proof, item.composition["retainedPicture"], caption_page_clips(item.original.held))
        self.verify()
        self.assertEqual(item.original.pictures, old)
        self.assertNotEqual(observations, old["presenterLayers"]["observations"])

    def test_nested_oracle_unknown_flag_or_missing_actual_field_rejects(self) -> None:
        """Close the actual full schema2 oracle, not just the test's core hash fields."""
        item = self.fixture
        item.proof["prefixOracle"]["qcPassed"] = True
        self.rebind_body_proof()
        with self.assertRaisesRegex(RuntimeError, "presenter body prefix oracle"):
            self.verify()
        item.proof["prefixOracle"].pop("qcPassed")
        item.proof["prefixOracle"].pop("timingMs")
        self.rebind_body_proof()
        with self.assertRaisesRegex(RuntimeError, "presenter body prefix oracle"):
            self.verify()

    def rebind_body_proof(self) -> None:
        """Rehash only this synthetic body proof, not original opening/caption files."""
        item = self.fixture
        report = item.composition["presenterCaptionClearance"]["precompositionReport"]
        item.composition["presenterCaptionClearance"] = body_presenter_caption_picture_record(
            report, item.proof, item.composition["retainedPicture"], caption_page_clips(item.original.held))


if __name__ == "__main__":
    unittest.main()
