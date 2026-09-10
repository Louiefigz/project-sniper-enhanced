"""Pure/live-seam TEST controls; no actual native graph, admission or approval claims."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import patch

from _guided_presenter_caption_body_fixture import BodyCaptionPictureFixture
from cut_preview_io import digest
from guided_presenter_caption_body_picture import BodyPresenterCaptionContext, prepare_presenter_caption_body
from guided_presenter_caption_body_record import (
    ORIGINAL_PROOF_FIELDS, body_presenter_caption_picture_record,
)
from guided_presenter_caption_clearance import inspect_presenter_caption_clearance, verify_presenter_caption_clearance
from opening_prefix_graphs import graph_hash


class PresenterCaptionBodyPictureTests(unittest.TestCase):
    """Full-clock precheck and post-retention binding through the real body compose seam."""

    def setUp(self) -> None:
        """Start independent TEST roots; faults never touch shared held dependencies."""
        self.fixture = BodyCaptionPictureFixture()
        self.addCleanup(self.fixture.close)

    def test_full_program_binding_preserves_report_and_actual_proof(self) -> None:
        """The opening's 120-frame boundary does not truncate this 960-frame body report."""
        fixture = self.fixture
        result = fixture.render_body()
        record = result["presenterCaptionClearance"]
        report = record["precompositionReport"]
        self.assertEqual(record["coverage"], {"startFrame": 0, "endFrameExclusive": 960})
        self.assertEqual(record["fullCombinedGraphHash"], graph_hash(fixture.request, "full"))
        self.assertEqual(record["fullCaptionTail"], len(fixture.value.caption_clips))
        self.assertEqual(record["compositionProofHash"], digest(fixture.last_proof))
        self.assertEqual(set(fixture.last_proof), ORIGINAL_PROOF_FIELDS)
        self.assertFalse(report["pictureProofBound"])
        self.assertTrue(record["pictureEvidenceBound"])
        self.assertTrue(all(record[key] is False for key in ("qcPassed", "creativeApproved", "deliveryApproved")))
        self.assertEqual(len(fixture.commands), 1)
        self.assertEqual(fixture.output.read_bytes(), (fixture.root / "picture-only.mp4").read_bytes())
        self.assertTrue(fixture.captions.finish(str(fixture.output))["burned"])

    def test_actual_inspection_surrounds_encode_and_retained_copy(self) -> None:
        """Both report computations run; native and timing leaves alone are TEST stubs."""
        fixture = self.fixture

        def inspect(context: object, guard: object) -> dict:
            """Record the real precomposition call."""
            fixture.events.append("inspect-full")
            return inspect_presenter_caption_clearance(context, guard)

        def verify(context: object, report: dict, guard: object) -> None:
            """The retained copy and actual caption completion must exist by this phase."""
            fixture.events.append("verify-full")
            self.assertTrue((fixture.root / "picture-only.mp4").is_file())
            self.assertIsNotNone(fixture.captions._completion)
            verify_presenter_caption_clearance(context, report, guard)

        with patch("guided_presenter_caption_body_picture.inspect_presenter_caption_clearance", side_effect=inspect), \
                patch("guided_presenter_caption_body_picture.verify_presenter_caption_clearance", side_effect=verify):
            fixture.render_body()
        self.assertEqual(fixture.events, ["inspect-full", "body-prefix-and-picture-encode",
                                         "body-retain-picture-copy", "verify-full"])

    def test_collision_rejects_before_prefix_or_retention(self) -> None:
        """A manually protected entry envelope is tested, not only its settled hold."""
        fixture = self.fixture
        cues = [fixture.cue((0, 15), (440, 600, 460, 620))]
        with patch("guided_presenter_caption_clearance._captions", return_value=cues), \
                self.assertRaisesRegex(RuntimeError, "clearance conflict"):
            fixture.render_body()
        self.assertFalse(fixture.output.exists())
        self.assertEqual(fixture.commands, [])

    def test_missing_live_caption_owner_rejects_before_prefix(self) -> None:
        """A prefilled request tail cannot replace the actual original caption owner."""
        fixture = self.fixture
        fixture.body.captions = None
        with self.assertRaisesRegex(RuntimeError, "actual live owners"):
            fixture.render_body()
        self.assertEqual(fixture.commands, [])

    def test_missing_or_retimed_full_tail_rejects_before_prefix(self) -> None:
        """Equal page IDs do not authorize truncated or rescheduled original pages."""
        fixture = self.fixture
        pages = deepcopy(fixture.value.caption_clips)
        pages[-1]["endFrameExclusive"] -= 1
        fixture.value = replace(fixture.value, caption_clips=pages)
        with self.assertRaisesRegex(RuntimeError, "original full pages"):
            fixture.render_body()
        self.assertEqual(fixture.commands, [])

    def test_wrong_actual_return_graph_stops_retention(self) -> None:
        """Never copy an oracle graph hash without matching the actual original request."""
        fixture, encode = self.fixture, self.fixture.encode

        def wrong(job: object) -> dict:
            """Change only TEST returned graph metadata, not production files."""
            proof = encode(job)
            proof["prefixOracle"]["fullGraphHash"] = "0" * 64
            return proof

        fixture.encode = wrong
        with self.assertRaisesRegex(RuntimeError, "exact schema2 graph proof"):
            fixture.render_body()
        self.assertFalse((fixture.root / "picture-only.mp4").exists())
        self.assertIsNone(fixture.body.composition)

    def test_pure_projector_rejects_augmented_proof_and_opening_coverage(self) -> None:
        """The shared cold/live hash domain excludes exactly the original augmentations."""
        fixture = self.fixture
        result = fixture.render_body()
        record = result["presenterCaptionClearance"]
        args = (record["precompositionReport"], fixture.last_proof, result["retainedPicture"], fixture.value.caption_clips)
        self.assertEqual(body_presenter_caption_picture_record(*args), record)
        with self.assertRaises(RuntimeError):
            body_presenter_caption_picture_record(args[0], result, args[2], args[3])
        report = deepcopy(args[0])
        report["binding"]["coverage"]["endFrameExclusive"] = 120
        with self.assertRaisesRegex(RuntimeError, "whole-program"):
            body_presenter_caption_picture_record(report, *args[1:])

    def test_genuine_uncaptioned_or_legacy_path_does_not_inspect(self) -> None:
        """The new layer does not add a clearance record or work on absent caption lanes."""
        fixture = self.fixture
        plan = fixture.inputs.documents["candidatePlan"]
        plan.pop("captionsTrack", None)
        plan.pop("captions", None)
        context = BodyPresenterCaptionContext(fixture.inputs, None, fixture.owner, fixture.guard)
        request = replace(fixture.request, caption_tail=None)
        value = replace(fixture.value, caption_clips=())
        with patch("guided_presenter_caption_body_picture.inspect_presenter_caption_clearance") as inspector:
            self.assertIsNone(prepare_presenter_caption_body(context, request, value, "unused"))
        inspector.assert_not_called()


if __name__ == "__main__":
    unittest.main()
