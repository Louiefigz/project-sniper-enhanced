"""Current metadata routing stays blocked by the actual unreleased audio registry."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from itertools import product
import unittest
from unittest.mock import patch

from _guided_presenter_capture_fixture import PresenterCaptureFixture, add_capture_graphic
from _guided_presenter_intake_fixture import authority_inputs, profile_inputs
from audio.render_audio_authority import SOURCE_FLOAT_POLICY_V2
from guided_media_profile import OPENING_PROFILE, body_profile, opening_profile, profile_for_plan
from guided_opening_frames import executable_frames, full_program_frames
import guided_opening_inputs as opening
import guided_presenter_intake as intake
from guided_presenter_profile import presenter_body_profile
from guided_proposal_presenter import guided_presenter_policy


class PresenterCurrentMetadataTests(unittest.TestCase):
    """Lower metadata positives are not successful intake, observed media or approval."""

    def setUp(self) -> None:
        """Create tiny descriptor fixtures only; no executable probe or media job runs."""
        self.fixture = PresenterCaptureFixture(repeated=True)
        self.addCleanup(self.fixture.close)

    def test_four_lower_classes_preserve_exact_original_plan_and_legacy_refusals(self) -> None:
        """New exact syntax is separate from legacy selectors and every held plan stays8."""
        for short, captioned in ((False, False), (True, False), (False, True), (True, True)):
            inputs = profile_inputs(self.fixture, short, captioned)
            before = deepcopy(inputs.documents)
            profile, clock = intake._matched_clock(inputs)
            self.assertEqual(intake.current_opening_profile(profile), profile)
            self.assertEqual(intake.current_body_profile(profile), presenter_body_profile(profile))
            self.assertEqual(intake.current_manual_profile(profile), short)
            self.assertEqual(intake._declared_frames(inputs, profile, clock), [])
            self.assertEqual(inputs.documents, before)
            with self.assertRaises(RuntimeError):
                opening_profile(profile)
            with self.assertRaises(RuntimeError):
                body_profile(profile)
            with self.assertRaisesRegex(RuntimeError, "presenterLayouts"):
                profile_for_plan(inputs.documents["candidatePlan"], profile)

    def test_actual_registry_refuses_all_four_current_paths_before_source_hash(self) -> None:
        """No stub turns the unreleased plan field into a successful CURRENT intake."""
        entries = (intake.presenter_metadata_frames, intake.current_profile_for_inputs, executable_frames, full_program_frames)
        for short, captioned, entry in product((False, True), (False, True), entries):
            inputs = profile_inputs(self.fixture, short, captioned)
            with self.subTest(profile=inputs.value["profile"], entry=entry.__name__), \
                    patch.object(intake, "audio_policy_reason", wraps=intake.audio_policy_reason) as audio, \
                    patch.object(intake, "_declared_frames") as lower, \
                    self.assertRaisesRegex(RuntimeError, "unreleased renderer fields.*presenterLayouts"):
                entry(inputs)
            audio.assert_called_once_with(inputs.documents["candidatePlan"], SOURCE_FLOAT_POLICY_V2)
            self.assertIs(audio.call_args.args[0], inputs.documents["candidatePlan"])
            lower.assert_not_called()

    def test_missing_wrong_geometry_cross_lane_and_authority_profile_reject(self) -> None:
        """Neither side may infer a token from layout presence or repair a mismatched token."""
        inputs = profile_inputs(self.fixture, False, False)
        alternatives = (None, True, {}, OPENING_PROFILE, intake._OPENING[1], intake._BODY[0])
        for profile in alternatives:
            with self.subTest(profile=profile), self.assertRaises(RuntimeError):
                intake._matched_clock(replace(inputs, value={**inputs.value, "profile": profile}))
        for profile in alternatives:
            docs = deepcopy(inputs.documents)
            docs["authority"]["profile"] = profile
            with self.subTest(authority=profile), self.assertRaises(RuntimeError):
                intake._matched_clock(replace(inputs, documents=docs))

    def test_actual_authority_refusal_precedes_readiness_and_every_source_hash(self) -> None:
        """Explicit TEST file/cut stubs cannot turn actual audio refusal into source admission."""
        inputs = authority_inputs(profile_inputs(self.fixture, False, False))
        with patch.object(opening, "file_hash", return_value=inputs.sha256), \
                patch.object(opening, "_documents", return_value=inputs.documents), \
                patch.object(opening, "_cut", return_value=None), \
                patch.object(opening, "_readiness") as readiness, \
                patch.object(opening, "execution_media_authority_entries") as sources, \
                self.assertRaisesRegex(RuntimeError, "unreleased renderer fields.*presenterLayouts"):
            opening.observe_inputs(inputs)
        readiness.assert_not_called()
        sources.assert_not_called()

    def test_lower_whole_graphics_include_future_rows_and_half_open_collisions(self) -> None:
        """A future own-screen conflict is not hidden by an opening-only selection."""
        inputs = profile_inputs(self.fixture, False, False)
        add_capture_graphic(inputs.documents, (42, 48))
        profile, clock = intake._matched_clock(inputs)
        rows = intake._declared_frames(inputs, profile, clock)
        self.assertEqual([(row["startFrame"], row["operationIndex"]) for row in rows], [(42, 2)])
        add_capture_graphic(inputs.documents, (27, 28))
        with self.assertRaisesRegex(RuntimeError, "overlaps requested presenter"):
            intake._declared_frames(inputs, profile, clock)

    def test_lower_workload_counts_each_occurrence_without_deduplicating_pixels(self) -> None:
        """Declared large reused assets can exceed combined cost despite one unique source."""
        inputs = profile_inputs(self.fixture, False, False)
        docs = inputs.documents
        docs["manifest"]["broll"][0]["resolution"] = [1920, 1080]
        docs["readinessPacket"]["evidence"]["presenterPolicy"] = guided_presenter_policy(docs["acceptedPlan"], docs["manifest"])
        for _index in range(30):
            add_capture_graphic(docs, (0, 2))
        profile, clock = intake._matched_clock(inputs)
        with self.assertRaisesRegex(RuntimeError, "combined graph exceeds"):
            intake._declared_frames(inputs, profile, clock)

    def test_lower_caption_cost_reserves_full_page_bound_before_any_spawn(self) -> None:
        """A captioned class cannot use only visible opening pages in full graph preflight."""
        inputs = profile_inputs(self.fixture, False, True)
        profile = inputs.value["profile"]
        for _index in range(31):
            add_capture_graphic(inputs.documents, (0, 2))
        inputs.documents["authority"]["profile"] = profile
        _, clock = intake._matched_clock(inputs)
        with self.assertRaisesRegex(RuntimeError, "caption combined graph exceeds"):
            intake._declared_frames(inputs, profile, clock)

    def test_lower_actual_v8_v2_and_whole_presentation_are_not_relabeled(self) -> None:
        """Even self-resealed header changes cannot downgrade the real V8 operation."""
        inputs = profile_inputs(self.fixture, False, False)
        profile, clock = intake._matched_clock(inputs)
        for key, value in (("schemaVersion", 1), ("schemaVersion", True), ("presenterLayouts", [])):
            docs = deepcopy(inputs.documents)
            docs["frameBindings"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(RuntimeError):
                intake._declared_frames(replace(inputs, documents=docs), profile, clock)


if __name__ == "__main__":
    unittest.main()
