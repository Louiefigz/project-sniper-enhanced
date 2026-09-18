"""Exact frame-clock tests for qualification conversion evidence."""
from __future__ import annotations

import copy
import subprocess
import unittest
from pathlib import Path

from headless.external_media_snapshot import MAX_EXTERNAL_MEDIA_BYTES
from qualification_mezzanine_contract import validate_worker
from qualification_mezzanine_files import FileFact
from qualification_mezzanine_fixture import envelope, source_fact


class QualificationClockContractTests(unittest.TestCase):
    def _validate(self, value: dict) -> None:
        size = len(b"qualified-media")
        output = FileFact("/tmp/qualified.mp4", "e" * 64, size, 1, 2, 3, 4)
        validate_worker(
            value, 24, source_fact("/tmp/source.mp4"), output)

    def test_fixture_has_exact_zero_based_progressive_clocks(self) -> None:
        self._validate(envelope(
            MAX_EXTERNAL_MEDIA_BYTES + 1, len(b"qualified-media")))

    def test_source_and_output_clock_tampering_fail_closed(self) -> None:
        mutations = (
            ("sourceProbe", "facts", "lastPts"),
            ("sourceProbe", "facts", "progressive"),
            ("outputProbe", "facts", "video", "lastPts"),
            ("outputProbe", "facts", "video", "rotationDegrees"),
        )
        for path in mutations:
            with self.subTest(path=path):
                value = envelope(
                    MAX_EXTERNAL_MEDIA_BYTES + 1, len(b"qualified-media"))
                target = value["worker"]
                for key in path[:-1]:
                    target = target[key]
                leaf = path[-1]
                target[leaf] = not target[leaf] \
                    if type(target[leaf]) is bool else target[leaf] + 1
                with self.assertRaisesRegex(RuntimeError, "frame clock"):
                    self._validate(value)

    def test_source_audio_pts_samples_and_coverage_tamper_fail_closed(self) -> None:
        paths = (
            ("lastEndPts", 1),
            ("decodedSamplesPerChannel", -1),
            ("firstPts", 1),
            ("contiguousFromZero", False),
        )
        for key, change in paths:
            with self.subTest(key=key):
                value = envelope(
                    MAX_EXTERNAL_MEDIA_BYTES + 1, len(b"qualified-media"))
                audio = value["worker"]["sourceProbe"]["facts"]["sourceAudio"]
                audio[key] = change if type(change) is bool \
                    else audio[key] + change
                with self.assertRaisesRegex(RuntimeError, "source audio"):
                    self._validate(value)

    def test_transcode_argv_binds_exact_video_and_audio_filters(self) -> None:
        source_size = MAX_EXTERNAL_MEDIA_BYTES + 1
        self._validate(envelope(source_size, len(b"qualified-media")))
        for option in ("-vf", "-af"):
            for mutation in ("missing", "tampered"):
                with self.subTest(option=option, mutation=mutation):
                    value = envelope(source_size, len(b"qualified-media"))
                    argv = value["worker"]["transcode"]["argv"]
                    index = argv.index(option)
                    if mutation == "missing":
                        del argv[index:index + 2]
                    else:
                        argv[index + 1] += ",null"
                    with self.assertRaisesRegex(RuntimeError, "tool argv"):
                        self._validate(value)

    def test_audio_sample_authority_is_the_full_output_probe(self) -> None:
        value = envelope(
            MAX_EXTERNAL_MEDIA_BYTES + 1, len(b"qualified-media"))
        output = value["worker"]["outputProbe"]
        self.assertEqual(output["audioDecodeArgv"], output["argv"])
        output["audioDecodeArgv"] = [
            "/usr/bin/ffprobe", "-show_frames", "/output/qualified.mp4"]
        with self.assertRaisesRegex(RuntimeError, "tool argv"):
            self._validate(value)
        value = envelope(
            MAX_EXTERNAL_MEDIA_BYTES + 1, len(b"qualified-media"))
        output = value["worker"]["outputProbe"]
        output["argv"][1:1] = ["-select_streams", "v:0"]
        output["audioDecodeArgv"] = output["argv"].copy()
        with self.assertRaisesRegex(RuntimeError, "tool argv"):
            self._validate(value)


