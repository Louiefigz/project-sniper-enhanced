"""Immutable Desktop before-state storage and tamper rejection."""
from __future__ import annotations

import json
import os
import tempfile
import unittest

from _common import *  # noqa: F401,F403
from palmier.desktop_operation_snapshot import (load_before_snapshot,
                                                write_before_snapshot)
from palmier.mcp_client import PalmierError
from palmier.timeline_authority import snapshot


class DesktopOperationSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.out = os.path.join(self.temp.name, "out")
        os.makedirs(self.out)
        self.timeline = {
            "id": "candidate", "fps": 24, "width": 1920, "height": 1080,
            "totalFrames": 120,
            "tracks": [{"id": "video", "type": "video", "clips": [{
                "id": "clip", "frames": [0, 120], "mediaRef": "source",
            }]}],
        }
        self.found = snapshot("project", self.timeline)
        self.state = {
            "outDir": self.out, "projectId": "project",
            "candidate": {"timelineId": "candidate"},
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _pending(self, reference: dict) -> dict:
        return {
            "beforeFingerprint": self.found.fingerprint,
            "beforeSnapshot": reference,
        }

    def test_round_trip_is_content_addressed(self) -> None:
        first = write_before_snapshot(self.state, self.found)
        second = write_before_snapshot(self.state, self.found)
        self.assertEqual(first, second)
        loaded = load_before_snapshot(self.state, self._pending(first))
        self.assertEqual(loaded.timeline, self.found.timeline)

    def test_tampered_bytes_fail(self) -> None:
        reference = write_before_snapshot(self.state, self.found)
        with open(reference["path"], "w", encoding="utf-8") as handle:
            json.dump({"schemaVersion": 1}, handle)
        with self.assertRaisesRegex(PalmierError, "bytes changed"):
            load_before_snapshot(self.state, self._pending(reference))

    def test_pending_fingerprint_must_match_snapshot(self) -> None:
        reference = write_before_snapshot(self.state, self.found)
        pending = self._pending(reference)
        pending["beforeFingerprint"] = "0" * 64
        with self.assertRaisesRegex(PalmierError, "pending ancestry"):
            load_before_snapshot(self.state, pending)

    def test_symlink_reference_is_rejected(self) -> None:
        reference = write_before_snapshot(self.state, self.found)
        link = os.path.join(self.out, "before-link.json")
        os.symlink(reference["path"], link)
        hostile = {**reference, "path": link}
        with self.assertRaisesRegex(PalmierError, "outside authority"):
            load_before_snapshot(self.state, self._pending(hostile))


if __name__ == "__main__":
    unittest.main()
