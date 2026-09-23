"""Actual crop quality, fractional clocks and unchanged PCM through fused cuts."""
from __future__ import annotations

import contextlib
import io
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from cut_reframe import select_fusion
from cut_speed import CutSpeedOptions, render_cut_speed_opts
from media_probe import probe_video, probe_video_frames
from motion.reframe import reframe_uniform


def native(arguments: list[str]) -> subprocess.CompletedProcess:
    """Run local FFmpeg, surfacing real media errors in the fixture."""
    return subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "info", *arguments],
                          capture_output=True, text=True, check=True)


def pcm_hash(path: Path) -> str:
    """Compare the actual decoded float samples, not container bytes."""
    return native(["-i", str(path), "-map", "0:a", "-c:a", "pcm_f32le",
                   "-f", "hash", "-hash", "sha256", "-"]).stdout.strip()


def compare_case(root: Path, shape: str, fps: str) -> dict:
    """Render the original two-pass path and the qualified fused path."""
    source = root / "source.mp4"
    native(["-f", "lavfi", "-i", f"testsrc2=s={shape}:r={fps}:d=2.5",
            "-f", "lavfi", "-i", "sine=f=523:r=48000:d=2.5", "-c:v", "libx264",
            "-preset", "ultrafast", "-crf", "16", "-c:a", "aac", str(source)])
    plan = {"target": {"mode": "short"}, "reframe": {"strategy": "center"}, "cutTrack": [
        {"sourceId": "s", "start": .211, "end": .684},
        {"sourceId": "s", "start": .943, "end": 1.384, "speed": 1.25, "audioLeadMs": 80},
        {"sourceId": "s", "start": 1.631, "end": 2.291}]}
    manifest = {"sources": [{"id": "s", "path": str(source)}]}
    selected = select_fusion(SimpleNamespace(plan=plan, manifest=manifest, resume=False), False)
    results = []
    for name, fusion in (("original", None), ("fused", selected)):
        directory = root / name
        directory.mkdir()
        output = directory / "mezz.mp4"
        with contextlib.redirect_stdout(io.StringIO()):
            proof = render_cut_speed_opts(plan, manifest, str(output), CutSpeedOptions(str(directory), reframe=fusion))
        hashes = [pcm_hash(path) for path in sorted(directory.glob("part_*.mp4"))]
        if fusion is None:
            framed = directory / "framed.mp4"
            reframe_uniform(str(output), str(framed), "center")
            output = framed
        results.append({"output": output, "proof": proof, "pcm": hashes})
    return {"results": results, "fps": fps}


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class FusedCutMediaTests(unittest.TestCase):
    """Synthetic media proves geometry and clocks, independently of release footage."""

    @classmethod
    def setUpClass(cls) -> None:
        """Cover both integer/NTSC clocks and landscape/portrait crop shapes."""
        cls.temp = tempfile.TemporaryDirectory(prefix="sniper-fused-media-")
        cls.cases = []
        for index, (shape, fps) in enumerate((("2560x1440", "30000/1001"), ("1440x2560", "30"))):
            directory = Path(cls.temp.name) / str(index)
            directory.mkdir()
            cls.cases.append(compare_case(directory, shape, fps))

    @classmethod
    def tearDownClass(cls) -> None:
        """Dispose synthetic media after all output checks."""
        cls.temp.cleanup()

    def test_exact_frame_and_pcm_clocks(self) -> None:
        """Crop fusion never alters J-cut, retime or cumulative sample boundaries."""
        for case in self.cases:
            old, new = case["results"]
            self.assertEqual(probe_video_frames(str(old["output"])), probe_video_frames(str(new["output"])))
            self.assertEqual(old["pcm"], new["pcm"])
            self.assertEqual(probe_video(str(new["output"]))["width"], 1080)
            self.assertEqual(probe_video(str(new["output"]))["height"], 1920)

    def test_same_crop_and_high_picture_similarity(self) -> None:
        """One fewer CRF generation may change pixels but must preserve the intended crop."""
        for case in self.cases:
            old, new = case["results"]
            result = native(["-i", str(old["output"]), "-i", str(new["output"]),
                "-lavfi", "[0:v]setpts=PTS-STARTPTS[a];[1:v]setpts=PTS-STARTPTS[b];[a][b]ssim",
                "-an", "-f", "null", "-"])
            score = float(re.findall(r"All:([0-9.]+)", result.stderr)[-1])
            self.assertGreater(score, .98)

    def test_completed_receipt_contains_both_native_commands_and_clock(self) -> None:
        """The published record includes actual clamp argv, tools and source bytes."""
        for case in self.cases:
            new = case["results"][1]
            receipt = new["proof"]["executionReceipt"]
            self.assertIn("version", receipt["environment"]["tools"]["ffmpeg"])
            self.assertEqual(len(receipt["stageCommands"]), 1)
            frames = 0
            for part in receipt["parts"]:
                self.assertEqual(part["framesBefore"], frames)
                self.assertEqual(len(part["commands"]), 2)
                clamp = part["commands"][1]["attempts"][0]["argv"]
                self.assertIn("atrim=end_sample=", clamp[clamp.index("-af") + 1])
                self.assertEqual(len(part["executionKey"]), 64)
                frames += part["videoFrames"]
            disk = json.loads((new["output"].parent / "cut_execution.json").read_text())
            self.assertEqual(disk, receipt)
