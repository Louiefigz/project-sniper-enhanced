"""Actual tiny picture encodes bound to graph proof, never delivery approval."""
from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from _common import pl  # noqa: F401
import opening_prefix_composition as composition
from opening_prefix_composition import PrefixCompositionJob
from opening_prefix_contract import PrefixOracleError, PrefixOracleRuntime
from guided_opening_picture import observe_picture
from graphics.composite_core import CompositeOptions, composite
from test_opening_compositor_media import _ffmpeg
from test_opening_prefix_contract import held
from test_opening_prefix_oracle import _fixture


class OpeningPrefixCompositionTests(unittest.TestCase):
    """Real shared compositor; fault cases must never claim accepted media."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(tempfile.mkdtemp(prefix="sniper-prefix-composition-", dir="/private/tmp"))
        cls.request = _fixture(cls.root, "24000/1001")
        cls.runtime = PrefixOracleRuntime(held(Path(shutil.which("ffmpeg"))),
            held(Path(shutil.which("ffprobe"))), str(cls.root), 30)
        print(f"Synthetic bound prefix composition evidence: {cls.root}", flush=True)

    def _job(self, label: str) -> PrefixCompositionJob:
        output = self.root / label
        output.mkdir(mode=0o700)
        end = time.monotonic() + 30
        return PrefixCompositionJob(self.request, self.runtime, str(output / "picture.mp4"),
                                    lambda: end - time.monotonic())

    def test_actual_encode_uses_the_proved_graph_without_approval_or_audio_claim(self) -> None:
        job = self._job("actual")
        result = composition.compose_verified_prefix(job)
        self.assertGreater(Path(job.output_path).stat().st_size, 0)
        self.assertEqual(result["outputPath"], job.output_path)
        self.assertEqual(result["output"]["sha256"], held(Path(job.output_path)).sha256)
        self.assertEqual(result["outputTransport"], "exclusively-reserved-held-regular-file-descriptor-mp4")
        self.assertFalse(result["outputDecoded"])
        self.assertFalse(result["audioCompared"])
        self.assertFalse(result["deliveryApproved"])
        self.assertTrue(result["prefixOracle"]["comparison"]["core"]["exactPreencodePixels"])
        tools = {"ffmpeg": {"path": job.runtime.ffmpeg.path}, "ffprobe": {"path": job.runtime.ffprobe.path}}
        actual = observe_picture(Path(job.output_path), ("24000/1001", 24, (64, 36)), tools)
        self.assertTrue(actual["videoDecodeSucceeded"])
        self.assertEqual(actual["frames"], 24)
        reference = Path(job.output_path).with_name("ordinary-reference.mp4")
        composite(job.request.base.path, list(job.request.full_clips), str(reference),
                  CompositeOptions(eof_pass=True, frame_rate="24000/1001", video_only=True))
        decode = ["-map", "0:v:0", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"]
        actual_pixels = _ffmpeg(["-xerror", "-err_detect", "explode", "-i", job.output_path, *decode])
        reference_pixels = _ffmpeg(["-xerror", "-err_detect", "explode", "-i", str(reference), *decode])
        self.assertEqual(actual_pixels, reference_pixels)
        self.assertEqual(len(actual_pixels), 24 * 64 * 36 * 3)
        print(f"Actual tiny bound picture composition: {result['elapsedMs']:.3f} ms", flush=True)

    def test_plain_picture_still_uses_the_same_whole_base_frame_range(self) -> None:
        job = self._job("plain")
        job = replace(job, request=replace(job.request, assets=(), full_clips=(), opening_clips=()))
        result = composition.compose_verified_prefix(job)
        self.assertTrue(Path(job.output_path).is_file())
        self.assertEqual(result["prefixOracle"]["fullGraphHash"],
                         result["prefixOracle"]["openingGraphHash"])

    def test_failed_prefix_does_not_create_candidate_picture(self) -> None:
        job = self._job("mismatch")
        request = replace(job.request, opening_clips=job.request.opening_clips[:1])
        with self.assertRaisesRegex(PrefixOracleError, "absolute frame"):
            composition.compose_verified_prefix(replace(job, request=request))
        self.assertFalse(Path(job.output_path).exists())

    def test_changed_actual_encoder_command_is_rejected_before_encode(self) -> None:
        job = self._job("command-drift")
        original = composition._command

        def changed(*arguments: object) -> list[str]:
            command = original(*arguments)
            command[command.index("-crf") + 1] = "30"
            return command

        with patch.object(composition, "_command", side_effect=changed):
            with self.assertRaisesRegex(PrefixOracleError, "command differs"):
                composition.compose_verified_prefix(job)
        self.assertFalse(Path(job.output_path).exists())

    def test_same_byte_input_rewrite_after_encode_cannot_return_proof(self) -> None:
        job = self._job("input-race")
        original = composition._execute
        path = Path(job.request.assets[0].path)
        data = path.read_bytes()

        def changed(*arguments: object) -> None:
            original(*arguments)
            path.write_bytes(data)

        with patch.object(composition, "_execute", side_effect=changed):
            with self.assertRaisesRegex(PrefixOracleError, "inventory changed during encode"):
                composition.compose_verified_prefix(job)
        self.assertTrue(Path(job.output_path).exists())  # Retained failure, not selected.

    def test_expired_caller_clock_cannot_be_reset_by_oracle_runtime(self) -> None:
        job = self._job("expired")
        with patch.object(composition, "verify_compositor_prefix") as oracle:
            with self.assertRaisesRegex(PrefixOracleError, "unexpired"):
                composition.compose_verified_prefix(replace(job, remaining=lambda: 0))
            oracle.assert_not_called()
        self.assertFalse(Path(job.output_path).exists())

    def test_existing_output_is_never_replaced(self) -> None:
        job = self._job("existing")
        Path(job.output_path).write_bytes(b"TEST-only prior failed output")
        with self.assertRaisesRegex(PrefixOracleError, "new MP4"):
            composition.compose_verified_prefix(job)
        self.assertEqual(Path(job.output_path).read_bytes(), b"TEST-only prior failed output")

    def test_parent_alias_after_oracle_cannot_write_into_retained_opening(self) -> None:
        job = self._job("parent-before-spawn")
        attempt = Path(job.output_path).parent
        retained = self.root / "retained-before-spawn"
        retained.mkdir(mode=0o700)
        original = composition._command

        def moved(*arguments: object) -> list[str]:
            command = original(*arguments)
            attempt.rename(self.root / "original-before-spawn")
            attempt.symlink_to(retained, target_is_directory=True)
            return command

        with patch.object(composition, "_command", side_effect=moved):
            with self.assertRaises(RuntimeError):
                composition.compose_verified_prefix(job)
        self.assertEqual(list(retained.iterdir()), [])
        self.assertEqual(list((self.root / "original-before-spawn").iterdir()), [])

    def test_parent_alias_at_spawn_writes_only_held_inode_and_fails_readback(self) -> None:
        job = self._job("parent-at-spawn")
        attempt = Path(job.output_path).parent
        retained = self.root / "retained-at-spawn"
        retained.mkdir(mode=0o700)
        original = composition._execute

        def moved(*arguments: object) -> None:
            attempt.rename(self.root / "original-at-spawn")
            attempt.symlink_to(retained, target_is_directory=True)
            original(*arguments)

        with patch.object(composition, "_execute", side_effect=moved):
            with self.assertRaises(RuntimeError):
                composition.compose_verified_prefix(job)
        self.assertEqual(list(retained.iterdir()), [])
        self.assertGreater((self.root / "original-at-spawn/picture.mp4").stat().st_size, 0)

    def test_target_symlink_at_spawn_never_overwrites_other_bytes(self) -> None:
        job = self._job("target-at-spawn")
        path = Path(job.output_path)
        other = self.root / "TEST-retained-original.txt"
        other.write_bytes(b"TEST-only untouched original")
        original = composition._execute

        def moved(*arguments: object) -> None:
            path.rename(path.with_name("held-original.mp4"))
            path.symlink_to(other)
            original(*arguments)

        with patch.object(composition, "_execute", side_effect=moved):
            with self.assertRaisesRegex(PrefixOracleError, "reserved name changed"):
                composition.compose_verified_prefix(job)
        self.assertEqual(other.read_bytes(), b"TEST-only untouched original")
        self.assertGreater(path.with_name("held-original.mp4").stat().st_size, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
