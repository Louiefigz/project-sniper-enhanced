"""Regressions for stream, frame, codec, and decode proof strictness."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _common import pl  # noqa: F401
from graphics import asset_proof as proof
from graphics import frame_oracles

_STREAM = {"codec_type": "video", "codec_name": "h264", "profile": "High",
           "pix_fmt": "yuv420p", "width": 1920, "height": 1080,
           "duration": "3.5", "nb_frames": "105",
           "avg_frame_rate": "30/1", "r_frame_rate": "30/1"}
_ENTRY = {"kind": "statement-card", "anchor": "own-screen",
          "spec": {"variant": "classic", "text": "Copy"}}


def _request(path: str) -> proof.AssetProofRequest:
    return proof.AssetProofRequest(path, _ENTRY, "mp4", (1920, 1080),
                                   3.5, "render-key")


class AssetProofStrictnessTests(unittest.TestCase):
    def _path(self, directory: str) -> str:
        path = os.path.join(directory, "card.mp4")
        Path(path).write_bytes(b"not-empty")
        return path

    def test_extra_audio_or_video_stream_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._path(tmp)
            probe = {"streams": [_STREAM,
                                 {"codec_type": "audio", "codec_name": "aac"}]}
            with mock.patch.object(proof, "_probe", return_value=probe):
                with self.assertRaisesRegex(RuntimeError, "no others"):
                    proof.prove_rendered_asset(_request(path))

    def test_missing_or_wrong_frame_count_is_rejected(self) -> None:
        for count in ("N/A", "104", "106"):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as tmp:
                path = self._path(tmp)
                stream = {**_STREAM, "nb_frames": count}
                with mock.patch.object(proof, "_probe",
                                       return_value={"streams": [stream]}):
                    with self.assertRaisesRegex(RuntimeError, "frame count"):
                        proof.prove_rendered_asset(_request(path))

    def test_full_decode_failure_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._path(tmp)
            with mock.patch.object(proof, "_probe",
                                   return_value={"streams": [_STREAM]}), \
                    mock.patch.object(proof, "_full_decode",
                                      side_effect=RuntimeError("decode failed")):
                with self.assertRaisesRegex(RuntimeError, "decode failed"):
                    proof.prove_rendered_asset(_request(path))

    def test_wrong_rate_or_codec_profile_is_rejected(self) -> None:
        mutations = ({"avg_frame_rate": "29/1"}, {"codec_name": "hevc"},
                     {"pix_fmt": "yuv444p"})
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                path = self._path(tmp)
                stream = {**_STREAM, **mutation}
                with mock.patch.object(proof, "_probe",
                                       return_value={"streams": [stream]}):
                    with self.assertRaises(RuntimeError):
                        proof.prove_rendered_asset(_request(path))

    def test_nonclear_last_encoded_alpha_frame_is_rejected(self) -> None:
        process = mock.Mock(returncode=0, stdout=b"\xff" * (96 * 54), stderr=b"")
        with mock.patch.object(frame_oracles.subprocess, "run", return_value=process):
            with self.assertRaisesRegex(RuntimeError, "retains alpha"):
                frame_oracles.terminal_alpha("overlay.mov", 75, "/ffmpeg", {})

    def test_sealed_asset_binding_does_not_reread_live_source(self) -> None:
        sealed = ({"field": "iconFile", "selector": "proof.svg",
                   "path": "motion/icons/proof.svg", "sha256": "0" * 64},)
        with mock.patch.object(proof, "resolved_assets",
                               side_effect=AssertionError("live reread")):
            self.assertEqual(proof._asset_inputs(_ENTRY, sealed), list(sealed))


if __name__ == "__main__":
    unittest.main(verbosity=2)
