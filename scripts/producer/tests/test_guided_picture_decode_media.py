"""Real small-file equivalence/defect recall; retained evidence, no creator claims."""
from __future__ import annotations

import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import guided_opening_picture as picture
from _guided_picture_media_fixture import command, corrupt_late, encode, old_observe, timed_observe, variant
from palmier.process_deadline import use_process_deadline


class Remaining:
    """One monotonic allowance for all commands within a TEST operation."""

    def __init__(self, seconds: float = 60) -> None:
        """Capture one original deadline, never an allowance per subprocess."""
        self.end = time.monotonic() + seconds

    def remaining(self) -> float:
        """Expose decreasing remainder and fail terminally when it expires."""
        value = self.end - time.monotonic()
        if value <= 0:
            raise RuntimeError("TEST original media deadline expired")
        return value


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "requires installed FFmpeg")
class PictureDecodeMediaTests(unittest.TestCase):
    """Both algorithms inspect identical bytes; failures and timings remain retained."""

    @classmethod
    def setUpClass(cls) -> None:
        """Create local fixtures only, no accepted producer project or source mutation."""
        cls.root = Path(tempfile.mkdtemp(prefix="sniper-picture-decode-", dir="/private/tmp"))
        print(f"TEST picture decode root: {cls.root}", flush=True)
        cls.measurements = []
        cls.tools = {name: {"path": shutil.which(name)} for name in ("ffmpeg", "ffprobe")}
        with use_process_deadline(Remaining()):
            cls.positive = [(encode(cls.root, f"clean-{index}", (rate, 96, "160x90", [])),
                (rate, 96, (160, 90))) for index, rate in enumerate(("24/1", "30000/1001", "24000/1001"))]
            cls._pathologies()
            cls.benchmark = encode(cls.root, "benchmark-720p", ("30000/1001", 360, "1280x720", []))
            cls.single = [(encode(cls.root, f"single-{index}", (rate, 1, "64x36", [])),
                (rate, 1, (64, 36))) for index, rate in enumerate(("24/1", "25/1", "30/1", "50/1", "60/1",
                    "24000/1001", "30000/1001", "60000/1001"))]

    @classmethod
    def _pathologies(cls) -> None:
        """Retain normal metadata with actual offset, VFR, rotation, SAR and damaged bytes."""
        clean = cls.positive[0][0]
        cls.bad = [encode(cls.root, "offset", ("24/1", 96, "160x90", ["-vf", "setpts=PTS+1/TB"])),
            encode(cls.root, "vfr", ("24/1", 96, "160x90", ["-vf", "select='not(eq(n,2))'"])),
            encode(cls.root, "sar", ("24/1", 96, "160x90", ["-vf", "setsar=2"])),
            variant(clean, "multiple", ["-map", "0:v:0", "-map", "0:v:0", "-c", "copy"]), corrupt_late(clean)]
        cls._rotation(clean)
        truncated = cls.root / "truncated.mp4"
        truncated.write_bytes(clean.read_bytes()[:clean.stat().st_size * 9 // 10])
        cls.bad.append(truncated)
        av = cls.root / "av.mp4"
        command(["ffmpeg", "-nostdin", "-v", "error", "-i", str(clean), "-f", "lavfi", "-i",
            "sine=frequency=997:sample_rate=48000:duration=5", "-c:v", "copy", "-c:a", "aac", str(av)])
        cls.positive.append((av, ("24/1", 96, (160, 90))))

    @classmethod
    def _rotation(cls, clean: Path) -> None:
        """Require actual display-matrix rotation; FFmpeg 8 ignores legacy rotate tags."""
        rotated = cls.root / "rotation.mp4"
        command(["ffmpeg", "-nostdin", "-v", "error", "-display_rotation:v:0", "90",
            "-i", str(clean), "-c", "copy", str(rotated)])
        metadata = json.loads(command(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(rotated)]))
        row = metadata["streams"][0]
        if not any(abs(side.get("rotation", 0)) == 90 for side in row.get("side_data_list", [])):
            raise RuntimeError("TEST rotation fixture lacks its declared actual matrix")
        cls.bad.append(rotated)

    @classmethod
    def tearDownClass(cls) -> None:
        """Retain measured observations and scope without replacing old evidence."""
        value = {"scope": "TEST small synthetic mechanical equivalence, not creator quality or performance forecast",
            "tools": cls.tools, "measurements": cls.measurements}
        (cls.root / "measurements.json").write_text(json.dumps(value, indent=2))
        print(f"TEST picture evidence: {cls.root / 'measurements.json'}", flush=True)

    def test_exact_old_new_receipt_equivalence_for_integer_ntsc_and_av(self) -> None:
        """All returned fields and input bytes match, including packet timeline hashes."""
        with use_process_deadline(Remaining()):
            for path, expected in self.positive:
                self._equivalent(path, expected)

    def _equivalent(self, path: Path, expected: tuple) -> None:
        """Observe both real decoders against one exact same-byte authority."""
        before = picture.file_hash(path)
        inputs = path, expected, self.tools
        old = timed_observe(old_observe, inputs, self.measurements, path.name + ":old")
        new = timed_observe(picture.observe_picture, inputs, self.measurements, path.name + ":new")
        self.assertEqual(old, new)
        self.assertEqual(before, picture.file_hash(path))

    def test_one_frame_positive_terminal_time_at_integer_and_ntsc_rates(self) -> None:
        """The terminal clock must qualify even the smallest legitimate picture span."""
        with use_process_deadline(Remaining()):
            for path, expected in self.single:
                self._equivalent(path, expected)

    def test_actual_defect_recall_both_algorithms_reject(self) -> None:
        """Container metadata cannot rescue late corruption, truncation or bad clocks."""
        with use_process_deadline(Remaining()):
            for path in self.bad:
                self._reject_both(path, ("24/1", 96, (160, 90)))

    def _reject_both(self, path: Path, expected: tuple) -> None:
        """Preserve each exact negative fixture and its original hash."""
        before = picture.file_hash(path)
        for call in (old_observe, picture.observe_picture):
            with self.subTest(path=path.name, call=call.__name__), self.assertRaises(RuntimeError):
                timed_observe(call, (path, expected, self.tools), self.measurements, path.name + ":" + call.__name__)
        self.assertEqual(before, picture.file_hash(path))

    def test_wrong_exact_count_canvas_and_rate_reject(self) -> None:
        """No container frame count or rounded-rate fallback remains."""
        clean = self.positive[0][0]
        values = (("24/1", 95, (160, 90)), ("24/1", 97, (160, 90)),
                  ("24/1", 96, (162, 90)), ("25/1", 96, (160, 90)))
        with use_process_deadline(Remaining()):
            for expected in values:
                self._reject_both(clean, expected)

    def test_byte_mutation_after_packet_observation_still_rejects(self) -> None:
        """A complete decode never relaxes the final whole-file hash fence."""
        target = self.root / "postread-mutation.mp4"
        shutil.copyfile(self.positive[0][0], target)
        original = picture.observe_picture_source
        def mutate(*args: object) -> object:
            """Inject only a TEST post-observation byte change into a new copy."""
            observed = original(*args)
            with target.open("ab") as handle:
                handle.write(b"TEST mutation after packet proof")
            return observed
        with use_process_deadline(Remaining()), patch.object(picture, "observe_picture_source", side_effect=mutate):
            with self.assertRaisesRegex(RuntimeError, "changed during"):
                picture.observe_picture(target, ("24/1", 96, (160, 90)), self.tools)

    def test_alternating_same_bytes_benchmark_preserves_full_receipt(self) -> None:
        """Three paired same-file measurements, not a longform latency forecast."""
        inputs = self.benchmark, ("30000/1001", 360, (1280, 720)), self.tools
        reference = None
        with use_process_deadline(Remaining()):
            for index in range(3):
                reference = self._benchmark_pair(inputs, index, reference)

    def _benchmark_pair(self, inputs: tuple, index: int, reference: dict | None) -> dict:
        """Alternate call order so a single cold/warm ordering cannot dictate the result."""
        methods = [("old", old_observe), ("new", picture.observe_picture)]
        for name, call in methods[::1 if index % 2 == 0 else -1]:
            result = timed_observe(call, inputs, self.measurements, f"benchmark:{index}:{name}")
            self.assertEqual(reference or result, result)
            reference = result
        return reference


if __name__ == "__main__":
    unittest.main(verbosity=2)
