"""Exact current parser/crop seams with explicit TEST stubs, not admitted execution."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from _guided_presenter_capture_fixture import PresenterCaptureFixture
from _guided_presenter_intake_fixture import invocation, profile_inputs, requested_crop_inputs
from cut_preview_io import digest
from guided_body_contract import parse_body_input, parse_current_body_input
from guided_media_profile import CAPTION_SHORT_PROFILE, OPENING_PROFILE
import guided_opening_inputs as opening
import guided_presenter_intake as intake
from headless.external_media_verification import SourceVerificationRuntime
from guided_proposal_music import guided_music_policy
from test_guided_body_contract import body_input
from test_guided_proposal_reframe_guards import cut_inputs


class PresenterCurrentParserTests(unittest.TestCase):
    """Only syntax/call routing is stubbed; no fake source receipt is authenticated."""

    def test_current_opening_dispatch_retains_four_tokens_14_refs_and_original_clock(self) -> None:
        """The one initial capture receives the identical caller runtime, never a new budget."""
        runtime = SourceVerificationRuntime(lambda: 12.5)
        for profile in intake._OPENING:
            row = invocation(profile)
            before = deepcopy(row)
            with patch.object(opening, "_json", return_value=(row, 1)), \
                    patch.object(opening, "_documents", return_value={"TEST": "not authenticated"}) as docs, \
                    patch.object(opening, "_initial_observation", side_effect=lambda inputs, clock: inputs) as observe:
                result = opening.read_current_inputs(Path("/TEST/input.json"), "b" * 64, runtime)
            self.assertEqual(result.value, before)
            self.assertEqual(len(result.value["documents"]), 14)
            docs.assert_called_once_with(row["documents"])
            self.assertIs(observe.call_args.args[1], runtime)
            observe.assert_called_once()
            self.assertIsNone(result.verified_media)

    def test_historical_opening_refuses_new_and_current_rejects_unknown_tokens(self) -> None:
        """A newer parser cannot re-label old results or treat missing/null as a fresh class."""
        invalid = (*intake._BODY, None, True, {}, "", "future-profile")
        for profile in intake._OPENING:
            with patch.object(opening, "_json", return_value=(invocation(profile), 1)), \
                    patch.object(opening, "_documents") as docs, self.assertRaises(RuntimeError):
                opening.read_inputs(Path("/TEST/input.json"), "b" * 64)
            docs.assert_not_called()
        for profile in invalid:
            with patch.object(opening, "_json", return_value=(invocation(profile), 1)), \
                    patch.object(opening, "_documents") as docs, self.assertRaises(RuntimeError):
                opening.read_current_inputs(Path("/TEST/input.json"), "b" * 64)
            docs.assert_not_called()

    def test_current_syntax_does_not_drop_documents_or_accept_hash_and_field_drift(self) -> None:
        """Expanded class syntax does not widen the closed original invocation shape."""
        for mutation in ("document", "extra", "hash"):
            row = invocation(intake._OPENING[0])
            if mutation == "document":
                del row["documents"]["occurrences"]
                row["executionInputHash"] = digest({key: value for key, value in row.items() if key != "executionInputHash"})
            if mutation == "extra":
                row["executable"] = True
            if mutation == "hash":
                row["executionInputHash"] = "f" * 64
            with patch.object(opening, "_json", return_value=(row, 1)), \
                    patch.object(opening, "_documents") as docs, self.assertRaises(RuntimeError):
                opening.read_current_inputs(Path("/TEST/input.json"), "b" * 64)
            docs.assert_not_called()

    def test_legacy_opening_still_retains_its_original_class(self) -> None:
        """No new default is selected when a historical token is already held."""
        row = invocation(OPENING_PROFILE)
        with patch.object(opening, "_json", return_value=(row, 1)), patch.object(opening, "_documents", return_value={}), \
                patch.object(opening, "_initial_observation", side_effect=lambda inputs, clock: inputs):
            old = opening.read_inputs(Path("/TEST/input.json"), "b" * 64)
            current = opening.read_current_inputs(Path("/TEST/input.json"), "b" * 64)
        self.assertEqual(current, old)

    def test_body_current_only_pairs_exact_four_new_syntax_classes(self) -> None:
        """Body syntax is not an execution claim, and old public body parser remains strict."""
        for opening_profile, profile in zip(intake._OPENING, intake._BODY):
            row = body_input()
            row["profile"] = profile
            self.assertEqual(parse_current_body_input(row), row)
            self.assertEqual(intake.current_body_profile(opening_profile), profile)
            with self.assertRaises(RuntimeError):
                parse_body_input(row)
        for profile in (*intake._OPENING, None, True, {}, "future-profile"):
            row = body_input()
            row["profile"] = profile
            with self.assertRaises(RuntimeError):
                parse_current_body_input(row)


class PresenterRequestedCropTests(unittest.TestCase):
    """Lower cut validation keeps actual candidate layout; registry is a later refusal."""

    def test_exact_new_caption_short_keeps_requested_crop_and_actual_v8(self) -> None:
        """Only the new class reaches shared native geometry; old no-presenter guard stays strict."""
        inputs = requested_crop_inputs()
        before = deepcopy(inputs)
        self.assertIsNotNone(opening._cut(inputs))  # Explicit TEST music request remains retained too.
        self.assertEqual(inputs, before)
        self.assertEqual(inputs.documents["readinessPacket"]["proposal"]["schemaVersion"], 8)
        self.assertIn("presenterLayouts", inputs.documents["candidatePlan"])
        with self.assertRaisesRegex(RuntimeError, "presenterLayouts"):
            opening._cut(requested_crop_inputs(CAPTION_SHORT_PROFILE))

    def test_other_new_classes_and_changed_requested_crop_are_not_reinterpreted(self) -> None:
        """A short caption request cannot borrow a long or uncaptioned token to pass."""
        for profile in intake._OPENING[:3]:
            with self.assertRaisesRegex(RuntimeError, "explicit captioned-short"):
                opening._cut(requested_crop_inputs(profile))
        inputs = requested_crop_inputs()
        inputs.documents["candidatePlan"]["reframe"]["crop"][0] += 0.01
        with self.assertRaisesRegex(RuntimeError, "candidate reframe differs"):
            opening._cut(inputs)

    def test_new_uncaptioned_manual_class_preserves_original_crop_and_captions_off(self) -> None:
        """A presenter request alone cannot silently author another short crop or caption lane."""
        fixture = PresenterCaptureFixture()
        self.addCleanup(fixture.close)
        inputs = profile_inputs(fixture, True, False)
        docs = inputs.documents
        docs["readinessPacket"]["evidence"]["musicPolicy"] = guided_music_policy(docs["acceptedPlan"], docs["manifest"])
        current = cut_inputs(docs["acceptedPlan"], docs["candidatePlan"], docs["readinessPacket"], inputs.value["profile"])
        current.documents["manifest"] = docs["manifest"]
        self.assertIsNone(opening._cut(current))
        before = deepcopy(current.documents["candidatePlan"])
        for key, value in (("reframe", {"layout": "fill", "crop": [0.1, 0, 0.9, 1], "track": False}),
                           ("captions", {"burn": True})):
            current.documents["candidatePlan"] = {**before, key: value}
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, "submitted manual short"):
                opening._cut(current)


if __name__ == "__main__":
    unittest.main()
