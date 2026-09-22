"""Omitting an optional CLI path must retain the freshly rebuilt base receipt."""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import assemble
import assemble_arguments
import assemble_base_rebuild
from test_base_reuse import bound_record


class DefaultBaseReceiptTests(unittest.TestCase):
    """Exercise parser, real promotion and exact base/source checks together."""

    def setUp(self) -> None:
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.dict(os.environ))
        self.base = self.root / "base_final.mp4"
        self.base.write_bytes(b"TEST completed base")
        self.plan = {"cutTrack": [{"sourceId": "raw-1", "start": 0, "end": 2}]}
        self.record = bound_record(self.base, self.plan)
        self.plan_path = self.root / "edit_plan.json"
        self.plan_path.write_text(json.dumps(self.plan))
        self.argv = ["assemble.py", str(self.base), str(self.plan_path), str(self.root / "final.mp4"),
                     "--manifest", self.record["manifestPath"], "--auto-base"]

    def parse(self, additional: list[str] | None = None) -> object:
        with patch.object(sys, "argv", self.argv + (additional or [])):
            return assemble_arguments.parse_arguments()

    def render_fixture(self, _job: object, _plan_path: str, directory: str) -> None:
        """Replace only the media renderer with byte-bearing synthetic artifacts."""
        root = Path(directory)
        (root / "final.mp4").write_bytes(b"TEST completed base")
        (root / "base.fingerprint.json").write_text(json.dumps(self.record))
        (root / "timeline_map.json").write_text("{}")
        (root / "render_report.json").write_text("{}")
        (root / "cover.png").write_bytes(b"TEST cover")

    def test_auto_base_without_fingerprint_promotes_and_reuses_exact_receipt(self) -> None:
        self.base.unlink()
        args = self.parse()
        expected = self.root / "base.fingerprint.json"
        self.assertEqual(args.fingerprint, str(expected))
        with patch.object(assemble_base_rebuild, "_run_renderer", side_effect=self.render_fixture), \
                contextlib.redirect_stdout(io.StringIO()):
            _, state = assemble.ensure_base(args.base, args.plan_path, self.plan,
                args.fingerprint, assemble.BaseManifest(args.manifest))
        self.assertEqual(state, "rebuilt")
        self.assertTrue(expected.is_file())
        self.assertEqual(assemble._base_state(args.base, self.plan, args.fingerprint,
                         assemble.BaseManifest(args.manifest)), "current")
        (self.root / "fixture-source.mov").write_bytes(b"changed source")
        self.assertEqual(assemble._base_state(args.base, self.plan, args.fingerprint,
                         assemble.BaseManifest(args.manifest)), "stale")

    def test_explicit_receipt_location_is_preserved(self) -> None:
        self.assertEqual(self.parse(["--fingerprint", "explicit.json"]).fingerprint, "explicit.json")

    def test_default_is_beside_selected_base_not_plan_or_working_directory(self) -> None:
        self.argv[1] = str(self.root / "elsewhere" / "base.mp4")
        self.assertEqual(self.parse().fingerprint, str(self.root / "elsewhere" / "base.fingerprint.json"))


if __name__ == "__main__":
    unittest.main()
