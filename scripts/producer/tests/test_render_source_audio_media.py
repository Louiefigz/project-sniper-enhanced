"""Actual ordinary final renders against synthetic source-content clock oracles."""
from __future__ import annotations

import array
import contextlib
import json
import tempfile
import subprocess
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import render as renderer
from _cut_preview_fixture import ffmpeg
from _ingest_admission_fixture import runner as admission_fixture
from audio.render_audio_authority import (SOURCE_FLOAT_POLICY, admit_audio,
                                          audio_policy_reason, seal_audio_record)
from audio.render_audio_bus import BusRender, render_source_bus, verify_source_bus
from audio.audio_mix_picture import packet_signature
from fingerprints import file_sha256
from ingest_admission import admit_ingest_candidates, collect_ingest_candidates
from test_cut_preview import center


def pcm(path: Path) -> bytes:
    """Independent source/output oracle isolates the synthetic event frequency."""
    return subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path),
        "-map", "0:a:0", "-af", "bandpass=f=880:w=300", "-ar", "48000", "-ac", "2",
        "-c:a", "pcm_s16le", "-f", "s16le", "-"],
        capture_output=True, check=True, timeout=20).stdout


def _media(root: Path, size: str = "160x90", frame_rate: str = "30000/1001") -> dict:
    """Generate two different audio layouts/rates plus a declared silent source."""
    source = root / "source"
    source.mkdir()
    paths = [root / name for name in ("stereo.mp4", "right-only.mp4", "silent.mp4")]
    video = ["-f", "lavfi", "-i", f"testsrc2=size={size}:rate={frame_rate}:duration=4"]
    events = "+".join(f"between(t,{start},{start + 0.02})" for start in (0.2, 1.42, 1.8, 2.92, 3.92))
    expression = f"0.1*sin(2*PI*3000*t)+if({events},0.2*sin(2*PI*880*t),0)"
    for index, rate in ((0, 48000), (1, 44100)):
        audio = expression if index == 0 else f"0|{expression}"
        ffmpeg([*video, "-f", "lavfi", "-i", f"aevalsrc='{audio}':s={rate}:d=4",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2", str(paths[index])])
    ffmpeg([*video, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(paths[2])])
    admitted = admit_ingest_candidates(collect_ingest_candidates(paths, None, None), source, admission_fixture)
    rows = []
    for identity, original in zip(("raw-1", "right-2", "silent"), paths):
        item = admitted.media_by_original[str(original)]
        rows.append({"id": identity, "duration": 4, "path": item.snapshot_path,
            "originalPath": item.original_path, "sourceSha256": item.sha256,
            "admissionReceiptPath": item.receipt_path, "admissionReceiptSha256": item.receipt_sha256})
    return {"sources": rows, "sourceSetAdmission": admitted.binding}


def _fixture(root: Path, size: str = "160x90", frame_rate: str = "30000/1001") -> tuple[dict, dict]:
    """Reuse only synthetic admitted media, not preview request/approval fixtures."""
    manifest = _media(root, size, frame_rate)
    manifest_path = root / "source/asset_manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    manifest["_path"] = str(manifest_path)
    plan = {"planVersion": 1, "target": {"mode": "longform", "excerpt": True, "scope": "trim"},
            "captions": {"burn": False}, "cutTrack": [
                {"sourceId": "raw-1", "start": 0, "end": 1},
                {"sourceId": "right-2", "start": 1.5, "end": 3, "audioLeadMs": 100},
                {"sourceId": "silent", "start": 0, "end": 1},
                {"sourceId": "raw-1", "start": 3.5, "end": 4}]}
    return plan, manifest


def _context(root: Path, plan: dict, manifest: dict, policy: str) -> renderer.RenderCtx:
    """Persist a genuine ordinary-render plan/output directory and private work."""
    output = root / policy
    work = output / "work"
    work.mkdir(parents=True)
    plan_path = output / "edit_plan.json"
    plan_path.write_text(json.dumps(plan))
    return renderer.RenderCtx(plan, manifest, str(output), str(work),
                              plan_path=str(plan_path), audio_clock_policy=policy)


class OrdinarySourceFloatMediaTests(unittest.TestCase):
    """Keep artifacts/logs for diagnosis; no creator quality or SLA assertion."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(tempfile.mkdtemp(prefix="sniper-f1-ordinary-", dir="/private/tmp"))
        cls.plan, cls.manifest = _fixture(cls.root)
        cls.sources = {row["id"]: array.array("h", pcm(Path(row["path"])))
                       for row in cls.manifest["sources"] if row["id"] != "silent"}
        # Independent reference selects the known live right channel and
        # duplicates it; production receipt must independently reach that choice.
        right = cls.sources["right-2"]
        cls.sources["right-2"] = array.array("h", (right[index | 1] for index in range(len(right))))
        cls.contexts, cls.reports = {}, {}
        for policy in ("legacy-v1", SOURCE_FLOAT_POLICY):
            context = _context(cls.root, cls.plan, cls.manifest, policy)
            cls.contexts[policy] = context
            with (cls.root / f"{policy}.log").open("w") as log, contextlib.redirect_stdout(log):
                try:
                    cls.reports[policy] = renderer.render(context, audit=policy == SOURCE_FLOAT_POLICY)
                except Exception as exc:
                    print(f"FAILED: {type(exc).__name__}: {exc}")
                    raise RuntimeError(f"ordinary fixture retained at {cls.root}: {exc}") from exc

    def test_ordinary_mezzanine_now_aligns_with_source_content_within_the_preview_tolerance(self) -> None:
        """Until 2026-09-06 this pinned the ordinary path as MISALIGNED (>3 ms; a 12.5 ms
        shift). Exact cumulative sample clocks, one AAC generation and the exact-window
        declick moved it inside the private preview's 3 ms tolerance (measured 0.85 ms on
        this fixture). Duration success alone still proves nothing; content alignment does."""
        samples = array.array("h", pcm(self.root / "legacy-v1/final.mp4"))
        self.assertLess(abs(center(samples, 0.2) - center(self.sources["raw-1"], 0.2)), 0.003)

    def test_actual_final_preserves_interior_jcut_and_retained_end_events(self) -> None:
        samples = array.array("h", pcm(self.root / SOURCE_FLOAT_POLICY / "final.mp4"))
        for source_time, mapped_time in ((0.2, 0.2), (1.42, 0.92), (1.8, 1.301),
                                         (2.92, 2.421), (3.92, 3.9235)):
            source = self.sources["raw-1" if source_time in {0.2, 3.92} else "right-2"]
            expected = center(source, source_time) + mapped_time - source_time
            self.assertLess(abs(center(samples, mapped_time) - expected), 0.003,
                            f"source event {source_time}: expected={expected},actual={center(samples, mapped_time)}")

    def test_actual_full_audit_and_exact_picture_audio_clock_proof(self) -> None:
        report = self.reports[SOURCE_FLOAT_POLICY]
        self.assertNotEqual(report["audit"]["overall"], "fail")
        receipt = json.loads(Path(report["master"]["source_audio_receipt"]).read_text())
        self.assertFalse(receipt["approved"])
        self.assertTrue(receipt["delivery"]["qualified"])
        self.assertTrue(receipt["picture"]["picturePacketsIdentical"])
        self.assertEqual(packet_signature(str(self.root / "legacy-v1/final.mp4"), "v:0"),
                         packet_signature(str(self.root / SOURCE_FLOAT_POLICY / "final.mp4"), "v:0"))
        self.assertEqual(receipt["audioClock"]["presentedSamples"], 192192)
        self.assertEqual(receipt["sha256"], file_sha256(str(self.root / SOURCE_FLOAT_POLICY / "final.mp4")))
        self.assertEqual(receipt["audiblePathAacEncodes"], 1)
        self.assertTrue(receipt["legacyPictureTransportAacStillExecuted"])
        bus = self.contexts[SOURCE_FLOAT_POLICY].source_audio_bus
        channels = bus.receipt["channelReceipts"]
        self.assertEqual(len(channels), 2)
        self.assertTrue(any(row["receipt"]["decision"]["status"] == "dead-channel-repaired"
                            and row["receipt"]["stream"]["sampleRate"] == 44100 for row in channels))

    def test_changed_retained_bus_rejected_before_mastering(self) -> None:
        bus = self.contexts[SOURCE_FLOAT_POLICY].source_audio_bus
        self.assertIsNotNone(bus)
        original = file_sha256(bus.path)
        with patch("audio.render_audio_bus.file_sha256", return_value="0" * 64):
            with self.assertRaisesRegex(RuntimeError, "dialogue bus changed"):
                verify_source_bus(bus, self.plan)
        self.assertEqual(file_sha256(bus.path), original)

    def test_actual_silent_source_byte_drift_is_not_ignored(self) -> None:
        bus = self.contexts[SOURCE_FLOAT_POLICY].source_audio_bus
        source = Path(next(row["path"] for row in self.manifest["sources"] if row["id"] == "silent"))
        original = source.read_bytes()
        try:
            with source.open("ab") as handle:
                handle.write(b"synthetic-source-drift")
            with self.assertRaisesRegex(RuntimeError, "admitted bytes changed"):
                verify_source_bus(bus, self.plan)
        finally:
            source.write_bytes(original)
        self.assertEqual(file_sha256(str(source)), bus.admission.sources[2]["sha256"])

    def test_missing_incoming_channel_receipt_rejects_jcut_before_bus_decode(self) -> None:
        ctx = self.contexts[SOURCE_FLOAT_POLICY]
        bus = ctx.source_audio_bus
        receipts = [row for row in bus.receipt["channelReceipts"]
                    if row["receipt"]["decision"]["status"] != "dead-channel-repaired"]
        parts = tuple(str(Path(ctx.work_dir) / "cut-parts" / f"part_{index:04d}.mp4") for index in range(4))
        with self.assertRaisesRegex(RuntimeError, "missing its current channel receipt"):
            render_source_bus(BusRender(self.plan, bus.admission, ctx.out_dir, parts,
                                        {"channelNormalizationReceipts": receipts}))

    def test_real_s32_bus_cannot_be_resealed_as_float(self) -> None:
        bus = self.contexts[SOURCE_FLOAT_POLICY].source_audio_bus
        directory = Path(tempfile.mkdtemp(prefix=".wrong-bus-", dir=self.contexts[SOURCE_FLOAT_POLICY].out_dir))
        wrong = directory / "dialogue.wav"
        ffmpeg(["-i", bus.path, "-c:a", "pcm_s32le", str(wrong)])
        body = {key: value for key, value in bus.receipt.items() if key != "receiptHash"}
        body.update(path=str(wrong), sha256=file_sha256(str(wrong)))
        receipt = seal_audio_record(str(directory / "bus-receipt.json"), body)
        forged = replace(bus, path=str(wrong), sha256=body["sha256"], directory=str(directory), receipt=receipt)
        with self.assertRaisesRegex(RuntimeError, "format or exact sample clock"):
            verify_source_bus(forged, self.plan)

    def test_unqualified_real_candidate_preserves_prior_final_and_sidecar(self) -> None:
        ctx = self.contexts[SOURCE_FLOAT_POLICY]
        final = Path(ctx.out_dir) / "final.mp4"
        sidecar = Path(str(final) + ".assembled.json")
        before = (file_sha256(str(final)), sidecar.read_bytes())
        from audio.mastering_filter import MasterFilterSelection
        selected = MasterFilterSelection("volume=-30dB", "fault injection", {"TEST": True})
        with patch("audio.render_audio_master.select_pass2_filter", return_value=selected):
            with self.assertRaisesRegex(RuntimeError, "unqualified; prior output preserved"):
                renderer.master_stage(ctx, str(Path(ctx.work_dir) / "mezzanine.mp4"), None)
        self.assertEqual((file_sha256(str(final)), sidecar.read_bytes()), before)
        failed = json.loads((Path(ctx.source_audio_bus.directory) / "master-failed.json").read_text())
        self.assertFalse(failed["result"]["published"])
        self.assertTrue(Path(failed["result"]["unapprovedCandidate"]).is_file())


class OrdinaryAudioAdmissionTests(unittest.TestCase):
    """Fail explicit capability requests before any silent legacy fallback."""

    def test_unknown_plan_roots_fail_before_source_admission(self) -> None:
        """Undeclared audio lanes reject even when their value is empty."""
        plain = {"cutTrack": [{"sourceId": "a", "start": 0, "end": 1}]}
        for unsupported in ({"sfxTrack": []}, {"futureAudioLane": {"enabled": True}}):
            plan = {**plain, **unsupported}
            self.assertIn("unregistered", audio_policy_reason(plan) or "")
            with self.assertRaisesRegex(RuntimeError, "unregistered"):
                admit_audio(plan, {}, (SOURCE_FLOAT_POLICY, False))

    def test_nonunity_legacy_remains_available_but_float_request_rejects(self) -> None:
        plan = {"cutTrack": [{"sourceId": "raw", "start": 0, "end": 1, "speed": 1.25}]}
        self.assertIsNone(admit_audio(plan, {}, ("legacy-v1", False)))
        with self.assertRaisesRegex(RuntimeError, "source speed 1"):
            admit_audio(plan, {}, (SOURCE_FLOAT_POLICY, False))

    def test_effects_and_resume_are_not_silently_ignored(self) -> None:
        plain = {"cutTrack": [{"sourceId": "a", "start": 0, "end": 1}]}
        for effect in ({"audioEnhance": {"preset": "voice"}}, {"audioGain": [{"dB": 1}]},
                       {"transitions": [{"sfx": True}]}, {"music": {"enabled": True}}):
            with self.subTest(effect=effect):
                self.assertIsNotNone(audio_policy_reason({**plain, **effect}))
        with self.assertRaisesRegex(RuntimeError, "fresh execution"):
            admit_audio(plain, {}, (SOURCE_FLOAT_POLICY, True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
