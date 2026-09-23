"""Real-media gates at legacy, fast, and direct program-mix boundaries."""
from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _channel_normalization_fixture import (  # noqa: E402
    FFMPEG,
    available,
    dead_stereo_video,
    mono_music,
)
from audio.audio_mix import MixSpec, run_audio_mix  # noqa: E402
from audio.audio_separate import extract_wav  # noqa: E402
from audio.channel_normalization import (  # noqa: E402
    observe_channel_authority,
    system_program_request,
)
from motion.transitions import apply_transitions  # noqa: E402
from cut_speed import render_cut_speed  # noqa: E402
from edit.exact_timing import PositiveRational, ProjectClock  # noqa: E402
from edit.picture_lock_common import content_hash  # noqa: E402
from edit.repair_fragment import render_repair_fragment  # noqa: E402
from edit.repair_composite import (  # noqa: E402
    RepairCompositeRequest,
    render_repair_composite,
)
from edit.repair_fragment_contracts import (  # noqa: E402
    RepairFragmentRequest,
    RepairRenderError,
)
from tests._p2_repair_media_fixture import (  # noqa: E402
    media as repair_media,
    operation as repair_operation,
    tools as repair_tools,
)
from contracts.schema_validator import validate_document  # noqa: E402


def _assert_balanced(test: unittest.TestCase, path: str) -> None:
    authority = observe_channel_authority(
        system_program_request(path))
    test.assertEqual(
        authority.receipt["decision"]["status"], "stereo-verified")
    peaks = [
        float(value) for value in authority.receipt["stream"]["peakDbfs"]
    ]
    test.assertLess(abs(peaks[0] - peaks[1]), 0.2)


def _dead_copy(source: str, destination: str, dead: int) -> None:
    live = 1 - dead
    audio_filter = (
        f"pan=stereo|c{dead}=0*c0|c{live}=c0")
    subprocess.run([
        str(FFMPEG), "-nostdin", "-v", "error", "-y", "-i", source,
        "-map", "0:v:0", "-c:v", "copy", "-map", "0:a:0",
        "-af", audio_filter, "-c:a", "pcm_s32le",
        "-ar", "48000", "-ac", "2", destination,
    ], check=True)


def _live_audio_copy(source: str, destination: str) -> None:
    subprocess.run([
        str(FFMPEG), "-nostdin", "-v", "error", "-y", "-i", source,
        "-f", "lavfi", "-i",
        "sine=frequency=330:sample_rate=48000:duration=5",
        "-map", "0:v:0", "-c:v", "copy", "-map", "1:a:0",
        "-af", "pan=stereo|c0=c0|c1=c0,atrim=end_sample=240000",
        "-c:a", "pcm_s32le", "-ar", "48000", "-ac", "2", destination,
    ], check=True)


