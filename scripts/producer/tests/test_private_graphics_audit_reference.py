"""Exact private graphics-free audit references, including actual tiny assembly.

TEST synthetic graphic pixels only: not HyperFrames/OCI or creator qualification.
"""
from __future__ import annotations

import contextlib
import shutil
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from _cut_preview_fixture import ffmpeg
from assemble import assemble
from audio import assemble_source_audio as source
from audit import audit_composite_visual as visual
from cut_preview_io import bound_json, file_hash
from graphics.owned_execution import GraphicsComposition, OwnedGraphicsExecution
from opening_prefix_composition import PrefixCompositionJob, compose_verified_prefix
from opening_prefix_contract import CompositorPrefixRequest, PrefixClock, PrefixOracleRuntime, PrefixRanges
import test_held_program_preparation as preparation_fixture
from test_opening_prefix_contract import held


class PrivateReferenceBoundaryTests(unittest.TestCase):
    def candidate(self) -> SimpleNamespace:
        """A plainly synthetic control seam; no media or held admission claimed."""
        return SimpleNamespace(directory=Path("/TEST/private"),
            job=SimpleNamespace(base="/TEST/actual-base.mp4", plan={"graphicsTrack": [{"kind": "TEST"}]}),
            preparation=SimpleNamespace(selection=SimpleNamespace(event={"baseSha256": "a" * 64})))

    def test_exact_held_base_is_passed_without_copy_or_directory_discovery(self) -> None:
        """Forward exact held bytes without creating a second reference artifact."""
        with patch.object(source, "file_hash", return_value="a" * 64) as hashes, \
                patch.object(source, "run_audit", return_value="TEST report") as audit:
            self.assertEqual(source._run_candidate_audit(self.candidate()), "TEST report")
        audit.assert_called_once_with("/TEST/private", graphics_reference="/TEST/actual-base.mp4")
        self.assertEqual(hashes.call_count, 2)

    def test_different_base_rejects_before_audit_and_late_change_rejects_after(self) -> None:
        """Reject wrong initial bytes and changes made during the complete audit."""
        for values, count in ((["b" * 64], 0), (["a" * 64, "b" * 64], 1)):
            with self.subTest(values=values), patch.object(source, "file_hash", side_effect=values), \
                    patch.object(source, "run_audit") as audit, self.assertRaisesRegex(RuntimeError, "visual QC base"):
                source._run_candidate_audit(self.candidate())
            self.assertEqual(audit.call_count, count)

    def test_explicit_missing_base_cannot_fall_back_to_discovered_reference(self) -> None:
        """Missing explicit input remains failure even when discovery is available."""
        frame = visual.FrameRef("graphic0_mid", "graphic", 1, "/TEST/final.jpg")
        plan = {"graphicsTrack": [{"kind": "TEST"}]}
        with patch.object(visual, "_reference_path") as discover, \
                patch.object(visual, "extract_review_frames", return_value=[]) as extract:
            checks = visual.check_composite_visuals("/TEST/private", plan, [frame], "/TEST/missing.mp4")
        discover.assert_not_called()
        self.assertEqual(extract.call_args.args[0], "/TEST/missing.mp4")
        self.assertEqual(next(row for row in checks if row.name == "graphic_composite_reference").status, "fail")


def _graphic_fixture(root: Path) -> tuple[dict, dict]:
    """Declare one actual takeover before preparing its immutable whole base."""
    from test_render_source_audio_media import _fixture
    plan, manifest = _fixture(root)
    plan["graphicsTrack"] = [{"kind": "statement-card", "anchor": "own-screen",
        "outStart": 0.5005, "outEnd": 3.003, "exitOnCut": False,
        "reason": "TEST ONLY native compositor and graphics-free reference QC fixture.",
        "spec": {"text": "TEST ONLY", "variant": "classic"}}]
    return plan, manifest


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires FFmpeg")
class PrivateReferenceActualAssemblyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        """Local subclass avoids importing/discovering the helper's test cases."""
        class GraphicPreparation(preparation_fixture.HeldPreparationTests):
            pass
        with patch.object(preparation_fixture, "_fixture", side_effect=_graphic_fixture):
            GraphicPreparation.setUpClass()
        cls.fixture = GraphicPreparation()

    def test_actual_one_graphic_held_assembly_has_reference_pixels_and_presence(self) -> None:
        """Exercise real reference extraction and presence checks in full assembly."""
        job = self.fixture.job("actual-graphic-body")
        bus = self.fixture.selection.master.source_bus
        job.graphic_frame_clock = (bus.frame_rate, bus.frames)
        asset = self.fixture.root / "TEST-synthetic-graphic.mp4"
        ffmpeg(["-f", "lavfi", "-i", f"testsrc2=size=160x90:rate={bus.frame_rate}:duration=3",
            "-vf", "hue=s=0", "-frames:v", "90", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(asset)])
        runtime = PrefixOracleRuntime(held(Path(shutil.which("ffmpeg"))),
            held(Path(shutil.which("ffprobe"))), str(self.fixture.root), 30)

        def render(entry: dict, order: int) -> dict:
            """Return only the deliberately generated native TEST fixture asset."""
            self.assertEqual((entry["kind"], order), ("statement-card", 0))
            return {"path": str(asset), "kind": entry["kind"], "key": "TEST-only", "fmt": "mp4", "cached": False}

        def compose(value: GraphicsComposition) -> dict:
            """Compare and encode the actual unchanged native TEST composition."""
            request = CompositorPrefixRequest(held(Path(value.video_in)), (held(asset),), value.clips, value.clips,
                PrefixClock(*value.frame_clock, *value.canvas), PrefixRanges((0, 100), (0, 110)))
            end = time.monotonic() + 30
            return compose_verified_prefix(PrefixCompositionJob(request, runtime, value.video_out, lambda: end - time.monotonic()))

        job.owned_graphics = OwnedGraphicsExecution(render, compose, lambda: None)
        base_sha = file_hash(Path(job.base))
        with patch.object(source, "build_program_master", side_effect=AssertionError("no remaster")), \
                (self.fixture.root / "actual-graphic-body.log").open("w") as log, contextlib.redirect_stdout(log):
            result = assemble(job)
        audit = bound_json(Path(job.out).parent / "audit_report.json")
        checks = {row["name"]: row["status"] for row in audit["checks"]}
        self.assertEqual(checks["graphic_composite_reference"], "pass")
        self.assertEqual(checks["graphic_composite_0_presence"], "pass")
        self.assertEqual(audit["counts"]["fail"], 0)
        self.assertTrue(list(Path(job.out).parent.glob(".source-assembly-v2-*/audit_reference/audit_frames/*.jpg")))
        self.assertFalse((Path(job.out).parent / "base_final.mp4").exists())
        self.assertEqual(file_hash(Path(job.base)), base_sha)
        self.assertFalse(result["preparationReuse"]["programRemastered"])
        self.assertTrue(result["delivery"]["qualified"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
