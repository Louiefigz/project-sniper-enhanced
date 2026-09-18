"""Synthetic render/clock tests, not creative or deployed admission qualification."""
from __future__ import annotations

import json
import math
import array
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _cut_preview_fixture import input_fixture
from cut_preview import render_preview
from cut_preview_authority import observe_inputs, validate_input
from cut_preview_io import bound_json


def pcm(path: Path) -> bytes:
    """Decode small synthetic audio with a bounded test command."""
    return subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path),
                           "-map", "0:a:0", "-f", "s16le", "-c:a", "pcm_s16le", "-"],
                          capture_output=True, check=True, timeout=20).stdout


def center(values: array.array, seconds: float) -> float:
    """Locate source energy within a declared local event window, not a waveform phase."""
    lo, hi = round((seconds - 0.03) * 48000), round((seconds + 0.05) * 48000)
    energy = [float(values[index * 2]) ** 2 for index in range(lo, hi)]
    if sum(energy) <= 1e7:
        raise AssertionError("source-derived impulse disappeared")
    return sum((lo + index) * item for index, item in enumerate(energy)) / sum(energy) / 48000


class CutPreviewTests(unittest.TestCase):
    def test_real_ntsc_multicut_proxy_full_audio_and_jcut_parity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            first, out_full = input_fixture(root)
            full = render_preview(first, out_full)
            second, out_proxy = input_fixture(root, 0.5)
            proxy = render_preview(second, out_proxy)
            self.assertEqual(full["profile"]["fps"], "30000/1001")
            self.assertEqual(proxy["profile"]["width"], full["profile"]["width"] // 2)
            self.assertEqual(proxy["media"]["videoFrames"], full["media"]["videoFrames"])
            self.assertEqual(proxy["media"]["audio"], full["media"]["audio"])
            sound = pcm(out_full / "cut-preview.mp4")
            self.assertEqual(sound, pcm(out_proxy / "cut-preview.mp4"))
            samples = array.array("h", sound)
            lead = samples[int(0.91 * 48000) * 2:int(0.95 * 48000) * 2]
            self.assertGreater(math.sqrt(sum(item * item for item in lead) / len(lead)), 10)
            source = json.loads(Path(first["manifestPath"]).read_text())["sources"][0]["path"]
            original = array.array("h", pcm(Path(source)))
            # Executed video frame-grid starts, not a nominal floating-point sum.
            for source_time, mapped_time in ((0.2, 0.2), (1.42, 0.92), (1.8, 1.301),
                                             (2.92, 2.421), (3.92, 3.9235)):
                expected = center(original, source_time) + mapped_time - source_time
                self.assertLess(abs(center(samples, mapped_time) - expected), 0.003,
                                f"interior/end source impulse drift at {source_time}: "
                                f"expected={expected},actual={center(samples, mapped_time)}")
            self.assertEqual(full["media"]["fullDecode"], "passed")
            self.assertEqual(full["scope"], "cut-only-source-aspect-ungraded-unmixed-not-delivery")
            self.assertFalse(any((root / "producer" / name).exists() for name in
                                 ("final.mp4", "base_final.mp4", ".sniper-qc-approved.json", ".render-graph-v1")))

    def test_nonunity_tempo_uses_algorithm_reference_not_sample_perfect_linear_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            value, output = input_fixture(Path(temporary), lead=0, speed=1.25)
            with self.assertRaisesRegex(RuntimeError, "source speed 1 only"):
                render_preview(value, output)
            self.assertFalse((output / "parts").exists(), "unsupported speed fails before render")
            # Exercise the private audio kernel for diagnosis, not admission. The
            # picture concat is exact for retimed parts too (its clock is rebuilt
            # from the packet index), so admission is the ONLY speed gate and a
            # bypassed admission must still seal the retiming EXPLICITLY.
            with patch("cut_preview.assert_supported_cut"):
                receipt = render_preview(value, output)
            source = json.loads(Path(value["manifestPath"]).read_text())["sources"][0]["path"]
            reference = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", source,
                "-af", "aformat=channel_layouts=stereo,atrim=start=0:end=1,asetpts=PTS-STARTPTS,atempo=1.25,aresample=48000",
                "-ac", "2", "-c:a", "pcm_s16le", "-f", "s16le", "-"],
                capture_output=True, check=True, timeout=20).stdout
            # The independent source-derived FFmpeg tempo result defines legitimate
            # phase movement. The additional AAC encode may move energy <=3ms.
            expected = center(array.array("h", reference), 0.2 / 1.25)
            actual = center(array.array("h", pcm(output / "cut-preview.mp4")), 0.2 / 1.25)
            self.assertLess(abs(actual - expected), 0.003)
            clock = bound_json(output / "audio-clock.json")
            self.assertTrue(all(row["speed"] == 1.25 for row in clock["parts"]))
            # 96 frames = 153753.6 samples: NOT a whole millisecond, so the presented
            # AAC clock equals the sealed float total only with a sample-rate movie
            # timescale (the TypeScript evidence reader demands exact equality).
            self.assertNotEqual(clock["totalSamples"] % 48, 0)
            self.assertEqual(receipt["media"]["audio"]["presentedAudioSamples"], clock["totalSamples"])
            manifestation = bound_json(output / "cut_manifestation.v1.json")
            self.assertTrue(all(row["speed"] == 1.25 for row in manifestation["parts"]))
            self.assertEqual(receipt["media"]["videoFrames"], manifestation["concat"]["videoFrames"])
            self.assertTrue((output / "receipt.json").exists())

    def test_duration_only_remux_still_fails_source_content_oracle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            value, output = input_fixture(Path(temporary))
            receipt = render_preview(value, output)
            rejected = output / "rejected-duration-only.mp4"
            count = receipt["media"]["audio"]["presentedAudioSamples"]
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-n", "-i", str(output / "cut-concat.mp4"),
                "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy", "-af",
                f"aresample=48000:async=1:first_pts=0,apad,atrim=end_sample={count},asetpts=PTS-STARTPTS",
                "-c:a", "aac", "-b:a", "192k", str(rejected)], check=True, capture_output=True, timeout=20)
            source = json.loads(Path(value["manifestPath"]).read_text())["sources"][0]["path"]
            expected = center(array.array("h", pcm(Path(source))), 0.2)
            actual = center(array.array("h", pcm(rejected)), 0.2)
            # Historically measured 8.830742ms; this rejects the flawed strategy
            # without assuming a codec-version-specific sample-perfect signature.
            self.assertGreater(abs(actual - expected), 0.003)

    def test_silent_source_byte_drift_and_unadmitted_manifest_fail_before_render(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            value, output = input_fixture(Path(temporary))
            _, manifest, _ = observe_inputs(value)
            silent = Path(manifest["sources"][1]["path"])
            silent.write_bytes(silent.read_bytes() + b"changed")
            with self.assertRaisesRegex(RuntimeError, "corrupt|changed"):
                render_preview(value, output)
            self.assertFalse((output / "receipt.json").exists())

    def test_post_render_source_drift_cannot_publish_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            value, output = input_fixture(Path(temporary))
            observed = observe_inputs(value)
            with patch("cut_preview.observe_inputs", side_effect=[observed, RuntimeError("silent source drift")]):
                with self.assertRaisesRegex(RuntimeError, "silent source drift"):
                    render_preview(value, output)
            self.assertTrue((output / "cut-preview.mp4").exists(), "failed media remains for diagnosis")
            self.assertFalse((output / "receipt.json").exists())

    def test_private_attempt_is_new_only_and_request_hash_is_exact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            value, output = input_fixture(Path(temporary))
            self.assertEqual(validate_input(value, output / "input.json"), output)
            (output / "cut-preview.mp4").write_bytes(b"prior")
            with self.assertRaisesRegex(RuntimeError, "not new"):
                validate_input(value, output / "input.json")
            (output / "cut-preview.mp4").unlink()
            value["request"]["createdAt"] = "2026-09-06T01:00:01.000Z"
            with self.assertRaisesRegex(RuntimeError, "request hash"):
                validate_input(value, output / "input.json")

    def test_missing_source_admission_and_forged_projection_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            value, output = input_fixture(Path(temporary))
            with patch("cut_preview_authority.execution_media_authority_entries", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "re-ingest"):
                    observe_inputs(value)
            projection = Path(value["producerDir"]) / "compatibility_projections" / f"{value['request']['projectionReceiptHash']}.json"
            document = bound_json(projection)
            document["timelineMap"]["outputDuration"] += 1
            projection.write_text(json.dumps(document))
            with self.assertRaisesRegex(RuntimeError, "hash changed"):
                render_preview(value, output)


if __name__ == "__main__":
    unittest.main()
