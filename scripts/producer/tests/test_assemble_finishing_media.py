"""Caller-shaped evidence: render.py base -> assemble.py -> revisions, finishing on real media.

This drives the actual ordinary callers (not mocks): the source-float-v2 base render admits a plan
with cleanup, gain and an SFX seam, assemble builds the finished full-program master and delivers it,
then a gain revision, a non-audio revision, an invalid request and an opening excerpt are exercised.
Numbers here are not creator listening approval.
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import assemble
import render as renderer
from audio.assemble_source_audio import PROGRAM_AUDIO_POINTER
from audio.audio_mix_picture import packet_signature
from audio.program_master_cache import load_program_master
from audio.program_master_excerpt import ExcerptRanges, extract_master_audio
from audio.program_master_selection import SelectionContext, capture_master_selection
from audio.render_audio_authority import SOURCE_FLOAT_POLICY_V2
from audio.render_audio_cache import load_source_bus
from cut_delivery_authority import RenderSeal, seal_render_delivery
from cut_preview_io import bound_json, file_hash
from fingerprints import plan_content_hash
from test_program_finish_media import GAIN, decoded
from test_render_audio_cache_media import with_synthetic_music
from test_render_source_audio_media import _context, _fixture

SEAM = [{"outTime": 1.0, "kind": "white-flash", "sfx": True}]


def _events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.startswith("{")]


def _relative_error(actual, reference) -> float:
    """RMS of the difference relative to the reference RMS over the common prefix."""
    count = min(len(actual), len(reference))
    diff = sum((actual[i] - reference[i]) ** 2 for i in range(count))
    energy = sum(reference[i] ** 2 for i in range(count))
    return (diff / energy) ** 0.5


class CallerShapedFinishingTests(unittest.TestCase):
    """Retain every generated directory for inspection; assert exact identities."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(tempfile.mkdtemp(prefix="sniper-finishing-assembly-", dir="/private/tmp"))
        print(f"Caller-shaped finishing evidence: {cls.root}", flush=True)
        fixture_plan, cls.manifest = _fixture(cls.root)
        cls.manifest = with_synthetic_music(cls.root, cls.manifest)
        cls.plan = {**fixture_plan, "audioEnhance": {"preset": "voice"},
                    "audioGain": copy.deepcopy(GAIN), "transitions": copy.deepcopy(SEAM)}
        cls.ctx = _context(cls.root, cls.plan, cls.manifest, SOURCE_FLOAT_POLICY_V2)
        cls.ctx.skip_graphics = True
        cls.output = Path(cls.ctx.out_dir)
        with (cls.root / "base.log").open("w") as log, contextlib.redirect_stdout(log):
            renderer.render(cls.ctx, audit=True)
        cls.base_events = _events(cls.root / "base.log")
        cls.base = cls.output / "base.mp4"
        os.replace(cls.output / "final.mp4", cls.base)
        seal_render_delivery(str(cls.output), str(cls.base), cls.plan, RenderSeal(True, SOURCE_FLOAT_POLICY_V2))
        cls.job = assemble.AssembleJob(str(cls.base), cls.plan, str(cls.output / "final.mp4"), None,
            fingerprint_path=str(cls.output / "base.fingerprint.json"), manifest=cls.manifest["_path"],
            audio_clock_policy=SOURCE_FLOAT_POLICY_V2, plan_path=cls.ctx.plan_path,
            source_bus_receipt_hash=cls.ctx.source_audio_bus.receipt["receiptHash"])
        cls.result = cls._assemble(cls.plan, "assemble")

    @classmethod
    def _assemble(cls, plan: dict, label: str) -> dict:
        Path(cls.ctx.plan_path).write_text(json.dumps(plan))
        with (cls.root / f"{label}.log").open("w") as log, contextlib.redirect_stdout(log):
            return assemble.assemble(replace(cls.job, plan=plan))

    def _pointer(self) -> dict:
        return bound_json(self.output / PROGRAM_AUDIO_POINTER)

    def test_01_base_admits_finishing_and_skips_the_legacy_audio_stages(self) -> None:
        policy = next(row for row in self.base_events if row.get("stage") == "audio_policy")
        self.assertEqual(policy["status"], "admitted")
        skipped = {row["stage"]: row for row in self.base_events if row.get("status") == "stage_skipped"}
        for stage in ("audio_enhance", "audio_gain"):
            self.assertIn(stage, skipped)
            self.assertIn("float program", skipped[stage]["reason"])
        transitions = next(row for row in self.base_events
                           if row.get("stage") == "transitions" and row.get("status") == "stage_done")
        self.assertEqual(transitions["events"], 1)
        fingerprint = bound_json(self.output / "base.fingerprint.json")
        self.assertEqual(len(fingerprint.get("sourceAudioBusReceiptHash", "")), 64)
        base_master = bound_json(Path(self.ctx.source_audio_bus.directory) / "master-receipt.json")
        self.assertEqual(base_master["kind"], "ordinary-source-float-master")
        self.assertTrue(base_master["delivery"]["qualified"])

    def test_02_assembled_final_carries_the_finished_program_audio(self) -> None:
        self.assertTrue(self.result["delivery"]["qualified"])
        self.assertFalse(self.result["programMasterReused"])
        receipt = bound_json(Path(self._pointer()["programMasterReceiptPath"]))
        self.assertEqual(receipt["schemaVersion"], 3)
        self.assertIn(receipt["masteringDecision"]["branch"], {"linear", "static", "dynamic"})
        self.assertTrue(receipt["masteringFilter"].startswith(receipt["masteringDecision"]["filter"]))
        finishing = receipt["finishing"]
        self.assertEqual(finishing["settings"]["audioGain"], [{"outStart": 1.0, "outEnd": 1.5, "dB": 6.0}])
        self.assertEqual(finishing["settings"]["audioEnhance"], {"preset": "voice"})
        self.assertEqual(finishing["sfx"]["cues"][0]["startSample"], 33_600)
        self.assertGreater(finishing["cleanup"]["measuredLatencySamples"], 0)
        self.assertTrue(receipt["wholeProgramMeasurement"]["qualified"])
        final, master = decoded(self.job.out), decoded(receipt["masteredAudio"]["path"])
        self.assertLessEqual(abs(len(final) - len(master)), 2 * 1024)
        self.assertLess(_relative_error(final, master), 0.05,
                        "the delivered AAC must be the finished float master, codec residual only")
        self.assertEqual(packet_signature(str(self.base), "v:0"), packet_signature(self.job.out, "v:0"))

    def test_03_gain_revision_keeps_base_current_and_picture_and_rebuilds_only_the_master(self) -> None:
        """No render graph exists here, so the picture is a fresh no-graphics passthrough whose
        packets are asserted identical; graph-backed picture reuse is proved in
        test_current_render_graph_audio_media, not by this test."""
        plan = copy.deepcopy(self.plan)
        plan["audioGain"][0]["dB"] = 3
        state = assemble._base_state(str(self.base), plan, self.job.fingerprint_path, SOURCE_FLOAT_POLICY_V2)
        self.assertEqual(state, "current", "finishing-only edits never rebuild the v2 base or its raw bus")
        with contextlib.redirect_stdout(io.StringIO()):
            ensured, resolved = assemble.ensure_base(str(self.base), self.ctx.plan_path, plan,
                self.job.fingerprint_path, assemble.BaseManifest(self.manifest["_path"], SOURCE_FLOAT_POLICY_V2))
        self.assertEqual((ensured, resolved), (plan, "current"))
        before_picture, before = packet_signature(self.job.out, "v:0"), self._pointer()
        result = self._assemble(plan, "gain-revision")
        self.assertTrue(result["delivery"]["qualified"])
        self.assertFalse(result["programMasterReused"])
        self.assertFalse(result.get("pictureReusedForAudioRevision", False))
        self.assertEqual(before_picture, packet_signature(self.job.out, "v:0"))
        after = self._pointer()
        self.assertNotEqual(before["audioProgramInputHash"], after["audioProgramInputHash"])
        self.assertEqual(before["pictureReuseInputHash"], after["pictureReuseInputHash"])
        receipt = bound_json(Path(after["programMasterReceiptPath"]))
        self.assertEqual(receipt["finishing"]["settings"]["audioGain"][0]["dB"], 3.0)
        self.assertEqual(receipt["sourceBusReceiptHash"], self.job.source_bus_receipt_hash,
                         "the original admitted source dialogue is reused")
        rebuilt = [row for row in _events(self.root / "gain-revision.log") if row.get("status") == "program_master_rebuilt"]
        self.assertEqual(len(rebuilt), 1)
        self.assertIn("no held prior render graph", rebuilt[0]["reason"])
        type(self).plan = plan

    def test_04_non_audio_revision_without_a_held_graph_never_reuses_the_pointer(self) -> None:
        """The public pointer alone is not authority: with no prior ACTIVE render graph the
        retained master is declined and rebuilt (held reuse is proved in the graph-flow test)."""
        plan = {**copy.deepcopy(self.plan), "chapters": [{"outStart": 0.0, "title": "TEST chapter"}]}
        before_picture, before = packet_signature(self.job.out, "v:0"), self._pointer()
        result = self._assemble(plan, "chapters-revision")
        self.assertFalse(result["programMasterReused"])
        self.assertTrue(result["delivery"]["qualified"])
        after = self._pointer()
        self.assertEqual(after["audioProgramInputHash"], before["audioProgramInputHash"],
                         "same audio inputs: the rebuilt master is equivalent, only its receipt is new")
        self.assertEqual(before_picture, packet_signature(self.job.out, "v:0"))
        rebuilt = [row for row in _events(self.root / "chapters-revision.log") if row.get("status") == "program_master_rebuilt"]
        self.assertEqual(len(rebuilt), 1)
        self.assertIn("no held prior render graph", rebuilt[0]["reason"])
        self.assertEqual(bound_json(Path(self.job.out + ".assembled.json"))["planHash"], plan_content_hash(plan))
        type(self).plan = plan

    def test_05_invalid_finishing_is_refused_before_media_and_keeps_the_accepted_final(self) -> None:
        bad = {**copy.deepcopy(self.plan), "audioGain": [{"outStart": 0, "outEnd": 2, "dB": 1},
                                                          {"outStart": 1, "outEnd": 3, "dB": 1}]}
        names = ("final.mp4", "final.mp4.assembled.json", PROGRAM_AUDIO_POINTER)
        before = {name: file_hash(self.output / name) for name in names}
        Path(self.ctx.plan_path).write_text(json.dumps(bad))
        try:
            with self.assertRaisesRegex(RuntimeError, "rejects audioGain: .*overlap"), \
                    contextlib.redirect_stdout(io.StringIO()):
                assemble.assemble(replace(self.job, plan=bad))
        finally:
            Path(self.ctx.plan_path).write_text(json.dumps(self.plan))
        self.assertEqual(before, {name: file_hash(self.output / name) for name in names})
        fresh = _context(self.root / "invalid", bad, self.manifest, SOURCE_FLOAT_POLICY_V2)
        fresh.skip_graphics = True
        with self.assertRaisesRegex(RuntimeError, "rejects audioGain"), contextlib.redirect_stdout(io.StringIO()):
            renderer.render(fresh, audit=False)
        self.assertEqual(list(Path(fresh.work_dir).iterdir()), [], "refused at admission, before any stage ran")

    def test_06_opening_excerpt_from_the_published_pointer_is_the_delivered_finished_program(self) -> None:
        plan = bound_json(Path(self.ctx.plan_path))
        manifest = bound_json(Path(self.manifest["_path"]))
        manifest["_path"] = self.manifest["_path"]
        pointer = self._pointer()
        bus = load_source_bus(plan, manifest, (str(self.output), str(self.base)), self.job.source_bus_receipt_hash)
        master = load_program_master(bus, plan, (pointer["programMasterReceiptPath"], pointer["programMasterReceiptHash"]))
        self.assertEqual(master.receipt["finishing"]["settings"]["audioGain"][0]["dB"], 3.0)
        context = SelectionContext(Path(self.ctx.plan_path), Path(self.manifest["_path"]), self.output, self.base,
                                   Path(master.directory) / "selection-event.json")
        selection = capture_master_selection(master, plan, context)
        output = Path(tempfile.mkdtemp(prefix="attempt-", dir=self.root))
        result = extract_master_audio(selection, ExcerptRanges((0, 45), (0, 45), "c" * 64), output, lambda: None)
        core, whole = decoded(result["core"]["path"]), decoded(master.path)
        self.assertEqual(result["core"]["endSampleExclusive"], 72_072)
        self.assertEqual(core.tobytes(), whole[:len(core)].tobytes())
        self.assertLess(_relative_error(decoded(self.job.out), core), 0.05,
                        "the opening excerpt is a slice of the same finished program the final carries")


    def test_07_standalone_render_never_silently_omits_requested_finishing(self) -> None:
        """Codex blocker: a monolithic source-float-v2 render with finishing is refused before any
        stage; legacy-v1 still applies finishing through its own stages; source-float-v1 refuses at
        admission; and the v2 base reports its finishing as deferred, not done."""
        report = bound_json(self.output / "render_report.json")
        self.assertEqual(report["audioFinishing"], "deferred-to-assemble")
        self.assertTrue(any(row.get("status") == "audio_finishing_deferred" for row in self.base_events))
        monolithic = _context(self.root / "standalone-v2", self.plan, self.manifest, SOURCE_FLOAT_POLICY_V2)
        with self.assertRaisesRegex(RuntimeError, "monolithic delivery is not qualified"), \
                contextlib.redirect_stdout(io.StringIO()):
            renderer.render(monolithic, audit=False)
        self.assertEqual(list(Path(monolithic.work_dir).iterdir()), [], "refused before any stage ran")
        self.assertFalse((Path(monolithic.out_dir) / "final.mp4").exists())
        v1 = _context(self.root / "standalone-v1", self.plan, self.manifest, "source-float-v1")
        with self.assertRaisesRegex(RuntimeError, "has not qualified"), contextlib.redirect_stdout(io.StringIO()):
            renderer.render(v1, audit=False)
        self.assertEqual(list(Path(v1.work_dir).iterdir()), [])
        legacy = _context(self.root / "standalone-legacy", self.plan, self.manifest, "legacy-v1")
        with (self.root / "legacy.log").open("w") as log, contextlib.redirect_stdout(log):
            legacy_report = renderer.render(legacy, audit=False)
        events = _events(self.root / "legacy.log")
        done = {row["stage"] for row in events if row.get("status") == "stage_done"}
        self.assertTrue({"audio_enhance", "audio_gain"} <= done, done)
        self.assertEqual(legacy_report["audioFinishing"], "applied-by-legacy-stages")
        self.assertTrue((Path(legacy.out_dir) / "final.mp4").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
