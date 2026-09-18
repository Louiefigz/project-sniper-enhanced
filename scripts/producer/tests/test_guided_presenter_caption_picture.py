"""Pre/post actual adapter controls over TEST files; no native encoder or admission."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import patch

from _guided_presenter_caption_picture_fixture import CaptionPictureFixture
from cut_preview_io import digest
from guided_presenter_caption_clearance import inspect_presenter_caption_clearance, verify_presenter_caption_clearance
from guided_presenter_caption_picture import presenter_caption_picture_record
from opening_prefix_contract import canonical_hash


class PresenterCaptionPictureTests(unittest.TestCase):
    """The actual invocation flow must not confuse clearance with QC or approval."""

    def setUp(self) -> None:
        """Create independently held tiny files and original live TEST observer owner."""
        self.fixture = CaptionPictureFixture()
        self.addCleanup(self.fixture.close)

    def test_pre_and_post_clearance_bind_actual_ranges_without_new_decode(self) -> None:
        """Keep the original full-program clock and truthful nested/outer scopes."""
        fixture = self.fixture
        with patch("guided_presenter_caption_picture.inspect_presenter_caption_clearance",
                   wraps=inspect_presenter_caption_clearance) as before, \
                patch("guided_presenter_caption_picture.verify_presenter_caption_clearance",
                      wraps=verify_presenter_caption_clearance) as after, \
                patch("guided_presenter_observation.run_text") as decoder:
            pictures = fixture.render()
        before.assert_called_once()
        after.assert_called_once()
        decoder.assert_not_called()
        report = pictures["presenterCaptionClearance"]["precompositionReport"]
        self.assertEqual(pictures["presenterCaptionClearance"], presenter_caption_picture_record(report, pictures))
        self.assertEqual([row[2].frame_range for row in fixture.commands], [(0, 60), (0, 120)])
        self.assertEqual(report["binding"]["clock"]["totalFrames"], 960)
        self.assertEqual(report["binding"]["clock"]["frameRate"], "30000/1001")
        self.assertFalse(report["pictureProofBound"])
        self.assertFalse(pictures["presenterLayers"]["captionClearanceVerified"])
        bound = pictures["presenterCaptionClearance"]
        self.assertTrue(bound["pictureEvidenceBound"])
        self.assertEqual(bound["pictureRangesHash"], digest(pictures["ranges"]))
        self.assertEqual(bound["precompositionReportHash"], canonical_hash(report))
        self.assertTrue(all(bound[key] is False for key in ("qcPassed", "creativeApproved", "deliveryApproved")))

    def test_original_inputs_and_caption_owner_required_before_encoder(self) -> None:
        """An optional old context may not accidentally bypass caption inspection."""
        fixture = self.fixture
        context = replace(fixture.picture_context, presenter=replace(fixture.presenter, inputs=None))
        with self.assertRaisesRegex(RuntimeError, "original opening inputs"):
            fixture.render(context)
        with self.assertRaisesRegex(RuntimeError, "live caption/presenter owners"):
            fixture.absent_captions()
        self.assertEqual(fixture.commands, [])

    def test_crossing_review_keeps_original_window_exit_and_full_program_clock(self) -> None:
        """Coverage limits screening/output, not the original presenter animation."""
        fixture = self.fixture
        fixture.authority["core"]["endFrameExclusive"] = 45
        fixture.authority["review"]["endFrameExclusive"] = 90
        pictures = fixture.render()
        record = pictures["presenterCaptionClearance"]
        self.assertEqual(record["coverage"], {"startFrame": 0, "endFrameExclusive": 90})
        full = record["precompositionReport"]["binding"]["presenterGraph"]
        self.assertEqual(full["windows"][0]["frameRange"], [0, 120])
        self.assertEqual([row[2].frame_range for row in fixture.commands], [(0, 45), (0, 90)])
        self.assertTrue(all(row[2].presenter.windows[0].geometry.timing.end_frame_exclusive == 120
                            for row in fixture.commands))

    def test_entry_collision_rejects_before_any_composition(self) -> None:
        """A safe final hold cannot hide a source-envelope collision during entry."""
        fixture = self.fixture
        cues = [fixture.cue((0, 15), (440, 600, 460, 620))]
        with patch("guided_presenter_caption_clearance._captions", return_value=cues), \
                self.assertRaisesRegex(RuntimeError, "clearance conflict"):
            fixture.render()
        self.assertEqual(fixture.events, [])

    def test_identical_ranges_encode_once_but_keep_both_clearance_phases(self) -> None:
        """Deduplication does not skip final clearance or mint additional work."""
        fixture = self.fixture
        fixture.authority["core"] = dict(fixture.authority["review"])
        with patch("guided_presenter_caption_picture.verify_presenter_caption_clearance",
                   wraps=verify_presenter_caption_clearance) as after:
            pictures = fixture.render()
        self.assertEqual(len(fixture.commands), 1)
        after.assert_called_once()
        self.assertIs(pictures["ranges"]["core"], pictures["ranges"]["review"])

    def test_legacy_tuple_keeps_caption_fields_without_new_presenter_record(self) -> None:
        """Unselected historical composition does not acquire new owner obligations."""
        fixture = self.fixture
        with patch("guided_presenter_caption_picture.inspect_presenter_caption_clearance") as inspect:
            pictures = fixture.render((fixture.root, fixture.authority, fixture.tools))
        inspect.assert_not_called()
        self.assertIn("captionLayers", pictures)
        self.assertNotIn("presenterCaptionClearance", pictures)
        self.assertNotIn("presenterLayers", pictures)

    def test_mismatched_picture_graph_ranges_and_projection_cannot_bind(self) -> None:
        """No self-sealed outer hash may reattach an unchanged clearance elsewhere."""
        pictures = self.fixture.render()
        report = pictures["presenterCaptionClearance"]["precompositionReport"]
        mutations = (lambda value: value["ranges"]["review"].update(endFrameExclusive=119),
                     lambda value: value["captionLayers"].update(projectionHash="0" * 64),
                     lambda value: value["presenterLayers"].update(fullPresenterGraphHash="0" * 64),
                     lambda value: value["presenterLayers"]["graph"].update(captionTail=0))
        for mutate in mutations:
            changed = deepcopy(pictures)
            mutate(changed)
            with self.assertRaisesRegex(RuntimeError, "does not bind"):
                presenter_caption_picture_record(report, changed)
        changed = deepcopy(report)
        changed["pictureProofBound"] = True
        with self.assertRaisesRegex(RuntimeError, "unchanged precomposition"):
            presenter_caption_picture_record(changed, pictures)


if __name__ == "__main__":
    unittest.main()
