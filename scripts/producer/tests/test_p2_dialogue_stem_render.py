"""Real-media gates for the exact private dialogue-stem renderer."""
from __future__ import annotations

import copy
import json
import math
import os
import shutil
import stat
import struct
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

from audio.dialogue_stem_contracts import (
    DialogueSourceSnapshot,
    DialogueStemRenderError,
    DialogueStemRenderRequest,
    DialogueStemTools,
    dialogue_source_snapshot_set_hash,
)
from audio.dialogue_stem_media import _tempo_token
from audio.dialogue_stem_receipt import verify_dialogue_stem_receipt
from audio.dialogue_stem_render import render_dialogue_stem
from contracts.schema_validator import validate_document
from edit.dialogue_authority import (
    compile_dialogue_map,
    dialogue_map_hash,
)
from edit.picture_lock_common import content_hash
from fingerprints import file_sha256

_FIXTURE = Path(__file__).parent / "fixtures" / "dialogue-authority-v1.json"
_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")


def _supports_rubberband() -> bool:
    if not _FFMPEG or not _FFPROBE:
        return False
    result = subprocess.run(
        [_FFMPEG, "-hide_banner", "-filters"],
        text=True, capture_output=True, check=False)
    return result.returncode == 0 and "rubberband" in result.stdout


def _tools() -> DialogueStemTools:
    ffmpeg = os.path.realpath(str(_FFMPEG))
    ffprobe = os.path.realpath(str(_FFPROBE))
    return DialogueStemTools(
        ffmpeg, file_sha256(ffmpeg), ffprobe, file_sha256(ffprobe))


def _audio(path: str, rate: int, frequency: int, duration: str) -> None:
    command = [
        str(_FFMPEG), "-nostdin", "-v", "error", "-y",
        "-f", "lavfi", "-i",
        f"sine=frequency={frequency}:sample_rate={rate}:duration={duration}",
        "-af", "volume=0.1", "-c:a", "pcm_s24le", path,
    ]
    subprocess.run(command, check=True)


@unittest.skipUnless(
    _supports_rubberband(), "FFmpeg with rubberband is required")
class DialogueStemRenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.root = self.temp.name
        self.paths = {
            "source-a": os.path.join(self.root, "source-a.wav"),
            "source-b": os.path.join(self.root, "source-b.wav"),
            "source-c": os.path.join(self.root, "source-c.wav"),
        }
        _audio(self.paths["source-a"], 48_000, 300, "3")
        _audio(self.paths["source-b"], 44_100, 600, "3")
        _audio(self.paths["source-c"], 48_000, 900, "2")
        self.track = json.loads(
            _FIXTURE.read_text(encoding="utf-8"))["track"]

    def tearDown(self) -> None:
        for root, directories, files in os.walk(
                self.root, topdown=False):
            for name in files:
                os.chmod(os.path.join(root, name), 0o600)
            for name in directories:
                os.chmod(os.path.join(root, name), 0o700)
        self.temp.cleanup()

    def _sources(
        self,
        ids: tuple[str, ...] = ("source-a", "source-b", "source-c"),
    ) -> tuple[DialogueSourceSnapshot, ...]:
        return tuple(
            DialogueSourceSnapshot(
                source_id, self.paths[source_id],
                file_sha256(self.paths[source_id]), 0)
            for source_id in ids
        )

    def _map(
        self,
        sources: tuple[DialogueSourceSnapshot, ...],
        track: dict | None = None,
    ) -> dict:
        value = copy.deepcopy(track or self.track)
        value["sourceSnapshotSetHash"] = \
            dialogue_source_snapshot_set_hash(sources)
        return compile_dialogue_map(value)

    def _request(
        self,
        dialogue_map: dict,
        sources: tuple[DialogueSourceSnapshot, ...],
        name: str = "generation",
    ) -> DialogueStemRenderRequest:
        return DialogueStemRenderRequest(
            dialogue_map, dialogue_map_hash(dialogue_map), sources,
            os.path.join(self.root, name), _tools())

    def test_real_j_l_and_rational_retime_end_at_exact_b_f(self) -> None:
        sources = self._sources()
        dialogue_map = self._map(sources)
        frozen = copy.deepcopy(dialogue_map)
        request = self._request(dialogue_map, sources)
        receipt = render_dialogue_stem(request)
        validate_document("dialogue-stem-receipt-v1.schema.json", receipt)
        self.assertEqual(dialogue_map, frozen)
        self.assertEqual(receipt["output"]["decodedSamples"], 288_000)
        self.assertEqual(
            {row["role"] for row in receipt["entries"]},
            {"primary", "j-cut-handle", "l-cut-handle"})
        retimed = next(row for row in receipt["entries"]
                       if row["dialogueSegmentId"] == "dialogue-c-primary")
        self.assertEqual(retimed["effectiveSpeed"], {
            "numerator": "5", "denominator": "4"})
        self.assertEqual(retimed["tempoToken"], "1.25")
        self.assertEqual(retimed["preReconcileSamples"], 48_000)
        self.assertEqual(retimed["reconciliationSamples"], 0)
        generation = request.generation_dir
        output = os.path.join(generation, "dialogue-stem.wav")
        self.assertEqual(stat.S_IMODE(os.stat(generation).st_mode), 0o500)
        self.assertEqual(stat.S_IMODE(os.stat(output).st_mode), 0o400)
        self.assertGreater(
            self._rms(output, 140_000, 143_000),
            self._rms(output, 120_000, 123_000) * 1.1)
        self.assertGreater(
            self._rms(output, 241_000, 244_000),
            self._rms(output, 210_000, 213_000) * 1.1)
        before = file_sha256(output)
        with self.assertRaisesRegex(DialogueStemRenderError, "already exists"):
            render_dialogue_stem(request)
        self.assertEqual(file_sha256(output), before)

    def _rms(self, path: str, start: int, end: int) -> float:
        with wave.open(path, "rb") as handle:
            self.assertEqual(handle.getnframes(), 288_000)
            self.assertEqual(handle.getsampwidth(), 4)
            handle.setpos(start)
            raw = handle.readframes(end - start)
        samples = [item[0] for item in struct.iter_unpack("<i", raw)]
        return math.sqrt(sum(value * value for value in samples) / len(samples))

    def test_non_aligned_44100_boundary_uses_absolute_p_projection(self) -> None:
        sources = self._sources(("source-b",))
        track = copy.deepcopy(self.track)
        track["totalOutputFrames"] = 3
        track["totalOutputSamples"] = 4_800
        track["segments"] = [{
            "dialogueSegmentId": "dialogue-b-primary",
            "cutSegmentId": "cut-b",
            "elementVersion": 1,
            "sourceId": "source-b",
            "sourceSampleRate": 44_100,
            "sourceSampleRange": {
                "startSample": 1, "endSampleExclusive": 4_411},
            "outputSampleRange": {
                "startSample": 0, "endSampleExclusive": 4_800},
            "speed": {"numerator": "1", "denominator": "1"},
            "role": "primary",
        }]
        dialogue_map = self._map(sources, track)
        entry = dialogue_map["entries"][0]
        self.assertEqual(entry["normalizedSourceSampleRange"], {
            "startSample": 1, "endSampleExclusive": 4_801})
        receipt = render_dialogue_stem(
            self._request(dialogue_map, sources, "non-aligned"))
        self.assertEqual(receipt["output"]["decodedSamples"], 4_800)
        self.assertEqual(receipt["entries"][0]["preReconcileSamples"], 4_800)

    def test_long_form_entry_count_uses_bounded_fan_in(self) -> None:
        sources = self._sources(("source-a",))
        track = copy.deepcopy(self.track)
        track["totalOutputFrames"] = 65
        track["totalOutputSamples"] = 104_000
        track["segments"] = [
            {
                "dialogueSegmentId": f"dialogue-{index:03}-primary",
                "cutSegmentId": f"cut-{index:03}",
                "elementVersion": 1,
                "sourceId": "source-a",
                "sourceSampleRate": 48_000,
                "sourceSampleRange": {
                    "startSample": index * 1_600,
                    "endSampleExclusive": (index + 1) * 1_600,
                },
                "outputSampleRange": {
                    "startSample": index * 1_600,
                    "endSampleExclusive": (index + 1) * 1_600,
                },
                "speed": {"numerator": "1", "denominator": "1"},
                "role": "primary",
            }
            for index in range(65)
        ]
        dialogue_map = self._map(sources, track)
        receipt = render_dialogue_stem(
            self._request(dialogue_map, sources, "bounded-fan-in"))
        self.assertEqual(len(receipt["entries"]), 65)
        self.assertEqual(receipt["output"]["decodedSamples"], 104_000)

    def test_hash_set_and_existing_destination_fail_before_publication(
        self,
    ) -> None:
        sources = self._sources()
        dialogue_map = self._map(sources)
        stale = DialogueStemRenderRequest(
            dialogue_map, "f" * 64, sources,
            os.path.join(self.root, "stale"), _tools())
        with self.assertRaisesRegex(DialogueStemRenderError, "map hash"):
            render_dialogue_stem(stale)
        self.assertFalse(os.path.lexists(stale.generation_dir))
        bad_sources = (
            DialogueSourceSnapshot(
                "source-a", self.paths["source-a"], "f" * 64, 0),
            *sources[1:],
        )
        bad = self._request(dialogue_map, bad_sources, "bad-source")
        with self.assertRaisesRegex(DialogueStemRenderError, "bytes drifted"):
            render_dialogue_stem(bad)
        self.assertFalse(os.path.lexists(bad.generation_dir))
        os.mkdir(os.path.join(self.root, "occupied"))
        sentinel = os.path.join(self.root, "occupied", "keep")
        Path(sentinel).write_text("owned", encoding="utf-8")
        occupied = self._request(dialogue_map, sources, "occupied")
        with self.assertRaisesRegex(DialogueStemRenderError, "already exists"):
            render_dialogue_stem(occupied)
        self.assertEqual(Path(sentinel).read_text(encoding="utf-8"), "owned")

    def test_decimal_tool_projection_preserves_exact_integer_bounds(self) -> None:
        self.assertEqual(_tempo_token({
            "numerator": "100", "denominator": "1"}), "100")
        self.assertEqual(_tempo_token({
            "numerator": "1", "denominator": "100"}), "0.01")

    def test_insufficient_decoded_source_never_publishes(self) -> None:
        _audio(self.paths["source-b"], 44_100, 600, "2.1")
        sources = self._sources()
        dialogue_map = self._map(sources)
        request = self._request(dialogue_map, sources, "too-short")
        with self.assertRaisesRegex(DialogueStemRenderError, "exceeds decoded"):
            render_dialogue_stem(request)
        self.assertFalse(os.path.lexists(request.generation_dir))

    def test_receipt_self_hash_rejects_tampering(self) -> None:
        sources = self._sources(("source-b",))
        track = copy.deepcopy(self.track)
        track["totalOutputFrames"] = 3
        track["totalOutputSamples"] = 4_800
        track["segments"] = [{
            "dialogueSegmentId": "dialogue-b-primary",
            "cutSegmentId": "cut-b",
            "elementVersion": 1,
            "sourceId": "source-b",
            "sourceSampleRate": 44_100,
            "sourceSampleRange": {
                "startSample": 0, "endSampleExclusive": 4_410},
            "outputSampleRange": {
                "startSample": 0, "endSampleExclusive": 4_800},
            "speed": {"numerator": "1", "denominator": "1"},
            "role": "primary",
        }]
        dialogue_map = self._map(sources, track)
        receipt = render_dialogue_stem(
            self._request(dialogue_map, sources, "tamper"))
        tampered = copy.deepcopy(receipt)
        tampered["output"]["decodedSamples"] -= 1
        with self.assertRaisesRegex(DialogueStemRenderError, "hash drifted"):
            verify_dialogue_stem_receipt(tampered)
        body = {key: value for key, value in tampered.items()
                if key != "receiptHash"}
        tampered["receiptHash"] = content_hash(body)
        with self.assertRaisesRegex(DialogueStemRenderError, "terminal"):
            verify_dialogue_stem_receipt(tampered)


if __name__ == "__main__":
    unittest.main(verbosity=2)
