"""Opt-in real Next HTTP/SSE + Python CLI qualification, never browser/editorial approval."""
from __future__ import annotations

import json
import os
import unittest

from _supporting_rescan_http_fixture import HttpFixture


@unittest.skipUnless(os.environ.get("RUN_SUPPORTING_RESCAN_HTTP_TESTS") == "1",
                     "opt-in supervised real Next HTTP and Docker admission acceptance")
class SupportingRescanHttpMediaTests(HttpFixture):
    """Real HTTP boundary, streamed CLI, durable publication and retained authority."""

    def test_copied_source_supporting_post_and_rescan_stream_publish(self) -> None:
        self.initial_project()
        staged = self.stage()
        status, events = self.rescan()
        self.assertEqual(status, 200, events)
        self.assert_published(events, staged)

    def test_referenced_source_supporting_post_and_rescan_stream_publish(self) -> None:
        self.initial_project(referenced=True)
        staged = self.stage()
        status, events = self.rescan()
        self.assertEqual(status, 200, events)
        self.assert_published(events, staged)
        self.assertEqual(json.loads((self.project / "project.json").read_text())["sourceMode"], "referenced")

    def test_staged_invalid_png_returns_stream_error_without_publication(self) -> None:
        self.initial_project()
        self.stage(invalid=True)
        status, events = self.rescan()
        self.assertEqual(status, 200, events)
        self.assertTrue([row for row in events if row.get("event") == "error"], events)
        self.assertFalse([row for row in events if row.get("event") == "manifest" or row.get("status") == "done"])
        self.unchanged()

    def test_mutation_and_checkpoint_fences_reject_wrong_targets_before_children(self) -> None:
        self.initial_project()
        selected = self.fixture / "unadmitted.png"
        selected.write_bytes(b"TEST request must be blocked before this is copied or admitted")
        before = self.child_ledgers()
        with self.held_project():
            status, _ = self.post("/api/producer/supporting-media", {"dir": str(self.directory), "inputPath": str(selected)})
            self.assertEqual(status, 409)
            status, _ = self.rescan()
            self.assertEqual(status, 409)
        self.assertEqual(self.child_ledgers(), before)
        self.checkpoint()
        before = self.child_ledgers()
        for target in ({"projectRoot": str(self.project)}, {"outDir": str(self.source)},
                       {"projectRoot": str(self.project), "outDir": str(self.source)}):
            status, _ = self.post("/api/producer/ingest", {"inputPath": str(self.source), "reuseTranscripts": True, **target})
            self.assertIn(status, (400, 409, 422))
        status, _ = self.post("/api/producer/supporting-media", {"dir": str(self.directory), "inputPath": str(selected)})
        self.assertEqual(status, 409)
        self.assertEqual(self.child_ledgers(), before)
        self.unchanged()


if __name__ == "__main__":
    unittest.main()
