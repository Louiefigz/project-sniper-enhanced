"""Synthetic-media tests for governed mastered-stereo PCM derivation."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from _common import *  # noqa: F401,F403
from fingerprints import file_sha256
from palmier.desktop_audio_master_contract import \
    validate_mastered_stereo_assets
from palmier.desktop_audio_master_media import (
    MasteredStereoRequest, asset_dict, prepare_mastered_stereo_asset)
from palmier.mcp_client import PalmierError


class MasteredStereoMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            raise unittest.SkipTest("ffmpeg/ffprobe are unavailable")
        cls.shared = tempfile.TemporaryDirectory()
        cls.base = Path(cls.shared.name) / "trusted-final.mp4"
        result = subprocess.run([
            shutil.which("ffmpeg"), "-nostdin", "-v", "error", "-y",
            "-f", "lavfi", "-i", "color=c=black:s=320x180:r=24:d=1",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:d=1",
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-r", "24",
            "-t", "1", str(cls.base),
        ], capture_output=True, text=True, check=False)
        if result.returncode:
            raise RuntimeError(result.stderr)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.shared.cleanup()

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.final = root / "final.mp4"
        shutil.copyfile(self.base, self.final)
        self.cache = root / "cache"
        self.inputs = SimpleNamespace(
            out_dir=str(root), plan_path=str(root / "plan.json"),
            manifest_path=str(root / "manifest.json"))
        self.authority = SimpleNamespace(plan_hash="a" * 64)
        self.project = {"projectSettings": {"fps": 24}}

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _master(self, frames: int = 24):
        return SimpleNamespace(
            path=str(self.final), content_hash=file_sha256(str(self.final)),
            frame_rate="24/1", end_frame=frames)

    def _prepare(self, frames: int = 24):
        request = MasteredStereoRequest(
            self.inputs, self.authority, self.project, frames, str(self.cache))
        with patch(
                "palmier.desktop_audio_master_media.approved_master",
                return_value=self._master(frames)):
            return prepare_mastered_stereo_asset(request)

    def test_derives_exact_pcm_with_atomic_argv_and_reuses_cache(self) -> None:
        asset = self._prepare()
        value = validate_mastered_stereo_assets(asset_dict(asset))
        self.assertEqual(value["pcm"]["decodedSamples"], 48_000)
        self.assertEqual(value["projectFrameRate"], "24/1")
        proof = json.loads(Path(asset.proof_path).read_text(encoding="utf-8"))
        self.assertIsInstance(proof["command"], list)
        self.assertEqual(proof["command"][0], os.path.realpath(
            shutil.which("ffmpeg")))
        with patch(
                "palmier.desktop_audio_master_media._derive",
                side_effect=AssertionError("cache should be reused")):
            cached = self._prepare()
        self.assertEqual(cached, asset)

    def test_changed_or_missing_wav_final_and_proof_fail_closed(self) -> None:
        for target in ("wav", "final", "proof"):
            with self.subTest(target=target):
                asset = self._prepare()
                value = asset_dict(asset)
                path = {
                    "wav": Path(asset.path), "final": self.final,
                    "proof": Path(asset.proof_path),
                }[target]
                path.write_bytes(path.read_bytes() + b"tamper")
                with self.assertRaisesRegex(
                        PalmierError, "bytes changed|proof"):
                    validate_mastered_stereo_assets(value)
                shutil.rmtree(self.cache)

    def test_matching_proof_hash_cannot_hide_wrong_timing_evidence(self) -> None:
        asset = self._prepare()
        value = asset_dict(asset)
        proof = json.loads(Path(asset.proof_path).read_text(encoding="utf-8"))
        proof["timing"]["frames"] = 23
        Path(asset.proof_path).write_text(
            json.dumps(proof), encoding="utf-8")
        value["derivationProofHash"] = file_sha256(asset.proof_path)
        with self.assertRaisesRegex(PalmierError, "derivation proof"):
            validate_mastered_stereo_assets(value)

    def test_wrong_project_duration_and_changed_final_are_rejected(self) -> None:
        request = MasteredStereoRequest(
            self.inputs, self.authority, self.project, 24, str(self.cache))
        with patch(
                "palmier.desktop_audio_master_media.approved_master",
                return_value=self._master(23)):
            with self.assertRaisesRegex(PalmierError, "duration"):
                prepare_mastered_stereo_asset(request)
        master = self._master()
        self.final.write_bytes(self.final.read_bytes() + b"changed")
        with patch(
                "palmier.desktop_audio_master_media.approved_master",
                return_value=master):
            with self.assertRaisesRegex(PalmierError, "approved final changed"):
                prepare_mastered_stereo_asset(request)

    def test_dangling_or_symlink_cache_pair_is_never_overwritten(self) -> None:
        self.cache.mkdir()
        target = self.cache / "mastered-stereo-forced.wav"
        target.symlink_to(self.final)
        request = MasteredStereoRequest(
            self.inputs, self.authority, self.project, 24, str(self.cache))
        with patch(
                "palmier.desktop_audio_master_media.approved_master",
                return_value=self._master()), patch(
                    "palmier.desktop_audio_master_media.cache_key",
                    return_value="forced"):
            with self.assertRaisesRegex(PalmierError, "incomplete or unsafe"):
                prepare_mastered_stereo_asset(request)
        self.assertTrue(target.is_symlink())


if __name__ == "__main__":
    unittest.main(verbosity=2)
