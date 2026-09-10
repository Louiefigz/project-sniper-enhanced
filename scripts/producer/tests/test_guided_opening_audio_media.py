"""Actual synthetic source→whole master→bit-exact excerpt; never creator approval."""
from __future__ import annotations

import contextlib
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import render as renderer
from audio.program_master_bus import build_program_master
from audio.program_master_excerpt import ExcerptRanges, SAMPLE_CLOCK_POLICY, extract_master_audio, read_master_audio
from audio.program_master_selection import SelectionContext, capture_master_selection, read_master_selection
from audio.render_audio_authority import SOURCE_FLOAT_POLICY_V2, admit_audio, run_audio
from audio.render_audio_cache import write_source_bus_pointer
from cut_preview_io import file_hash, write_new
from guided_opening_audio import OpeningAudioDeadline, run
from palmier.process_deadline import use_process_deadline
from test_render_audio_cache_media import with_synthetic_music
from test_render_source_audio_media import _context, _fixture


def _whole_pcm(path: str) -> bytes:
    """Decode once without using production trim logic; Python slices the oracle."""
    return run_audio(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", path,
                      "-map", "0:a:0", "-c:a", "pcm_f32le", "-f", "f32le", "-"])


def _build(root: Path, rate: str) -> object:
    """Use real ordinary cutting/channel repair, retained source authority and master."""
    root.mkdir()
    plan, manifest = _fixture(root, frame_rate=rate)
    manifest = with_synthetic_music(root, manifest)
    plan["music"] = {"enabled": True, "assetId": "test-only-bed", "gapDb": 12}
    context = _context(root, plan, manifest, SOURCE_FLOAT_POLICY_V2)
    context.audio_admission = admit_audio(plan, manifest, (SOURCE_FLOAT_POLICY_V2, False))
    with (root / "ordinary-cut.log").open("w") as log, contextlib.redirect_stdout(log):
        renderer.compile_stage(context)
        base = renderer.cut_stage(context)
    bus = context.source_audio_bus
    write_source_bus_pointer(base, context.out_dir, bus)
    master = build_program_master(bus, plan)
    selection = SelectionContext(Path(context.plan_path), Path(manifest["_path"]), Path(context.out_dir),
        Path(base), Path(master.directory) / "selection-event.json")
    return capture_master_selection(master, plan, selection)


def _input(selection: object, frames: tuple[int, int]) -> dict:
    """Model exact server-captured invocation fields, never fabricated master stats."""
    event = selection.event
    return {"schemaVersion": 1, "kind": "guided-opening-audio-input", "executionInputHash": "e" * 64,
        "sourceSelection": {key: event[key] for key in ("artifactRoot", "basePath", "sourceBusReceiptHash")},
        "programMasterSelection": {"receiptPath": event["programMasterReceiptPath"],
            "receiptHash": event["programMasterReceiptHash"], "sourceBusReceiptHash": event["sourceBusReceiptHash"],
            "audioProgramInputHash": event["audioProgramInputHash"],
            "selectionEventPath": str(selection.context.event_path), "selectionEventHash": selection.event_sha256},
        **{key: event[key] for key in ("planPath", "planSha256", "manifestPath", "manifestSha256")},
        "frameRate": selection.master.source_bus.frame_rate, "totalFrames": selection.master.source_bus.frames,
        "core": {"startFrame": frames[0], "endFrameExclusive": frames[1]},
        "review": {"startFrame": frames[0], "endFrameExclusive": frames[1]},
        "sampleClockPolicy": SAMPLE_CLOCK_POLICY}