@unittest.skipUnless(available(), "ffmpeg and ffprobe are required")
class ProgramMixBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_music_direct_path_materializes_authority_before_mix(self) -> None:
        source = os.path.join(self.temp.name, "dead-left.mp4")
        music = os.path.join(self.temp.name, "music.wav")
        output = os.path.join(self.temp.name, "mixed.mp4")
        work = os.path.join(self.temp.name, "music-work")
        dead_stereo_video(source, 0)
        mono_music(music)
        with contextlib.redirect_stdout(io.StringIO()):
            result = run_audio_mix(MixSpec(
                source, music, output, work_dir=work))
        self.assertEqual(result["status"], "done")
        receipt = result["channel_normalization"]["receipt"]
        self.assertEqual(
            receipt["decision"]["status"], "dead-channel-repaired")
        self.assertEqual(
            result["channel_normalization"]["materialization"]
            ["sourceReceiptHash"],
            receipt["receiptHash"])
        _assert_balanced(self, output)

    def test_retired_transition_refuses_before_source_audio_work(self) -> None:
        source = os.path.join(self.temp.name, "unread-source.mp4")
        output = os.path.join(self.temp.name, "transitioned.mp4")
        with self.assertRaisesRegex(ValueError, "retired"):
            apply_transitions(source, [{"outTime": 1.2,
                              "kind": "white-flash", "sfx": True}], output)
        self.assertFalse(os.path.exists(output))

    def test_multisource_cut_and_jcut_normalize_each_source_first(self) -> None:
        left = os.path.join(self.temp.name, "cut-left.mp4")
        right = os.path.join(self.temp.name, "cut-right.mp4")
        output = os.path.join(self.temp.name, "cut-output.mp4")
        parts = os.path.join(self.temp.name, "cut-parts")
        os.makedirs(parts)
        dead_stereo_video(left, 0)
        dead_stereo_video(right, 1)
        plan = {"cutTrack": [
            {"sourceId": "left", "start": 0.5, "end": 1.5},
            {"sourceId": "right", "start": 0.5, "end": 1.5,
             "audioLeadMs": 200},
        ]}
        manifest = {"sources": [
            {"id": "left", "path": left},
            {"id": "right", "path": right},
        ]}
        with contextlib.redirect_stdout(io.StringIO()):
            result = render_cut_speed(
                plan, manifest, output, parts)
        receipts = result["channelNormalizationReceipts"]
        self.assertEqual(len(receipts), 2)
        self.assertEqual(
            {row["receipt"]["decision"]["deadChannel"]
             for row in receipts},
            {0, 1})
        _assert_balanced(self, output)

    def test_separation_extract_repairs_both_channel_sides(self) -> None:
        for dead in (0, 1):
            with self.subTest(dead=dead):
                source = os.path.join(
                    self.temp.name, f"separate-{dead}.mp4")
                output = os.path.join(
                    self.temp.name, f"separate-{dead}.wav")
                dead_stereo_video(source, dead)
                authority = observe_channel_authority(
                    system_program_request(source))
                result = extract_wav(
                    source, output, authority.filter_for("stereo"))
                self.assertTrue(result["ok"], result["stderr"])
                self.assertIsNotNone(result["sha256"])
                _assert_balanced(self, output)

    def test_repair_splice_repairs_raw_source_but_rejects_dead_parent(self) -> None:
        rate = PositiveRational(30, 1)
        clock = ProjectClock(rate, 48_000)
        normal_parent = os.path.join(self.temp.name, "parent.mov")
        normal_source = os.path.join(self.temp.name, "source.mov")
        live_parent = os.path.join(self.temp.name, "parent-live.mov")
        dead_source = os.path.join(self.temp.name, "source-dead.mov")
        dead_parent = os.path.join(self.temp.name, "parent-dead.mov")
        repair_media(normal_parent, "30/1", False)
        repair_media(normal_source, "30/1", True)
        _live_audio_copy(normal_parent, live_parent)
        _dead_copy(normal_source, dead_source, 0)
        _dead_copy(live_parent, dead_parent, 1)
        operation = repair_operation(clock)
        output = os.path.join(self.temp.name, "repair.mov")
        receipt = render_repair_fragment(RepairFragmentRequest(
            operation, content_hash(operation), normal_parent, dead_source,
            output, clock, repair_tools()))
        self.assertEqual(
            receipt["inputs"]["parent"]["channelNormalization"]
            ["decision"]["status"],
            "stereo-verified")
        self.assertEqual(
            receipt["inputs"]["source"]["channelNormalization"]
            ["decision"]["status"],
            "dead-channel-repaired")
        validate_document(
            "cut-repair-fragment-receipt-v1.schema.json", receipt)
        _assert_balanced(self, output)
        candidate = os.path.join(self.temp.name, "candidate.mov")
        composite = render_repair_composite(RepairCompositeRequest(
            normal_parent, output, candidate, receipt,
            content_hash(operation), clock, repair_tools()))
        validate_document(
            "cut-repair-composite-receipt-v1.schema.json", composite)
        self.assertEqual(
            set(composite["inputs"]["channelNormalization"]),
            {"parent", "fragment"})
        _assert_balanced(self, candidate)
        rejected = os.path.join(self.temp.name, "rejected.mov")
        with self.assertRaisesRegex(
                RepairRenderError, "already-normalized stereo authority"):
            render_repair_fragment(RepairFragmentRequest(
                operation, content_hash(operation), dead_parent,
                normal_source, rejected, clock, repair_tools()))
        self.assertFalse(os.path.exists(rejected))


if __name__ == "__main__":
    unittest.main(verbosity=2)
