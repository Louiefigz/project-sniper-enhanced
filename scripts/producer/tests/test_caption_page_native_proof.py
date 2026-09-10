"""Tiny actual page proof equivalence/EOF/deadline regressions; no approval."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import captions.caption_page_decode as decoder
from _caption_page_ab_support import PageCommandRecorder, TestPageDeadline, write_json, write_new
from _caption_page_legacy_proof import LegacyPageProofContext, legacy_page_proof
from caption_page_ab import _equivalent
from headless.process_runner import ProcessDeadlineError, ProcessRequest, run_text
from palmier.process_deadline import use_process_deadline


class NativePageProofTests(unittest.TestCase):
    """Retain every tiny fixture and exact old/new pipes, including failures."""

    @classmethod
    def setUpClass(cls) -> None:
        """Use installed local tools only; unavailable tools skip this native suite."""
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            raise unittest.SkipTest("installed ffmpeg/ffprobe required")
        cls.root = Path(tempfile.mkdtemp(prefix="sniper-page-proof-regression-", dir="/private/tmp"))
        cls.tools = {name: {"path": str(Path(shutil.which(name)).resolve())}
                     for name in ("ffmpeg", "ffprobe")}
        print("retained native caption page proof:", cls.root, flush=True)

    def setUp(self) -> None:
        """Scope exact child records to this new TEST inventory."""
        self.directory = self.root / self._testMethodName
        self.directory.mkdir(mode=0o700)
        self.ledger = self.directory / "processes.jsonl"
        self.environment = patch.dict(os.environ, {"SNIPER_OWNED_PROCESS_LEDGER": str(self.ledger)})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def tearDown(self) -> None:
        """Require matching normal/timeout reap records and actual group absence."""
        rows = [json.loads(line) for line in self.ledger.read_text().splitlines()]
        spawned = [row["pid"] for row in rows if row["event"] == "spawned"]
        self.assertEqual(spawned, [row["pid"] for row in rows if row["event"] == "reaped"])
        for pid in spawned:
            with self.assertRaises(ProcessLookupError):
                os.killpg(pid, 0)

    def page(self, name: str, clock: tuple[str, int], visible: bool = True) -> tuple[Path, dict]:
        """Create one bounded native PNG/RGBA TEST page with transparent gaps."""
        rate, frames = clock
        target = self.directory / (name + ".mov")
        source = f"color=c=black@0.0:s=96x64:r={rate},format=rgba"
        if visible:
            source += ",drawbox=x=8:y=20:w=70:h=18:color=white@1:t=fill:replace=1"
            source += ":enable='between(n,1,2)+eq(n,5)'" if frames > 1 else ""
        command = (self.tools["ffmpeg"]["path"], "-nostdin", "-v", "error", "-f", "lavfi",
                   "-i", source, "-frames:v", str(frames), "-an", "-c:v", "png", "-pix_fmt",
                   "rgba", "-r", rate, "-fps_mode", "cfr", "-threads", "1", str(target))
        process = run_text(ProcessRequest(command, "", str(self.directory), dict(os.environ),
                                          10, max_output_bytes=1048576))
        self.assertEqual(process.returncode, 0, process.stderr)
        return target, {"codec_name": "png", "pix_fmt": "rgba", "width": 96, "height": 64,
                        "r_frame_rate": rate, "nb_read_frames": str(frames)}

    def pair(self, media: Path, facts: dict, name: str) -> tuple[Path, dict]:
        """Run both real algorithms under one decreasing TEST deadline."""
        output = self.directory / name
        output.mkdir(mode=0o700)
        results = {}
        with use_process_deadline(TestPageDeadline(time.monotonic() + 15)):
            for label in ("old", "new"):
                recorder = PageCommandRecorder(output, str(self.directory), label)
                results[label] = self.observed(label, (media, facts), recorder)
        write_json(output / "actual-results.json", results)
        return output, results

    def observed(self, label: str, inputs: tuple[Path, dict], recorder: PageCommandRecorder) -> dict:
        """Retain a failed actual leg without normalizing it into successful proof."""
        try:
            return {"status": "complete", "proof": self.algorithm(label, inputs, recorder)}
        except RuntimeError as error:
            return {"status": "failed", "error": str(error)}

    def algorithm(self, label: str, input_pair: tuple[Path, dict], recorder: PageCommandRecorder) -> dict:
        """Observe actual return channels; patches record but never fake tool output."""
        media, facts = input_pair
        if label == "old":
            return legacy_page_proof(str(media), LegacyPageProofContext(facts, self.tools, recorder.old_command))
        with patch.object(decoder, "run_text", recorder):
            return decoder.decode_caption_page(str(media), self.tools, facts)

    def test_integer_ntsc_single_frame_and_transparent_gaps(self) -> None:
        """Public proof and every raw hash/alpha byte equal the original algorithm."""
        for rate, frames in (("30/1", 1), ("30000/1001", 1), ("30/1", 6), ("30000/1001", 6)):
            name = rate.replace("/", "-") + "-" + str(frames)
            media, facts = self.page(name, (rate, frames))
            output, results = self.pair(media, facts, name)
            _equivalent(output, results)
            self.assertEqual((output / "old-02.stdout").read_bytes(), (output / "new-01.stderr").read_bytes())

    def test_actual_defects_reject_without_positive_proof(self) -> None:
        """Truncation, late packet damage, missing last frame, empty alpha and stale facts reject."""
        media, facts = self.page("valid", ("30/1", 6))
        missing, _ = self.page("missing", ("30/1", 5))
        empty, _ = self.page("empty", ("30/1", 6), False)
        raw = media.read_bytes()
        damaged = bytearray(raw)
        at = damaged.rfind(b"IDAT")
        self.assertGreater(at, 8)
        damaged[at + 6] ^= 255
        corrupt, truncated = self.directory / "corrupt.mov", self.directory / "truncated.mov"
        write_new(corrupt, bytes(damaged))
        write_new(truncated, raw[:-128])
        cases = [(missing, facts), (empty, facts), (corrupt, facts), (truncated, facts),
                 (media, {**facts, "width": 98}), (media, {**facts, "r_frame_rate": "30000/1001"})]
        for index, (path, expected) in enumerate(cases):
            _, results = self.pair(path, expected, "defect-" + str(index))
            self.assertTrue(all(row["status"] == "failed" for row in results.values()))
            self.assertTrue(results["new"]["error"].startswith("caption page "))

    def test_actual_child_deadline_never_returns_proof(self) -> None:
        """A real spawned probe times out under original credit and is group-reaped."""
        media, facts = self.page("timeout", ("30/1", 6))
        deadline = TestPageDeadline(time.monotonic() + 0.001)
        with use_process_deadline(deadline), self.assertRaises(ProcessDeadlineError):
            decoder.decode_caption_page(str(media), self.tools, facts)
        self.assertLessEqual(deadline.expires_at, time.monotonic())
        rows = [json.loads(line) for line in self.ledger.read_text().splitlines()]
        self.assertEqual(sum(row["event"] == "spawned" for row in rows), 2)


if __name__ == "__main__":
    unittest.main()
