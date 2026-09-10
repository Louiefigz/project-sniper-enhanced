"""Real still-content oracles and fault cases; no reduced Audit B sample coverage."""
from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from audit import audit_frame_batch as batch
from audit import audit_frames as frames
from audit.audit_probe import extract_frame, ffprobe_json


def probe() -> dict:
    """Ordinary metadata only; actual media tests use the real FFprobe below."""
    return {"streams": [{"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p",
        "r_frame_rate": "30/1", "avg_frame_rate": "30/1", "start_time": "0", "time_base": "1/15360",
        "width": 320, "height": 180, "sample_aspect_ratio": "1:1"}], "format": {"start_time": "0"}}


class FrameBatchContractTests(unittest.TestCase):
    """All original labels/timestamps survive bounded scheduling and failures."""

    def test_unsupported_streams_keep_serial_selection(self) -> None:
        self.assertTrue(batch.review_batch_eligible(probe()))
        self.assertFalse(batch.review_batch_eligible(None))
        for key, value in [("codec_name", "hevc"), ("pix_fmt", "yuv420p10le"), ("start_time", "2"),
                           ("avg_frame_rate", "17/1"), ("r_frame_rate", "N/A"), ("width", 8192), ("sample_aspect_ratio", "2:1"),
                           ("side_data_list", [{"rotation": 90}])]:
            current = probe()
            current["streams"][0][key] = value
            self.assertFalse(batch.review_batch_eligible(current), key)
        current = probe()
        current["streams"] *= 2
        self.assertFalse(batch.review_batch_eligible(current))
        for malformed in [{}, {"streams": None}, {"streams": [None]}, {"streams": [], "format": []}]:
            self.assertFalse(batch.review_batch_eligible(malformed))
        current = probe()
        current["streams"][0].update(r_frame_rate="12/1", avg_frame_rate="12/1")
        self.assertFalse(batch.review_batch_eligible(current), "unqualified rates retain serial extraction")

    def test_group_limits_order_duplicate_events_and_sparse_seeks(self) -> None:
        requested = [(9.0, "late"), (0.6, "a"), (0.6, "b"), (0.1, "early")]
        groups = batch.group_targets(requested)
        self.assertEqual([[row.index for row in group] for group in groups], [[3, 1, 2], [0]])
        many = batch.group_targets([(index / 100, str(index)) for index in range(20)])
        self.assertTrue(all(len(group) <= 6 for group in many))
        self.assertEqual(sum(map(len, many)), 20)
        self.assertEqual(len(batch.group_targets([(0.0, "a"), (0.7, "b"), (1.4, "c"), (2.1, "d")])), 2)
        self.assertEqual(len(batch.group_targets([(0.0, "a"), (0.8, "b")])), 2)

    def test_failed_batch_does_not_retry_or_select_stale_files(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            targets = [(i / 10, str(Path(folder) / f"{i}.jpg")) for i in range(3)]
            for _, file in targets:
                Path(file).write_bytes(b"old evidence must not count")
            with patch.object(batch, "run_ff", return_value=subprocess.CompletedProcess([], 0)):
                results = batch.extract_nearby_frames("missing", targets, lambda *_: self.fail("no retry"))
            self.assertEqual(results, [False, False, False])
            self.assertTrue(all(Path(file).read_bytes() == b"old evidence must not count" for _, file in targets))

    def test_timeout_propagates_and_deletes_only_private_partial_batch(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            targets = [(i / 10, str(Path(folder) / f"{i}.jpg")) for i in range(3)]
            with patch.object(batch, "run_ff", side_effect=subprocess.TimeoutExpired("ffmpeg", 1)):
                with self.assertRaises(subprocess.TimeoutExpired):
                    batch.extract_nearby_frames("source", targets, lambda *_: self.fail("no retry"))
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_partial_new_batch_never_publishes_or_selects_old_missing_member(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            targets = [(i / 10, str(Path(folder) / f"{i}.jpg")) for i in range(3)]
            old = Path(targets[-1][1])
            old.write_bytes(b"old missing member")

            def partial(command: list[str]) -> subprocess.CompletedProcess:
                for file in [value for value in command if value.endswith(".jpg")][:2]:
                    Image.new("RGB", (16, 16), (255, 0, 0)).save(file, format="JPEG")
                return subprocess.CompletedProcess(command, 0)

            with patch.object(batch, "run_ff", side_effect=partial):
                result = batch.extract_nearby_frames("source", targets, lambda *_: self.fail("no retry"))
            self.assertEqual(result, [False, False, False])
            self.assertEqual(list(Path(folder).iterdir()), [old])
            self.assertEqual(old.read_bytes(), b"old missing member")

    def test_ui_refs_preserve_label_note_order_and_explicit_failures(self) -> None:
        refs = [frames.FrameRef("last", "cut", 1.0, "", "last note"),
                frames.FrameRef("first", "graphic", 0.2, "", "first note")]
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(frames, "extract_nearby_frames", return_value=[True, False]):
                result = frames.extract_review_frames("final", directory, refs, probe())
        self.assertEqual([(row.label, row.timestamp, row.note) for row in result],
                         [(row.label, row.timestamp, row.note) for row in refs])
        self.assertTrue(result[0].path)
        self.assertEqual(result[1].path, "")
        self.assertEqual(frames.check_frame_extraction(result).status, frames.FAIL)


def media(directory: Path, rate: str, size: str = "320x180") -> Path:
    """Fresh real encoded pattern; record setup separately from still extraction."""
    target = directory / f"source-{rate.replace('/', '_')}-{size}.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-n", "-f", "lavfi", "-i",
        f"testsrc2=size={size}:rate={rate}", "-t", "3", "-c:v", "libx264", "-preset", "veryfast",
        "-pix_fmt", "yuv420p", str(target)], check=True, capture_output=True, timeout=30)
    return target


def pixels(file: str) -> str:
    """Compare actual reviewer-visible JPEG pixels, not an assumed frame number."""
    with Image.open(file) as image:
        return hashlib.sha256(image.convert("RGB").tobytes()).hexdigest()


class FrameBatchMediaTests(unittest.TestCase):
    """Retained actual CFR/range/size evidence; no complete-video quality claim."""

    @classmethod
    def setUpClass(cls) -> None:
        """Keep all fixtures, timings and failed outputs for independent review."""
        cls.directory = Path(tempfile.mkdtemp(prefix="sniper-review-batch-media-", dir="/private/tmp"))
        cls.measurements = []
        print(f"REVIEW_BATCH_EVIDENCE={cls.directory}", flush=True)

    @classmethod
    def tearDownClass(cls) -> None:
        """Persist observed measurements even if a later assertion failed."""
        (cls.directory / "measurements.json").write_text(json.dumps(cls.measurements, indent=2))

    def compare(self, rate: str, size: str) -> None:
        """Same media, all declared review times, no downscale or fewer images."""
        source = media(self.directory, rate, size)
        observed = ffprobe_json(str(source))
        self.assertTrue(batch.review_batch_eligible(observed), observed)
        folder = self.directory / source.stem
        folder.mkdir()
        times = [0.2, 0.6, 0.9, 1.0, 1.1, 1.6, 0.999, 1.001, 2.9, 0.6, 0.0]
        requested = [(value, str(folder / f"new-{index}.jpg")) for index, value in enumerate(times)]
        started = time.monotonic()
        previous = [extract_frame(str(source), value, str(folder / f"old-{index}.jpg")) for index, value in enumerate(times)]
        legacy = time.monotonic() - started
        started = time.monotonic()
        current = batch.extract_nearby_frames(str(source), requested, extract_frame)
        elapsed = time.monotonic() - started
        matches = [pixels(str(folder / f"old-{index}.jpg")) == pixels(file) for index, (_, file) in enumerate(requested)]
        self.measurements.append({"rate": rate, "size": size, "samples": len(times), "legacySeconds": legacy,
                                  "batchSeconds": elapsed, "allPixelsEqual": all(matches)})
        self.assertTrue(all(previous) and all(current))
        self.assertEqual(matches, [True] * len(times), (rate, size))

    def test_actual_rate_matrix_preserves_all_decoded_samples(self) -> None:
        for rate in ["24/1", "24000/1001", "25/1", "30000/1001", "30/1", "50/1", "60000/1001", "60/1"]:
            with self.subTest(rate=rate):
                self.compare(rate, "320x180")

    def test_actual_full_size_landscape_portrait_and_4k(self) -> None:
        for rate, size in [("30/1", "1920x1080"), ("30000/1001", "1080x1920"), ("24/1", "3840x2160")]:
            with self.subTest(rate=rate, size=size):
                self.compare(rate, size)

    def test_legacy_stale_image_cannot_count_when_seek_produces_no_frame(self) -> None:
        source = media(self.directory, "12/1")
        target = self.directory / "retained-before-empty-seek.jpg"
        self.assertTrue(extract_frame(str(source), 0.2, str(target)))
        original = target.read_bytes()
        self.assertFalse(extract_frame(str(source), 30.0, str(target)), "an old JPEG is not evidence of a new extraction")
        self.assertEqual(target.read_bytes(), original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
