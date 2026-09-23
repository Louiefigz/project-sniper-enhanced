"""A no-graphics edit still has a truthful Studio review project."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _common import *  # noqa: F401,F403
from studio import StudioProjectError
from studio.project_writer import ReviewBase
from studio.studio_project import GenerateRequest, generate_project
from studio.sync_diff import compute_report, load_state
from studio.view_manifest import MANIFEST_NAME, unsynced_changes


class TrimReviewProjectTests(unittest.TestCase):
    """Exercise real generation and sync parsing with an inert media fixture."""

    def setUp(self) -> None:
        """Prepare a scoped trim and mock only probing of the synthetic base bytes."""
        temporary = tempfile.TemporaryDirectory(prefix="studio-trim-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.plan = self.root / "edit_plan.json"
        self.plan.write_text(json.dumps({
            "target": {"mode": "short", "scope": "trim"},
            "captions": {"burn": False},
            "cutTrack": [{"sourceId": "TEST", "start": 0, "end": 2}],
        }))
        self.base = self.root / "base_final.mp4"
        self.base.write_bytes(b"TEST inert base; never decoded")
        self.studio = self.root / "studio"
        self.request = GenerateRequest(str(self.plan), str(self.base), str(self.studio))
        geometry = ReviewBase(1080, 1920, 2.0, 30.0, "", True)
        self.enterContext(patch("studio.studio_project._probe_base", return_value=geometry))

    def test_empty_graphics_generates_the_exact_base_and_clean_sync(self) -> None:
        """No invented treatment is needed to open a matching review timeline."""
        before = self.plan.read_bytes()
        result = generate_project(self.request)
        self.assertEqual((result["entries"], result["tracks"]), (0, 0))
        self.assertEqual(self.plan.read_bytes(), before)
        self.assertEqual((self.studio / "assets/base.mp4").read_bytes(), self.base.read_bytes())
        manifest = json.loads((self.studio / MANIFEST_NAME).read_text())
        self.assertEqual(manifest["entries"], [])
        index = (self.studio / "index.html").read_text()
        self.assertIn('id="review-base"', index)
        self.assertIn('id="review-base-audio"', index)
        self.assertNotIn('data-composition-src=', index)
        self.assertEqual(unsynced_changes(str(self.studio)), [])
        self.assertTrue(compute_report(load_state(str(self.studio))).clean)
        self.assertIn("cut changes belong in edit_plan.json",
                      (self.studio / "STORYBOARD.md").read_text())

    def test_trim_view_still_preserves_unsynced_operator_edits(self) -> None:
        """Supporting zero graphics must not weaken the overwrite guard."""
        generate_project(self.request)
        index = self.studio / "index.html"
        index.write_text(index.read_text() + "\n<!-- TEST unsynced edit -->\n")
        with self.assertRaisesRegex(StudioProjectError, "unsynced edits"):
            generate_project(self.request)
        self.assertIn("TEST unsynced edit", index.read_text())
