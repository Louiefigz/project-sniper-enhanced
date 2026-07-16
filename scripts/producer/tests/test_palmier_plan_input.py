"""Saved and unsaved plan input contracts for Palmier preflight."""
import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from _common import *  # noqa: F401,F403
from palmier.mcp_client import PalmierError
from palmier.plan_input import read_plan


class PlanInputTests(unittest.TestCase):
    def test_reads_saved_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "edit_plan.json")
            with open(path, "w") as handle:
                json.dump({"cutTrack": []}, handle)
            self.assertEqual(read_plan(path, False), {"cutTrack": []})

    def test_reads_unsaved_plan_without_touching_disk(self) -> None:
        disk = {"planVersion": 1}
        memory = {"planVersion": 2, "graphicsTrack": [{"kind": "card"}]}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "edit_plan.json")
            with open(path, "w") as handle:
                json.dump(disk, handle)
            with patch("sys.stdin", io.StringIO(json.dumps(memory))):
                self.assertEqual(read_plan(path, True), memory)
            with open(path) as handle:
                self.assertEqual(json.load(handle), disk)

    def test_non_object_stdin_fails_closed(self) -> None:
        with patch("sys.stdin", io.StringIO("[]")):
            with self.assertRaises(PalmierError):
                read_plan("unused.json", True)


if __name__ == "__main__":
    unittest.main()
