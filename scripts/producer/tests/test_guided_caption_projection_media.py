"""Actual tiny returned caption projection; no guided execution/approval claim."""
from __future__ import annotations

import contextlib
import hashlib
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import render as renderer
from audio.render_audio_authority import SOURCE_FLOAT_POLICY_V2
from captions.caption_page_contract import validate_caption_page_manifest
from captions.caption_shard_authority import validate_bound_shards
from guided_caption_dependencies import hold_caption_file
from guided_caption_projection import (CaptionProjectionBinding, capture_caption_projection,
                                       read_caption_projection, stage_caption_dependencies)
from guided_opening_execution import opening_clock
from test_assemble_source_audio_caption_media import _inputs
from test_render_source_audio_media import _context


class ActualHeldCaptionProjectionTests(unittest.TestCase):
    """Reuse the existing synthetic NTSC source/ordinary renderer, no OCI calls."""

    @classmethod
    def setUpClass(cls) -> None:
        """Retain actual failed/successful artifacts and all measured phase timings."""
        cls.root = Path(tempfile.mkdtemp(prefix="sniper-held-caption-media-", dir="/private/tmp"))
        print("retained actual caption projection:", cls.root, flush=True)
        cls.clock, cls.started = opening_clock(90), time.monotonic()
        try:
            cls.clock.phase("synthetic-inputs", cls._prepare)
            with (cls.root / "render.log").open("w") as log, contextlib.redirect_stdout(log):
                cls.clock.phase("actual-ordinary-base-caption-projection", lambda: renderer.render(cls.ctx))
            cls.output = Path(cls.ctx.out_dir)
            cls.before = cls._inventory()
            cls.binding = cls._binding()
            cls.held = cls.clock.phase("capture-held-caption", lambda: capture_caption_projection(cls.ctx, cls.binding, cls.guard))
            cls.clock.phase("read-held-caption", lambda: read_caption_projection(cls.held, cls.binding, cls.guard))
            cls.staged = cls.clock.phase("stage-held-caption-audit", lambda: stage_caption_dependencies(
                cls.held, cls.binding, cls.root / "new-audit-support", cls.guard))
            cls._record("complete")
        except Exception as error:
            cls._record("failed", str(error))
            raise

    @classmethod
    def guard(cls) -> None:
        """Every helper consumes this single fixture's original remaining clock."""
        cls.clock.remaining()

    @classmethod
    def _prepare(cls) -> None:
        """Build actual synthetic input; do not change an existing project/receipt."""
        _base, manifest, plan = _inputs(cls.root)
        path = Path(manifest["_path"])
        path.write_text(json.dumps({key: value for key, value in manifest.items() if key != "_path"}))
        cls.ctx = _context(cls.root, plan, manifest, SOURCE_FLOAT_POLICY_V2)
        cls.ctx.skip_graphics = True

    @classmethod
    def _binding(cls) -> CaptionProjectionBinding:
        """Hold actual source-facing files; the fixture grants no guided source authority."""
        dependencies = [hold_caption_file(Path(row["transcriptPath"]), cls.guard)
                        for row in cls.ctx.manifest["sources"] if row.get("transcriptPath")]
        return CaptionProjectionBinding(hold_caption_file(Path(cls.ctx.plan_path), cls.guard),
            hold_caption_file(Path(cls.ctx.manifest["_path"]), cls.guard),
            hold_caption_file(cls.output / "timeline_map.json", cls.guard),
            ("30000/1001", cls.ctx.source_audio_bus.frames, 1920, 1080), tuple(dependencies), "d" * 64)

    @classmethod
    def _inventory(cls) -> dict:
        """Hash full original base/caption/work inventory and actual admitted sources."""
        paths = {path for path in cls.output.rglob("*") if path.is_file()}
        paths.update(Path(row["path"]) for row in cls.ctx.manifest["sources"])
        return {str(path): (hold_caption_file(path, cls.guard).sha256 if path.stat().st_size
                           else hashlib.sha256(b"").hexdigest()) for path in sorted(paths)}

    @classmethod
    def _record(cls, status: str, error: str | None = None) -> None:
        """Keep explicit actual work scope and failures, without source/QC approval."""
        value = {"status": status, "error": error, "stages": cls.clock.events,
            "elapsedMs": (time.monotonic() - cls.started) * 1000,
            "scope": "actual-caption-projection-helper-not-guided-worker-or-approval"}
        (cls.root / "helper-evidence.json").write_text(json.dumps(value, indent=2))

    def test_actual_full_cues_pages_and_current_staged_audit_contract(self) -> None:
        """Actual returned alpha media survives the same existing caption validators."""
        held = self.held
        self.assertEqual(len(held.data["compilation"]["cues"]), 2)
        self.assertTrue(held.data["authority"]["burnExpected"])
        self.assertIsNone(validate_bound_shards(str(self.root / "new-audit-support"), held.data["authority"]))
        self.assertEqual(validate_caption_page_manifest(held.data["pages"], held.root,
            held.data["authority"]), held.data["pages"])
        self.assertEqual(self.before, self._inventory())

    def test_actual_read_and_stage_never_render_again(self) -> None:
        """Existing materializers/cache mutation/compilation cannot execute on readback."""
        with patch("captions.caption_shards.materialize_caption_shards", side_effect=AssertionError("render")), \
                patch("captions.caption_pages._current", side_effect=AssertionError("cache")), \
                patch("captions.caption_plan_pipeline.compile_plan_caption_track", side_effect=AssertionError("compile")):
            self.assertIs(read_caption_projection(self.held, self.binding, self.guard), self.held)
        self.assertEqual(self.before, self._inventory())


if __name__ == "__main__":
    unittest.main()
