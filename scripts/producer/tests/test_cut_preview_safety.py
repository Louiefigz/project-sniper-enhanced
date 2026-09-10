"""Bounded private-preview rejection tests; no models or creative qualification."""
from __future__ import annotations

import copy
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from _cut_preview_fixture import input_fixture
from cut_preview_authority import validate_input
from cut_preview_io import bound_json, read_bytes, run_bounded
from cut_preview_media import _decode_pcm
from cut_preview_picture import verify_picture_origin


class CutPreviewSafetyTests(unittest.TestCase):
    def test_artifact_links_and_parent_aliases_are_not_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            artifact, alias = root / "value.json", root / "alias.json"
            artifact.write_bytes(b'{"safe":true}')
            os.link(artifact, alias)
            with self.assertRaisesRegex(RuntimeError, "bounded regular"):
                read_bytes(artifact)
            alias.unlink()
            alias.symlink_to(artifact)
            with self.assertRaises(OSError):
                read_bytes(alias)
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(root, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "canonical"):
                read_bytes(linked_parent / "value.json")

    def test_artifact_bytes_must_be_bounded_utf8_and_stable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            artifact = Path(temporary).resolve() / "value.json"
            artifact.write_bytes(b'{"safe":true}')
            with self.assertRaisesRegex(RuntimeError, "bounded regular"):
                read_bytes(artifact, 3)
            real_read = os.read
            def mutate_after_read(descriptor: int, size: int) -> bytes:
                data = real_read(descriptor, size)
                artifact.write_bytes(b'{"safe":false}')
                return data
            with patch("cut_preview_io.os.read", side_effect=mutate_after_read):
                with self.assertRaisesRegex(RuntimeError, "changed during read"):
                    read_bytes(artifact)
            artifact.write_bytes(b'{"bad":"\xff"}')
            with self.assertRaises(UnicodeDecodeError):
                bound_json(artifact)

    def test_child_output_and_wall_time_are_bounded(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "output byte bound"):
            run_bounded([sys.executable, "-c", "import sys;sys.stderr.write('x'*1000000)"], maximum=32)
        started = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, "command deadline"):
            run_bounded([sys.executable, "-c", "import time;time.sleep(30)"], timeout=0.05)
        self.assertLess(time.monotonic() - started, 2)

    def test_invocation_types_timestamps_nonce_and_digest_are_exact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            value, output = input_fixture(Path(temporary))
            for key, invalid in (("schemaVersion", True), ("attempt", True), ("attempt", 10001),
                                 ("createdAt", "2026-02-31T01:00:00.000Z"), ("executionNonce", "../escape"),
                                 ("pipelineDigest", {}), ("runId", "x" * 201), ("proxyScale", float("nan"))):
                altered = copy.deepcopy(value)
                altered[key] = invalid
                with self.subTest(key=key), self.assertRaises((RuntimeError, ValueError)):
                    validate_input(altered, output / "input.json")

    def test_picture_origin_cannot_waive_relative_timing_or_payload_changes(self) -> None:
        before = {"timeBase": "1/30000", "frameRate": "30000/1001", "startPts": 630,
                  "packetCount": 120, "relativePacketsHash": "a" * 64, "fileHash": "b" * 64}
        after = {**before, "startPts": 0, "fileHash": "c" * 64}
        proof = verify_picture_origin(before, after)
        self.assertEqual(proof["originalStartPts"], 630)
        for key, changed in (("startPts", 1), ("packetCount", 119), ("relativePacketsHash", "d" * 64),
                             ("timeBase", "1/90000"), ("frameRate", "30/1")):
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, "exact relative clocks"):
                verify_picture_origin(before, {**after, key: changed})

    def test_strict_decode_rejects_broken_actual_media(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            invalid = Path(temporary).resolve() / "cut-preview.mp4"
            invalid.write_bytes(b"not an audiovisual MP4")
            with self.assertRaisesRegex(RuntimeError, "strict full decode"):
                _decode_pcm(invalid, "ffmpeg")


if __name__ == "__main__":
    unittest.main()