class GuidedOpeningAudioMediaTests(unittest.TestCase):
    """Retain generated fixtures/failures for independent media and timing inspection."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(tempfile.mkdtemp(prefix="sniper-opening-audio-", dir="/private/tmp"))
        print(f"Synthetic opening-audio evidence: {cls.root}", flush=True)
        cls.ntsc = _build(cls.root / "ntsc", "30000/1001")
        cls.half = _build(cls.root / "half", "32000/1001")

    def _output(self) -> Path:
        """One new owned private attempt, never a reusable public destination."""
        return Path(tempfile.mkdtemp(prefix="attempt-", dir=self.root))

    def test_actual_half_tie_excerpt_is_exact_absolute_master_slice(self) -> None:
        result = extract_master_audio(self.half, ExcerptRanges((1, 3), (0, 4), "a" * 64),
                                      self._output(), lambda: None)
        core, review = result["core"], result["review"]
        self.assertEqual((core["startSample"], core["endSampleExclusive"], core["samples"]), (1502, 4504, 3002))
        oracle = _whole_pcm(self.half.master.path)
        self.assertEqual(_whole_pcm(core["path"]), oracle[1502 * 8:4504 * 8])
        self.assertEqual(_whole_pcm(review["path"]), oracle[:6006 * 8])
        self.assertFalse(result["normalizationApplied"])
        self.assertFalse(result["fadesApplied"])
        self.assertEqual(read_master_audio(Path(core["path"]).parent, result["receiptHash"], self.half), result)

    def test_actual_ntsc_final_endpoint_preserves_full_master_tail(self) -> None:
        frames = self.ntsc.master.source_bus.frames
        result = extract_master_audio(self.ntsc, ExcerptRanges((100, frames), (100, frames), "b" * 64),
                                      self._output(), lambda: None)
        self.assertEqual(result["core"]["path"], result["review"]["path"])
        self.assertEqual(result["core"]["endSampleExclusive"], 192192)
        self.assertEqual(_whole_pcm(result["core"]["path"]), _whole_pcm(self.ntsc.master.path)[160160 * 8:])
        self.assertEqual(result["scope"], "full-program-master-excerpt-not-opening-or-delivery-approval")
        self.assertFalse(result["browserMedia"])

    def test_cli_uses_actual_held_selection_and_never_creates_public_final(self) -> None:
        output = self._output()
        input_path = output.parent / (output.name + "-input.json")
        write_new(input_path, _input(self.ntsc, (0, 10)))
        command = [sys.executable, str(Path(__file__).parents[1] / "guided_opening_audio.py"),
            str(input_path), str(output), "--input-sha256", file_hash(input_path), "--timeout-seconds", "60"]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=65)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["selectionEventHash"], self.ntsc.event_sha256)
        self.assertEqual(set(path.name for path in output.iterdir()), {"core.wav", "audio-result.json"})
        self.assertFalse(result["openingApproved"])
        self.assertFalse(result["deliveryApproved"])

    def test_changed_input_selection_or_clock_cannot_select_a_different_master(self) -> None:
        for key, value in (("totalFrames", 119), ("frameRate", "30"), ("planSha256", "0" * 64)):
            output = self._output()
            request = _input(self.ntsc, (0, 10))
            request[key] = value
            path = output.parent / (output.name + "-input.json")
            write_new(path, request)
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "differs"):
                run(path, output, (file_hash(path), 60))
            self.assertEqual(list(output.iterdir()), [])

    def test_no_proven_event_rejects_instead_of_scanning_master_directories(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "hash changed"):
            read_master_selection(self.ntsc.context.event_path, "0" * 64)

    def test_late_global_music_change_rejects_unchanged_opening(self) -> None:
        source = Path(self.ntsc.master.receipt["music"]["path"])
        original = source.read_bytes()
        pcm = _whole_pcm(str(source))
        # Modify a valid float WAV sample near its end, not its header or opening.
        changed = bytearray(original)
        changed[-16:-12] = b"\x00\x00\x00\x3f"
        try:
            source.write_bytes(changed)
            self.assertEqual(_whole_pcm(str(source))[:48000 * 8], pcm[:48000 * 8])
            self.assertNotEqual(_whole_pcm(str(source)), pcm)
            output = self._output()
            with self.assertRaisesRegex(RuntimeError, "changed|mismatch|admitted|snapshot is corrupt"):
                extract_master_audio(self.ntsc, ExcerptRanges((0, 10), (0, 10), "c" * 64), output, lambda: None)
            self.assertFalse((output / "audio-result.json").exists())
            self.assertTrue((output / "audio-failed.json").exists())
        finally:
            source.write_bytes(original)

    def test_mutation_at_publication_guard_never_receives_success(self) -> None:
        output = self._output()
        calls = 0

        def mutate() -> None:
            nonlocal calls
            calls += 1
            if calls == 5:
                with (output / "core.wav").open("ab") as handle:
                    handle.write(b"TEST ONLY mutation before receipt")

        with self.assertRaisesRegex(RuntimeError, "bytes changed"):
            extract_master_audio(self.ntsc, ExcerptRanges((0, 10), (0, 10), "d" * 64), output, mutate)
        self.assertFalse((output / "audio-result.json").exists())
        self.assertTrue((output / "audio-failed.json").exists())

    def test_failed_decoder_leaves_unapproved_attempt_only(self) -> None:
        output = self._output()
        with patch("audio.program_master_excerpt.run_audio", side_effect=RuntimeError("TEST ONLY decoder failure")):
            with self.assertRaisesRegex(RuntimeError, "decoder failure"):
                extract_master_audio(self.ntsc, ExcerptRanges((0, 10), (0, 10), "f" * 64), output, lambda: None)
        failed = json.loads((output / "audio-failed.json").read_text())
        self.assertFalse(failed["openingApproved"])
        self.assertEqual(failed["outerProcessGroupCleanup"], "requires-owned-runner-observation")
        self.assertFalse((output / "audio-result.json").exists())

    def test_real_ffmpeg_timeout_reaps_its_actual_child(self) -> None:
        """Actual shared child runner cleanup, not a mock decoder's success flag."""
        children = []
        original = subprocess.Popen

        def capture(*args: object, **kwargs: object) -> subprocess.Popen:
            child = original(*args, **kwargs)
            children.append(child)
            return child

        deadline = OpeningAudioDeadline(time.monotonic() + 0.15)
        with patch("subprocess.Popen", side_effect=capture), use_process_deadline(deadline):
            with self.assertRaises(subprocess.TimeoutExpired):
                run_audio(["ffmpeg", "-nostdin", "-v", "error", "-re", "-f", "lavfi",
                           "-i", "anullsrc=r=48000:cl=stereo:d=5", "-f", "null", "-"])
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())

    def test_deadline_after_receipt_returns_failure_and_retains_both_facts(self) -> None:
        """An on-disk result without successful owned invocation is not selectable."""
        output = self._output()
        calls = 0

        def expire() -> None:
            nonlocal calls
            calls += 1
            if calls == 6:
                raise RuntimeError("TEST ONLY elapsed deadline after receipt write")

        with self.assertRaisesRegex(RuntimeError, "deadline after receipt"):
            extract_master_audio(self.ntsc, ExcerptRanges((0, 10), (0, 10), "f" * 64), output, expire)
        self.assertTrue((output / "audio-result.json").exists())
        self.assertTrue((output / "audio-failed.json").exists())
        orphan = json.loads((output / "audio-result.json").read_text())
        with self.assertRaisesRegex(RuntimeError, "attempt failed"):
            read_master_audio(output, orphan["receiptHash"], self.ntsc)

    def test_existing_output_is_not_overwritten_even_when_it_is_private(self) -> None:
        output = self._output()
        path = output / "core.wav"
        path.write_bytes(b"TEST ONLY previous candidate")
        with self.assertRaisesRegex(RuntimeError, "empty private"):
            extract_master_audio(self.ntsc, ExcerptRanges((0, 10), (0, 10), "f" * 64), output, lambda: None)
        self.assertEqual(path.read_bytes(), b"TEST ONLY previous candidate")

    def test_global_plan_changed_at_last_guard_rejects_before_publication(self) -> None:
        output = self._output()
        path = self.ntsc.context.plan_path
        original = path.read_bytes()
        calls = 0

        def change() -> None:
            nonlocal calls
            calls += 1
            if calls == 5:
                plan = json.loads(original)
                plan["music"]["gapDb"] = 11
                path.write_text(json.dumps(plan))

        try:
            with self.assertRaisesRegex(RuntimeError, "hash changed"):
                extract_master_audio(self.ntsc, ExcerptRanges((0, 10), (0, 10), "f" * 64), output, change)
            self.assertFalse((output / "audio-result.json").exists())
        finally:
            path.write_bytes(original)

    def test_readback_requires_held_result_and_current_bytes(self) -> None:
        output = self._output()
        record = extract_master_audio(self.ntsc, ExcerptRanges((0, 10), (0, 10), "b" * 64), output, lambda: None)
        with self.assertRaisesRegex(RuntimeError, "held successful execution"):
            read_master_audio(output, "0" * 64, self.ntsc)
        with Path(record["core"]["path"]).open("ab") as handle:
            handle.write(b"TEST ONLY after successful extraction")
        with self.assertRaisesRegex(RuntimeError, "bytes changed"):
            read_master_audio(output, record["receiptHash"], self.ntsc)

    def test_readback_rejects_stale_global_plan_even_when_pcm_is_unchanged(self) -> None:
        output = self._output()
        record = extract_master_audio(self.ntsc, ExcerptRanges((0, 10), (0, 10), "b" * 64), output, lambda: None)
        path, original = self.ntsc.context.plan_path, self.ntsc.context.plan_path.read_bytes()
        try:
            plan = json.loads(original)
            plan["music"]["gapDb"] = 11
            path.write_text(json.dumps(plan))
            with self.assertRaisesRegex(RuntimeError, "hash changed"):
                read_master_audio(output, record["receiptHash"], self.ntsc)
        finally:
            path.write_bytes(original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
