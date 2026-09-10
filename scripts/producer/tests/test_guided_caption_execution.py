"""Pure/stub live-completion and O_EXCL sidecar faults, never media approval."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from _guided_caption_fixture import fixture, guard
from guided_caption_dependencies import hold_caption_file
from guided_caption_execution import OwnedCaptionExecution, read_owned_caption_support
from guided_caption_projection import capture_caption_projection
from graphics.owned_execution import OwnedGraphicsExecution, current
from assemble import _assemble_captioned


class CaptionExecutionTests(unittest.TestCase):
    """Only a trusted live callback, never serialized metadata, can finish this path."""

    def setUp(self) -> None:
        """Use TEST bytes, with the real bounded staging/read helpers."""
        self.temp = tempfile.TemporaryDirectory(prefix="sniper-caption-live-test-")
        self.root = Path(self.temp.name).resolve()
        ctx, binding = fixture(self.root)
        self.plan, self.plan_path = ctx.plan, binding.plan.path
        self.held = capture_caption_projection(ctx, binding, guard)
        self.candidate = self.root / "candidate"
        self.candidate.mkdir()
        self.output = str(self.candidate / "final.mp4")
        self.owner = OwnedCaptionExecution(self.held, guard)

    def tearDown(self) -> None:
        """Remove only this test's isolated files."""
        self.temp.cleanup()

    def proof(self) -> dict:
        """Explicit TEST fake media proof; never exposed to a real admission call."""
        Path(self.output).write_bytes(b"TEST fake encoded media")
        row = hold_caption_file(Path(self.output), guard)
        return {"outputPath": self.output, "output": {"path": self.output, "sha256": row.sha256, "size_bytes": row.size_bytes},
            "deliveryApproved": False, "prefixOracle": {"layerPolicy": {"fullCaptionTail": len(self.owner.clips())}}}

    def test_missing_completion_and_serialized_owner_never_skip(self) -> None:
        self.owner.stage(self.output)
        with self.assertRaisesRegex(RuntimeError, "live combined"):
            self.owner.finish(self.output)
        fake = OwnedGraphicsExecution(lambda *_: {}, lambda *_: {}, guard, {"burned": True})
        with self.assertRaisesRegex(RuntimeError, "live internal"):
            current(SimpleNamespace(owned_graphics=fake))

    def test_wrong_output_page_and_late_support_mutation_reject(self) -> None:
        self.owner.stage(self.output)
        proof = self.proof()
        for field, value in (("outputPath", str(self.root / "elsewhere")), ("deliveryApproved", True)):
            with self.assertRaises(RuntimeError):
                self.owner.complete(self.output, {**proof, field: value})
        proof["prefixOracle"]["layerPolicy"]["fullCaptionTail"] = 1
        with self.assertRaises(RuntimeError):
            self.owner.complete(self.output, proof)
        proof["prefixOracle"]["layerPolicy"]["fullCaptionTail"] = 2
        self.owner.complete(self.output, proof)
        self.assertTrue(self.owner.finish(self.output)["burned"])
        (self.candidate / "captions.srt").write_bytes(b"changed")
        with self.assertRaises(RuntimeError):
            self.owner.finish(self.output)

    def test_collision_is_never_replaced_or_repaired(self) -> None:
        path = self.candidate / "captions.srt"
        path.write_bytes(b"TEST existing user bytes")
        with self.assertRaises(FileExistsError):
            self.owner.stage(self.output)
        self.assertEqual(path.read_bytes(), b"TEST existing user bytes")
        with self.assertRaises(RuntimeError):
            self.owner.finish(self.output)

    def test_live_branch_bypasses_all_legacy_cache_and_burn_calls(self) -> None:
        hooks = OwnedGraphicsExecution(lambda *_: {}, lambda *_: {}, guard, self.owner)
        job = SimpleNamespace(out=self.output, owned_graphics=hooks, plan=self.plan, plan_path=self.plan_path)
        def actual_stub(_job: object) -> dict:
            """Mark TEST callback completion only after its fake output was written."""
            self.owner.complete(self.output, self.proof())
            return {"TEST": True}
        with patch("assemble._composite", side_effect=actual_stub), \
                patch("captions.caption_assemble.restore_caption_free_composite", side_effect=AssertionError("restore")), \
                patch("captions.caption_assemble.checkpoint_caption_free_composite", side_effect=AssertionError("checkpoint")), \
                patch("captions.caption_assemble.project_caption_track", side_effect=AssertionError("burn")):
            result = _assemble_captioned(job)
        self.assertTrue(result["captions"]["duplicateCaptionEncodeSkipped"])
        self.assertFalse((self.candidate / ".caption-free-composite.mp4").exists())
        self.assertTrue(read_owned_caption_support(self.held, self.candidate, guard))

    def test_uncaptioned_or_other_candidate_cannot_acquire_live_tail(self) -> None:
        for plan, path in (({**self.plan, "captions": {"burn": False}}, self.plan_path),
                           (self.plan, str(self.root / "other.json"))):
            with self.assertRaisesRegex(RuntimeError, "exact original"):
                self.owner.assert_plan(plan, path)


if __name__ == "__main__":
    unittest.main()
