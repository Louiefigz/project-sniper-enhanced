"""Cold clearance policy/real tiny held-file tests; no media or approval."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from _presenter_caption_read_fixture import CaptionReadFixture
from guided_presenter_caption_picture import presenter_caption_picture_record
from guided_presenter_caption_read import verify_presenter_caption_picture, _caption_identities, _caption_identity_guard, _held_hash
from guided_presenter_profile import PRESENTER_PROFILE


class PresenterCaptionReadTests(unittest.TestCase):
    """Original observation attestations stay data, never reconstructed live owners."""

    def setUp(self) -> None:
        """Use actual tiny held files and explicit TEST selection/probe stubs."""
        self.value = CaptionReadFixture()
        self.addCleanup(self.value.close)

    def verify(self, pictures: dict | None = None, context: object = None) -> None:
        """Exercise actual cold graph/cue reconstruction beneath TEST selection."""
        value = self.value
        with value.selected():
            verify_presenter_caption_picture(value.pictures if pictures is None else pictures,
                value.read if context is None else context, value.held, value.layers)

    def test_original_report_roundtrip_and_raw_attestations_stay_unchanged(self) -> None:
        """A cold match does not create live ownership, decode pictures or approve."""
        before = deepcopy(self.value.pictures)
        with patch("guided_presenter_observation.run_text") as run, \
                patch("guided_presenter_execution.OwnedPresenterExecution") as owner:
            self.verify(json.loads(json.dumps(before)))
        run.assert_not_called()
        owner.assert_not_called()
        self.assertEqual(self.value.pictures, before)
        binding = before["presenterCaptionClearance"]
        self.assertIs(binding["pictureEvidenceBound"], True)
        self.assertIs(binding["precompositionReport"]["pictureProofBound"], False)
        self.assertIs(before["presenterLayers"]["captionClearanceVerified"], False)
        self.assertEqual(binding["precompositionReport"]["binding"]["presenterObservations"],
                         before["presenterLayers"]["observations"])

    def test_crossing_and_all_future_windows_keep_full_graph_and_original_review(self) -> None:
        """No opening-only truncation can retime an exit or drop a future window."""
        for span in ((60, 180), (300, 420)):
            value = CaptionReadFixture(span)
            self.addCleanup(value.close)
            with value.selected():
                verify_presenter_caption_picture(value.pictures, value.read, value.held, value.layers)
            report = value.pictures["presenterCaptionClearance"]["precompositionReport"]
            self.assertEqual(report["binding"]["coverage"], {"startFrame": 0, "endFrameExclusive": 120})
            self.assertEqual(len(report["binding"]["presenterGraph"]["windows"]), 1)
            if span[0] >= 120:
                self.assertEqual(report["state"], "not-applicable")
                self.assertEqual(report["intersections"], [])

    def test_rehashed_report_cannot_omit_intersections_change_gutter_or_claim_approval(self) -> None:
        """The report is rederived, not trusted because its local hashes agree."""
        for key, changed in (("intersections", []), ("gutterPx", 0), ("state", "not-applicable"), ("schemaVersion", True)):
            pictures = deepcopy(self.value.pictures)
            report = pictures["presenterCaptionClearance"]["precompositionReport"]
            report[key] = changed
            pictures["presenterCaptionClearance"] = presenter_caption_picture_record(report, pictures)
            with self.assertRaises(RuntimeError):
                self.verify(pictures)
        pictures = deepcopy(self.value.pictures)
        pictures["presenterCaptionClearance"]["qcPassed"] = True
        with self.assertRaises(RuntimeError):
            self.verify(pictures)

    def test_exact_graph_layers_picture_ranges_and_unknown_fields_reject(self) -> None:
        """Self-hashed detached records cannot replace independently held joins."""
        mutations = (("openingPresenterGraphHash", "f" * 64), ("pictureRangesHash", "e" * 64),
                     ("captionProjectionHash", "d" * 64), ("unknown", False), ("schemaVersion", 1.0))
        for key, value in mutations:
            pictures = deepcopy(self.value.pictures)
            pictures["presenterCaptionClearance"][key] = value
            with self.assertRaises(RuntimeError):
                self.verify(pictures)

    def test_original_page_shard_plan_and_tool_drift_reject_without_decode(self) -> None:
        """Receipt rehashing cannot excuse changes to actual held dependency bytes."""
        for token in ("plan", "tool", "caption-page-", "caption-shard-"):
            value = CaptionReadFixture()
            self.addCleanup(value.close)
            named = {"plan": value.held.binding.plan, "tool": value.read.ffprobe}
            row = named[token] if token in named else next(row for row in value.held.files
                if token in row.path and row.path.endswith(".mov"))
            value.mutate_file(Path(row.path))
            with value.selected(), self.assertRaises((RuntimeError, ValueError)):
                verify_presenter_caption_picture(value.pictures, value.read, value.held, value.layers)

    def test_last_callback_cannot_change_caption_file_or_int_typed_authority(self) -> None:
        """The same guard brackets callbacks after strong caption reads too."""
        original = self.value.read.guard
        for change in ("metadata", "page"):
            value = CaptionReadFixture()
            self.addCleanup(value.close)
            called, armed = 0, False

            def projected(report: dict, pictures: dict) -> dict:
                """Arm only after all graph/cue reconstruction and final projection."""
                nonlocal armed
                result = presenter_caption_picture_record(report, pictures)
                armed = True
                return result

            def mutate() -> None:
                """Inject immediately after the caller's real original checks."""
                nonlocal called
                value.read.guard()
                called += 1
                if armed:
                    self.mutate_after_guard(value, change)

            with value.selected(), patch("guided_presenter_caption_read.presenter_caption_picture_record", side_effect=projected), \
                    self.assertRaises(RuntimeError):
                verify_presenter_caption_picture(value.pictures, replace(value.read, guard=mutate), value.held, value.layers)
            self.assertGreaterEqual(called, 2)
            self.assertTrue(armed)
        self.assertIs(self.value.read.guard, original)

    @staticmethod
    def mutate_after_guard(value: CaptionReadFixture, change: str) -> None:
        """Change one exact TEST metadata or page-file dependency after callback."""
        if change == "metadata":
            value.inputs.documents["authority"]["totalFrames"] = 960.0
            return
        row = next(row for row in value.held.files if "caption-page-" in row.path and row.path.endswith(".mov"))
        value.mutate_file(Path(row.path))

    def test_fault_target_guard_rejects_external_linked_and_aliased_files_before_open(self) -> None:
        """Fault tests cannot write repository dependencies or follow another path."""
        value = self.value
        target = Path(value.held.binding.plan.path)
        alias = value.fixture.root / "TEST-alias.json"
        alias.symlink_to(target)
        external = next(Path(row.path) for row in value.held.external
                        if not Path(row.path).is_relative_to(value.fixture.root))
        for path in (alias, external):
            with patch("_presenter_caption_read_fixture.os.open") as opened, self.assertRaises(AssertionError):
                value.mutate_file(path)
            opened.assert_not_called()
        linked = value.fixture.root / "TEST-hardlink.json"
        os.link(target, linked)
        with patch("_presenter_caption_read_fixture.os.open") as opened, self.assertRaises(AssertionError):
            value.mutate_file(target)
        opened.assert_not_called()

    def test_parent_alias_fails_even_when_every_original_file_identity_survives(self) -> None:
        """Cheap guards retain namespace safety, not merely target-file stat equality."""
        value = self.value
        directory = Path(value.held.root)
        self.assertEqual(directory.resolve(strict=True), directory)
        self.assertTrue(directory.is_relative_to(value.fixture.root) and directory != value.fixture.root)
        self.assertEqual(value.fixture.root.parent, Path("/private/tmp"))
        self.assertTrue(value.fixture.root.name.startswith("sniper-presenter-caption-TEST-"))
        check = _caption_identity_guard(value.held)
        moved = value.fixture.root / "TEST-renamed-original-captions"
        self.assertFalse(moved.exists())
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "parent changed"):
            check()

    def test_original_parent_walk_occurs_once_without_removing_callback_fences(self) -> None:
        """Count work structurally; no machine-speed threshold changes CI policy."""
        with patch("guided_presenter_caption_read._caption_identities", wraps=_caption_identities) as parents, \
                patch("guided_presenter_caption_read._held_hash", wraps=_held_hash) as metadata:
            self.verify()
        self.assertEqual(parents.call_count, 1)
        self.assertGreater(metadata.call_count, 2)
        print(f"TEST cold guard counts: canonical_parent_walks={parents.call_count}; "
              f"held_metadata_fences={metadata.call_count}")

    def test_legacy_presence_missing_caption_owner_and_expired_original_guard_reject(self) -> None:
        """No old profile or JSON-shaped caption owner can acquire clearance."""
        context = replace(self.value.read, inputs=replace(self.value.inputs,
            value={**self.value.inputs.value, "profile": PRESENTER_PROFILE}))
        verify_presenter_caption_picture({}, context, None, ((), None))
        with self.assertRaises(RuntimeError):
            verify_presenter_caption_picture({"presenterCaptionClearance": None}, context, None, ((), None))
        with self.assertRaises(RuntimeError):
            verify_presenter_caption_picture(self.value.pictures, self.value.read, {}, self.value.layers)
        self.value.fixture.probe.deadline.expired = True
        with self.assertRaisesRegex(RuntimeError, "expired"):
            self.verify()


if __name__ == "__main__":
    unittest.main()