class QualificationWorkerClockTests(unittest.TestCase):
    def _declarations(self) -> str:
        root = Path(__file__).parents[1]
        main = (root / "headless" /
                "qualification_mezzanine_worker.js").read_text()
        media = (root / "headless" /
                 "qualification_mezzanine_worker_media.js").read_text()
        return main.split("\ntry {\n", 1)[0] + "\n" + media

    def test_worker_checks_every_decoded_source_pts(self) -> None:
        declarations = self._declarations()
        document = {
            "frames": [
                {"media_type": "video", "pts": index * 1001,
                 "duration": 1001, "interlaced_frame": 0,
                 "top_field_first": 0}
                for index in range(4)
            ]
        }
        video = {
            "time_base": "1/24000", "start_pts": 0,
            "field_order": "progressive",
        }
        for bad_pts in (False, True):
            candidate = copy.deepcopy(document)
            if bad_pts:
                candidate["frames"][2]["pts"] += 1
            script = declarations + "\ntry {" + (
                f"sourceFrameClock({candidate!r}, {video!r}, "
                "rate('24000/1001', 'rate'), 4);"
            ).replace("'", '"') + (
                "} catch (error) { process.stderr.write(error.message); "
                "process.exitCode = 2; }\n"
            )
            result = subprocess.run(
                ["node", "-e", script, "8589934592", "68719476736",
                 "10800", "24"], capture_output=True, text=True)
            with self.subTest(bad_pts=bad_pts):
                self.assertEqual(result.returncode != 0, bad_pts, result.stderr)

    def test_worker_accepts_old_ffprobe_missing_stream_field_order(self) -> None:
        document = {"frames": [
            {"media_type": "video",
             "pkt_pts": index * 1001,
             "best_effort_timestamp": index * 1001,
             "pkt_duration": 1001, "interlaced_frame": 0,
             "top_field_first": 0}
            for index in range(3)
        ]}
        video = {"time_base": "1/24000", "start_pts": 0}
        invocation = (
            f"process.stdout.write(JSON.stringify(sourceFrameClock("
            f"{document!r}, {video!r}, rate('24000/1001', 'rate'), 3)));"
        ).replace("'", '"')
        result = subprocess.run(
            ["node", "-e", self._declarations() + "\n" + invocation,
             "8589934592", "68719476736", "10800", "24"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"streamFieldOrder":"not-reported"', result.stdout)

    def test_worker_rejects_any_decoded_interlace_evidence(self) -> None:
        document = {"frames": [
            {"media_type": "video", "pts": 0, "duration": 1001,
             "interlaced_frame": 0, "top_field_first": 1},
        ]}
        video = {
            "time_base": "1/24000", "start_pts": 0,
            "field_order": "progressive",
        }
        invocation = (
            f"sourceFrameClock({document!r}, {video!r}, "
            "rate('24000/1001', 'rate'), 1);"
        ).replace("'", '"')
        script = self._declarations() + "\ntry {" + invocation + (
            "} catch (error) { process.stderr.write(error.message); "
            "process.exitCode = 2; }\n"
        )
        result = subprocess.run(
            ["node", "-e", script, "8589934592", "68719476736",
             "10800", "24"], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not exact progressive", result.stderr)

    def test_worker_reobserves_every_output_frame(self) -> None:
        worker = Path(__file__).parents[1] / "headless" / \
            "qualification_mezzanine_worker.js"
        text = worker.read_text()
        self.assertIn("const outputProbe = probe(OUTPUT, true);", text)
        media = Path(__file__).parents[1] / "headless" / \
            "qualification_mezzanine_worker_media.js"
        body = media.read_text()
        self.assertIn(
            "sourceFrameClock(\n    document, video, expectedRate",
            body)
        self.assertNotIn(
            'video.field_order === "progressive"', body)

    def test_worker_checks_source_audio_sample_continuity(self) -> None:
        document = {"frames": [
            {"media_type": "audio", "pts": 0, "duration": 1024,
             "nb_samples": 1024},
            {"media_type": "audio", "pts": 1024, "duration": 1024,
             "nb_samples": 1024},
            {"media_type": "audio", "pts": 2048, "duration": 512,
             "nb_samples": 512},
        ]}
        audio = {"codec_name": "pcm_s16be", "sample_rate": "48000",
                 "channels": 2, "time_base": "1/48000",
                 "start_pts": 0, "duration_ts": 2560}
        for gap in (False, True):
            candidate = copy.deepcopy(document)
            if gap:
                candidate["frames"][1]["pts"] += 1
            invocation = (
                f"sourceAudioClock({candidate!r}, {audio!r}, "
                "rate('24000/1001', 'rate'), 1);"
            ).replace("'", '"')
            script = self._declarations() + "\ntry {" + invocation + (
                "} catch (error) { process.stderr.write(error.message); "
                "process.exitCode = 2; }\n"
            )
            result = subprocess.run(
                ["node", "-e", script, "8589934592", "68719476736",
                 "10800", "24"], capture_output=True, text=True)
            with self.subTest(gap=gap):
                self.assertEqual(result.returncode != 0, gap, result.stderr)

    def test_output_audio_samples_reuse_the_full_output_probe(self) -> None:
        document = {"frames": [
            {"media_type": "video", "nb_samples": 99},
            {"media_type": "audio", "nb_samples": 1024},
            {"media_type": "audio", "nb_samples": 608},
        ]}
        argv = ["/usr/bin/ffprobe", "-show_frames", "/output/qualified.mp4"]
        invocation = (
            f"process.stdout.write(JSON.stringify(decodedAudioSamples("
            f"{document!r}, {argv!r})));"
        ).replace("'", '"')
        result = subprocess.run(
            ["node", "-e", self._declarations() + "\n" + invocation,
             "8589934592", "68719476736", "10800", "24"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"samplesPerChannel":1632', result.stdout)
        worker = Path(__file__).parents[1] / "headless" / \
            "qualification_mezzanine_worker.js"
        self.assertNotIn(
            "decodedAudioSamples(OUTPUT)", worker.read_text())

    def test_worker_rejects_decoder_stderr_even_with_zero_status(self) -> None:
        invocation = """
child.spawnSync = () => ({
  error: null, status: 0, stdout: '{"frames":[]}', stderr: 'decode fault'
});
try {
  run('/usr/bin/ffprobe', ['-v', 'error']);
} catch (error) {
  process.stderr.write(error.message);
  process.exitCode = 2;
}
"""
        result = subprocess.run(
            ["node", "-e", self._declarations() + invocation,
             "8589934592", "68719476736", "10800", "24"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("decode fault", result.stderr)


if __name__ == "__main__":
    unittest.main()
