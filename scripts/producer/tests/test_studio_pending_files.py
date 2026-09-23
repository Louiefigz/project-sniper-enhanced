"""Tracked sidecars and untracked additions retain exact pending TEST bytes."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import test_studio_pending_edits as fixtures
from studio import StudioProjectError, studio_project
from studio import sync_apply
from studio.sync_diff import compute_report, load_state
from studio.view_manifest import unsynced_changes


class StudioPendingFileTests(unittest.TestCase):
    """Reuse the same actual SDK/generated fixture without native media."""

    def setUp(self) -> None:
        """Borrow fixture setup only, never a forged successful sync result."""
        self.case = fixtures.StudioPendingEditTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def _tracked_refusal(self, relative: str) -> None:
        """Restore each owned TEST file so every rejection is independently attributable."""
        path = self.case.studio / relative
        before = path.read_bytes()
        try:
            path.write_bytes(before + fixtures.MARKER.encode())
            self.case._refused()
        finally:
            path.write_bytes(before)

    def test_modified_tracked_sidecars_and_assets_never_rebaseline(self) -> None:
        """Each real tracked CSS, descriptor, script and storyboard remains pending."""
        self.case._timing()
        for relative in ("assets/tokens.css", "STORYBOARD.md", "hyperframes.json",
                         "assets/vendor/motion-tokens.js"):
            with self.subTest(relative=relative):
                self._tracked_refusal(relative)

    def test_untracked_file_remains_nonfatal_but_requires_explicit_regeneration(self) -> None:
        """An additional file is still reported, never tracked by a legitimate sync."""
        path = self.case.studio / "TEST-operator-note.txt"
        path.write_text("TEST preserve this pending note")
        self.case._timing()
        code, output = fixtures.fixtures._run_main([str(self.case.studio), "--apply"])
        self.assertEqual(code, 0, output)
        self.assertTrue(any("unexpected" in item for item in unsynced_changes(str(self.case.studio))))
        self.assertTrue(compute_report(load_state(str(self.case.studio))).additions)
        before = self.case._snapshot()
        request = studio_project.GenerateRequest(str(self.case.root / "edit_plan.json"),
            str(self.case.root / "base_final.mp4"), str(self.case.studio))
        with self.assertRaisesRegex(StudioProjectError, "unsynced"):
            studio_project.generate_project(request)
        self.assertEqual(self.case._snapshot(), before)

    def test_deletion_preserves_operator_file_at_old_temporary_name(self) -> None:
        """A valid deletion cannot overwrite or consume any untracked operator bytes."""
        sentinel = self.case.studio / "index.html.studio-sync.tmp"
        original = b"TEST operator file at the old internal temporary name"
        sentinel.write_bytes(original)
        fixtures.fixtures._remove_slot(str(self.case.index), "gfx-01")
        code, output = fixtures.fixtures._run_main([str(self.case.studio), "--apply"])
        self.assertEqual(code, 0, output)
        self.assertTrue(sentinel.exists(), "sync consumed the original operator file")
        self.assertEqual(sentinel.read_bytes(), original)
        self.assertTrue(unsynced_changes(str(self.case.studio)))
        request = studio_project.GenerateRequest(str(self.case.root / "edit_plan.json"),
            str(self.case.root / "base_final.mp4"), str(self.case.studio))
        with self.assertRaisesRegex(StudioProjectError, "unsynced"):
            studio_project.generate_project(request)
        self.assertEqual(sentinel.read_bytes(), original)

    def test_valid_sync_preserves_operator_file_at_old_plan_temporary_name(self) -> None:
        """The accepted plan writer cannot consume a preexisting sibling TEST file."""
        sentinel = self.case.root / "edit_plan.json.studio-sync.tmp"
        original = b"TEST operator file at the old plan temporary name"
        sentinel.write_bytes(original)
        self.case._timing()
        code, output = fixtures.fixtures._run_main([str(self.case.studio), "--apply"])
        self.assertEqual(code, 0, output)
        self.assertTrue(sentinel.exists(), "sync consumed the original plan sibling file")
        self.assertEqual(sentinel.read_bytes(), original)
        plan = (self.case.root / "edit_plan.json").read_bytes()
        self.assertEqual(plan, json.dumps(json.loads(plan), indent=1).encode())
        self.assertFalse(compute_report(load_state(str(self.case.studio))).blockers)

    def test_save_during_existing_gate_cannot_be_rebaselined_as_synced(self) -> None:
        """A real pending instance save after the initial report still needs review."""
        self.case._timing()
        before = self.case._snapshot()
        original = sync_apply.gate_verdict

        def late(state: object, report: object, plan: dict, manifest: str) -> tuple:
            """Append only to the original TEST composition after the actual lint gate."""
            result = original(state, report, plan, manifest)
            self.case.instance.write_text(self.case.instance.read_text() + fixtures.MARKER)
            return result

        with patch.object(sync_apply, "gate_verdict", side_effect=late):
            code, output = fixtures.fixtures._run_main([str(self.case.studio), "--apply"])
        self.assertEqual(code, 2, output)
        before["studio/compositions/gfx-02-marker-highlight.html"] += fixtures.MARKER.encode()
        self.assertEqual(self.case._snapshot(), before)
        self.assertTrue(unsynced_changes(str(self.case.studio)))


if __name__ == "__main__":
    unittest.main()
