"""Exact held-assembly frame opt-in; synthetic marker media, no catalog or ASR."""
from __future__ import annotations

import contextlib
import copy
import io
import shutil
import subprocess
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from assemble import AssembleJob, assemble, _composite
from audio.assemble_source_audio import _staged_job
from audio.held_program_preparation import _inputs
from cut_preview_io import file_hash, write_new
from graphics import graphics_stage as stage
from graphics.frame_quantization import bind_graphic_frame_windows


class HeldGraphicClockTests(unittest.TestCase):
    def test_unheld_clock_rejects_before_any_assembly(self) -> None:
        for policy in ("legacy-v1", "source-float-v2"):
            job = AssembleJob("/TEST/base", {}, "/TEST/final", None, audio_clock_policy=policy)
            job.graphic_frame_clock = ("30", 60)
            with self.subTest(policy=policy), patch("audio.assemble_source_audio.assemble_source_audio") as render:
                with self.assertRaisesRegex(RuntimeError, "held.*clock|clock.*held"):
                    assemble(job)
                render.assert_not_called()

    def test_import_clock_must_equal_actual_held_bus(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            root = Path(temporary)
            plan = {"graphicsTrack": []}
            source = root / "plan.json"
            write_new(source, plan)
            context = SimpleNamespace(base_path=root / "base.mp4", manifest_path=root / "manifest.json", artifact_root=root)
            bus = SimpleNamespace(frame_rate="30000/1001", frames=120, receipt={"receiptHash": "a" * 64})
            selected = SimpleNamespace(context=context, event={"planSha256": file_hash(source)}, plan=plan,
                                       master=SimpleNamespace(source_bus=bus))
            job = AssembleJob(str(context.base_path), plan, str(root / "out.mp4"), None,
                fingerprint_path=str(root / "base.fingerprint.json"), manifest=str(context.manifest_path),
                plan_path=str(source), audio_clock_policy="source-float-v2", held_program_selection=("/TEST/event", "a" * 64))
            for clock in [("30", 120), ("30000/1001", 119), ["30000/1001", 120], ("", 120), ("NaN", 120), ("30", True)]:
                job.graphic_frame_clock = clock
                with self.subTest(clock=clock), self.assertRaises((RuntimeError, ValueError)):
                    _inputs(job, selected)
            job.graphic_frame_clock = ("30000/1001", 120)
            _inputs(job, selected)

    def test_clock_and_empty_frame_spans_reject_before_render(self) -> None:
        entry = {"outStart": 0.1, "outEnd": 0.101}
        job = stage.GraphicsJob("/TEST/base", "/TEST/out", [entry])
        job.graphic_frame_clock = ("24", 24)
        with patch.object(stage, "_clip_fps", return_value=Fraction(24)), \
                patch.object(stage, "_probe_frames", return_value=24), patch.object(stage, "_render_all") as render:
            with self.assertRaisesRegex((RuntimeError, ValueError), "frame"):
                stage.run_graphics_stage(job)
            render.assert_not_called()

    def test_frame_mapping_matches_approved_half_up_map_without_mutating_rows(self) -> None:
        rows = [{"outStart": 1 + 2 / 30, "outEnd": 1.5, "path": "/TEST/clip"}]
        self.assertEqual(bind_graphic_frame_windows(rows, ("30", 60)), [
            {**rows[0], "startFrame": 32, "endFrameExclusive": 45}])
        self.assertNotIn("startFrame", rows[0])
        for row in [{"outStart": -0.1, "outEnd": 1}, {"outStart": 1, "outEnd": 3},
                    {"outStart": 0, "outEnd": 0.001}, {"outStart": True, "outEnd": 1},
                    {"outStart": 0, "outEnd": 1, "endFrameExclusive": 31}]:
            with self.subTest(row=row), self.assertRaises(ValueError):
                bind_graphic_frame_windows([row], ("30", 60))

    def test_stage_clock_mismatch_and_frame_loss_fail_without_fallback(self) -> None:
        job = stage.GraphicsJob("/TEST/base", "/TEST/out", [])
        job.graphic_frame_clock = ("24", 24)
        with patch.object(stage, "_clip_fps", return_value=Fraction(30)), \
                patch.object(stage, "_probe_frames", return_value=24), patch.object(stage, "_passthrough") as render:
            with self.assertRaisesRegex(ValueError, "differs"):
                stage.run_graphics_stage(job)
            render.assert_not_called()
        with patch.object(stage, "_probe_frames", return_value=25):
            with self.assertRaisesRegex(RuntimeError, "tolerance 0"):
                stage._verified_frame_count(job, 24)
            job.graphic_frame_clock = None
            self.assertEqual(stage._verified_frame_count(job, 24), 25)

    def test_staging_and_assembly_forward_opt_in_without_using_opening_cache(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as temporary:
            plan = {"target": {"mode": "longform"}, "graphicsTrack": []}
            job = AssembleJob("/TEST/base", plan, "/TEST/output", "/TEST/retained-cache", audio_clock_policy="source-float-v2",
                              held_program_selection=("/TEST/event", "a" * 64), graphic_frame_clock=("24", 24))
            candidate = SimpleNamespace(job=job, directory=Path(temporary), preparation=object())
            staged = _staged_job(candidate)
            self.assertEqual(staged.graphic_frame_clock, ("24", 24))
            self.assertEqual(staged.cache_dir, str(Path(temporary) / "graphics-cache"))
            with patch.object(stage, "run_graphics_stage", return_value={"passes": 1}) as render, \
                    patch("assemble._probe_fps", return_value=24), patch("assemble._read_inline_ydif", return_value=0), \
                    contextlib.redirect_stdout(io.StringIO()):
                _composite(staged)
            self.assertEqual(render.call_args.args[0].graphic_frame_clock, ("24", 24))


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires actual FFmpeg")
class HeldGraphicFrameMediaTests(unittest.TestCase):
    def run_marker(self, rate: str, exact: bool) -> tuple[list[bool], dict]:
        """Decode actual compositor pixels; the supplied marker is TEST-only media."""
        with tempfile.TemporaryDirectory(prefix="sniper-held-frames-") as temporary:
            root = Path(temporary)
            self.make_color(root / "base.mp4", "blue", rate)
            self.make_color(root / "marker.mp4", "red", rate)
            fps = float(Fraction(rate))
            entry = {"outStart": 4 / fps, "outEnd": 10 / fps, "anchor": "own-screen"}
            clip = {**entry, "path": str(root / "marker.mp4"), "x": 0, "y": 0}
            job = stage.GraphicsJob(str(root / "base.mp4"), str(root / "final.mp4"), [entry], eof_pass=True)
            if exact:
                job.graphic_frame_clock = (rate, 24)
            before = copy.deepcopy(entry)
            with patch.object(stage, "_render_all", return_value=([clip], [])), \
                    patch.object(stage, "run_verify"), contextlib.redirect_stdout(io.StringIO()):
                result = stage.run_graphics_stage(job)
            self.assertEqual(entry, before)
            raw = subprocess.run(["ffmpeg", "-v", "error", "-i", job.video_out, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                 capture_output=True, check=True, timeout=15).stdout
            stride = 64 * 36 * 3
            self.assertEqual(len(raw), 24 * stride)
            red = [raw[index * stride] > raw[index * stride + 2] for index in range(24)]
            return red, result

    @staticmethod
    def make_color(path: Path, color: str, rate: str) -> None:
        """Make an overlong marker so the compositor's window alone decides visibility."""
        subprocess.run(["ffmpeg", "-v", "error", "-n", "-f", "lavfi", "-i", f"color={color}:s=64x36:r={rate}",
            "-frames:v", "24", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)],
            capture_output=True, check=True, timeout=15)

    def test_exact_first_last_and_outside_frames_at_integer_and_ntsc_rate(self) -> None:
        for rate in ("24", "30000/1001"):
            with self.subTest(rate=rate):
                red, result = self.run_marker(rate, True)
                self.assertEqual(red, [4 <= frame < 10 for frame in range(24)])
                self.assertEqual(result["frames_in"], result["frames_out"])

    def test_ordinary_default_still_uses_legacy_gate(self) -> None:
        red, _result = self.run_marker("24", False)
        self.assertEqual(red, [5 <= frame <= 10 for frame in range(24)])


if __name__ == "__main__":
    unittest.main()
