"""Actual tiny base/master reuse, not authenticated guided-body approval."""
from __future__ import annotations

import contextlib
import copy
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from assemble import AssembleJob, assemble
from audio.held_program_preparation import load_held_program_preparation
from audio.assemble_source_audio import _staged_job
from audio.audio_mix_picture import packet_signature
from audio.program_audio_clock import aac_audio_clock
from cut_preview_io import file_hash, write_new
from guided_opening_inputs import OpeningInputs
from guided_opening_prepare import prepare_full_program
from test_render_audio_cache_media import with_synthetic_music
from test_render_source_audio_media import _fixture


class HeldPreparationTests(unittest.TestCase):
    """Use genuine current source/bus/PCM receipts and real ordinary assembly."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(tempfile.mkdtemp(prefix="sniper-held-preparation-", dir="/private/tmp"))
        print(f"Retained TEST-only held preparation fixture: {cls.root}", flush=True)
        cls.plan, manifest = _fixture(cls.root)
        chord = ("aevalsrc='0.04*(sin(2*PI*(220+55*floor(t/0.5))*t)"
                 "+sin(2*PI*(277.18+69.295*floor(t/0.5))*t)"
                 "+sin(2*PI*(329.63+82.4075*floor(t/0.5))*t))':s=48000:d=3")
        cls.manifest = with_synthetic_music(cls.root, manifest, chord)
        for cut in cls.plan["cutTrack"]:
            cut.pop("audioLeadMs", None)
        cls.plan["target"].update(width=160, height=90, fps=30)
        cls.plan["music"] = {"enabled": True, "assetId": "test-only-bed", "gapDb": 12}
        cls.plan_path = cls.root / "candidate.json"
        write_new(cls.plan_path, cls.plan)
        refs = {"candidatePlan": {"path": str(cls.plan_path), "sha256": file_hash(cls.plan_path)},
            "manifest": {"path": cls.manifest["_path"], "sha256": file_hash(Path(cls.manifest["_path"]))}}
        inputs = OpeningInputs(cls.plan_path, file_hash(cls.plan_path), {"documents": refs},
            {"candidatePlan": cls.plan, "manifest": cls.manifest,
             "authority": {"frameRate": "30000/1001", "totalFrames": 120,
                           "target": cls.plan["target"]}})
        output = cls.root / "opening"
        output.mkdir(mode=0o700)
        with (cls.root / "prepare.log").open("w") as log, contextlib.redirect_stdout(log):
            cls.prepared = prepare_full_program(inputs, output)
        cls.selection = cls.prepared.selection

    def job(self, label: str) -> AssembleJob:
        """Derive the internal handoff from the actual returned selection only."""
        output = self.root / label
        output.mkdir(mode=0o700)
        context = self.selection.context
        return AssembleJob(str(context.base_path), copy.deepcopy(self.plan), str(output / "final.mp4"), None,
            fingerprint_path=str(context.artifact_root / "base.fingerprint.json"),
            manifest=str(context.manifest_path), audio_clock_policy="source-float-v2",
            plan_path=str(context.plan_path), held_program_selection=(str(context.event_path), self.selection.event_sha256))

    def test_01_actual_assembly_reuses_same_master_and_base_without_rebuilding(self) -> None:
        job = self.job("body")
        opening = self.prepared.base.parent.parent
        before = {path: path.read_bytes() for path in opening.rglob("*") if path.is_file()}
        with patch("audio.assemble_source_audio.build_program_master", side_effect=AssertionError("no remaster")), \
                patch("render.render", side_effect=AssertionError("no base render")), \
                (self.root / "body.log").open("w") as log, contextlib.redirect_stdout(log):
            result = assemble(job)
        self.assertEqual(result["programAudio"]["programMasterReceiptHash"], self.selection.master.receipt["receiptHash"])
        self.assertTrue(result["delivery"]["qualified"])
        self.assertFalse(result["preparationReuse"]["baseAudioSelected"])
        self.assertFalse(result["preparationReuse"]["programRemastered"])
        self.assertEqual(packet_signature(job.base, "v:0"), packet_signature(job.out, "v:0"))
        clock = aac_audio_clock(job.out, self.selection.master.source_bus)
        self.assertEqual(clock["presentedSamples"], 192192)
        self.assertEqual(before, {path: path.read_bytes() for path in opening.rglob("*") if path.is_file()})
        self.assertTrue((Path(job.out).parent / "audit_report.json").is_file())
        self.assertTrue((Path(job.out).parent / "timeline_map.json").is_file())
        self.assertFalse((Path(job.out).parent / "APPROVED_HEAD.json").exists())

    def test_02_supplied_stale_selection_never_falls_back(self) -> None:
        job = self.job("stale")
        job.held_program_selection = (str(self.selection.context.event_path), "0" * 64)
        with patch("audio.assemble_source_audio.build_program_master") as rebuild:
            with self.assertRaisesRegex(RuntimeError, "hash changed"):
                assemble(job)
        rebuild.assert_not_called()
        self.assertEqual(list(Path(job.out).parent.iterdir()), [])

    def test_03_exact_plan_manifest_base_and_source_binding_are_required(self) -> None:
        job = self.job("identities")
        changed = copy.deepcopy(job.plan)
        changed["music"]["gapDb"] = 13
        cases = {"plan": replace(job, plan=changed), "manifest": replace(job, manifest=str(self.plan_path)),
            "base": replace(job, base=str(self.root / "different.mp4")),
            "receipt": replace(job, source_bus_receipt_hash="0" * 64)}
        for label, candidate in cases.items():
            with self.subTest(label=label), self.assertRaisesRegex(RuntimeError, "differs|unchanged"):
                load_held_program_preparation(candidate)

    def test_04_changed_master_and_source_bytes_reject(self) -> None:
        job = self.job("media-drift")
        paths = [Path(self.selection.master.path), Path(self.manifest["sources"][0]["path"])]
        for path in paths:
            original = path.read_bytes()
            try:
                path.write_bytes(original + b"TEST-only corruption")
                with self.subTest(path=path.name), self.assertRaises((RuntimeError, ValueError)):
                    load_held_program_preparation(job)
            finally:
                path.write_bytes(original)

    def test_05_import_requires_empty_separate_private_output(self) -> None:
        job = self.job("private")
        for output in (self.prepared.base, Path(job.out)):
            candidate = replace(job, out=str(output))
            if output == Path(job.out):
                output.write_bytes(b"TEST prior output remains")
            with self.subTest(output=str(output)), self.assertRaisesRegex(RuntimeError, "private|empty"):
                load_held_program_preparation(candidate)
        self.assertEqual(Path(job.out).read_bytes(), b"TEST prior output remains")

    def test_06_post_composite_support_drift_blocks_publication(self) -> None:
        from assemble import _assemble_captioned
        job = self.job("late-drift")
        support = self.selection.context.artifact_root / "cover.png"
        original = support.read_bytes()
        def changed(candidate: AssembleJob) -> dict:
            result = _assemble_captioned(candidate)
            support.write_bytes(original + b"TEST late support drift")
            return result
        try:
            with patch("assemble._assemble_captioned", side_effect=changed), \
                    (self.root / "late-drift.log").open("w") as log, contextlib.redirect_stdout(log):
                with self.assertRaisesRegex(RuntimeError, "held inputs|support changed"):
                    assemble(job)
            self.assertFalse(Path(job.out).exists())
            self.assertTrue(any(Path(job.out).parent.glob(".source-assembly-v2-*")))
        finally:
            support.write_bytes(original)

    def test_07_legacy_and_malformed_import_are_not_ignored(self) -> None:
        job = self.job("malformed")
        with self.assertRaisesRegex(RuntimeError, "legacy"):
            assemble(replace(job, audio_clock_policy="legacy-v1"))
        for value in (("relative.json", "0" * 64), (str(self.plan_path),), [str(self.plan_path), "0" * 64]):
            with self.subTest(value=value), self.assertRaises((RuntimeError, OSError)):
                load_held_program_preparation(replace(job, held_program_selection=value))

    def test_08_exact_graphic_clock_preserves_same_final_master_and_original_inventory(self) -> None:
        """Actual empty-graphics delivery smoke; graphical endpoints have separate decoded tests."""
        job = self.job("exact-frame-clock")
        bus = self.selection.master.source_bus
        job.graphic_frame_clock = (bus.frame_rate, bus.frames)
        opening = self.prepared.base.parent.parent
        before = {path: path.read_bytes() for path in opening.rglob("*") if path.is_file()}
        with patch("audio.assemble_source_audio.build_program_master", side_effect=AssertionError("no remaster")), \
                patch("render.render", side_effect=AssertionError("no base render")), \
                (self.root / "exact-frame-clock.log").open("w") as log, contextlib.redirect_stdout(log):
            result = assemble(job)
        self.assertTrue(result["delivery"]["qualified"])
        self.assertEqual(result["programAudio"]["programMasterReceiptHash"], self.selection.master.receipt["receiptHash"])
        self.assertEqual(aac_audio_clock(job.out, bus)["presentedSamples"], bus.samples)
        self.assertEqual(packet_signature(job.base, "v:0"), packet_signature(job.out, "v:0"))
        self.assertEqual(before, {path: path.read_bytes() for path in opening.rglob("*") if path.is_file()})


class HeldPreparationCacheTests(unittest.TestCase):
    """Unit-only graphics write boundary; never fake media/approval receipts."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="sniper-held-cache-", dir="/private/tmp")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.opening = self.root / "retained-opening"
        self.opening.mkdir(mode=0o700)
        for name in ("base.mp4", "source.wav", "master.wav", "selection.json"):
            (self.opening / name).write_bytes(b"TEST ONLY immutable " + name.encode())
        self.plan = {"target": {"mode": "longform", "scope": "trim"}, "captions": {"burn": False},
            "cutTrack": [{"sourceId": "unit-source", "start": 0, "end": 3}],
            "graphicsTrack": [{"kind": "statement-card", "anchor": "own-screen", "outStart": 0,
                "outEnd": 2, "spec": {"text": "TEST ONLY cache destination"}}]}

    def inventory(self) -> dict:
        """Detect new names/directories as well as changed original bytes."""
        return {str(path.relative_to(self.opening)): path.read_bytes() if path.is_file() else None
                for path in self.opening.rglob("*")}

    def candidate(self, label: str, cache: str | None, imported: bool = True) -> SimpleNamespace:
        """Model staging-only state; no authority reader or approved fact is stubbed."""
        directory = self.root / label
        directory.mkdir(mode=0o700)
        job = AssembleJob(str(self.opening / "base.mp4"), copy.deepcopy(self.plan),
            str(self.root / "unpublished.mp4"), cache,
            held_program_selection=(str(self.opening / "selection.json"), "0" * 64) if imported else None)
        return SimpleNamespace(job=job, directory=directory, preparation=object() if imported else None)

    def test_graphics_bearing_invocation_ignores_retained_or_default_cache(self) -> None:
        from assemble import _composite
        before = self.inventory()
        paths = (str(self.opening), str(self.opening / "new-cache"), None)
        for index, path in enumerate(paths):
            candidate = self.candidate(f"attempt-{index}", path)
            original = copy.deepcopy(candidate.job)
            staged = _staged_job(candidate)
            observed = []
            def cache_writer(job: object) -> dict:
                self.assertEqual(job.track, original.plan["graphicsTrack"])
                observed.append(Path(job.cache_dir))
                (Path(job.cache_dir) / "TEST-entry.bin").write_bytes(b"TEST ONLY rendered-cache write")
                raise RuntimeError("TEST stop after cache write, before media")
            with self.subTest(cache=path), patch("graphics.graphics_stage.run_graphics_stage", side_effect=cache_writer), \
                    self.assertRaisesRegex(RuntimeError, "TEST stop after cache write"):
                _composite(staged)
            self.assertEqual(observed, [candidate.directory / "graphics-cache"])
            self.assertEqual(candidate.job, original)
            self.assertEqual(before, self.inventory())
            self.assertEqual((candidate.directory / "graphics-cache").stat().st_mode & 0o777, 0o700)

    def test_preexisting_cache_symlink_fails_before_graphics(self) -> None:
        candidate = self.candidate("linked-cache", str(self.opening))
        (candidate.directory / "graphics-cache").symlink_to(self.opening, target_is_directory=True)
        before = self.inventory()
        with patch("graphics.graphics_stage.run_graphics_stage") as graphics:
            with self.assertRaises(FileExistsError):
                _staged_job(candidate)
        graphics.assert_not_called()
        self.assertEqual(before, self.inventory())

    def test_ordinary_assembly_preserves_its_existing_cache_contract(self) -> None:
        candidate = self.candidate("ordinary", str(self.root / "ordinary-cache"), imported=False)
        staged = _staged_job(candidate)
        self.assertEqual(staged.cache_dir, candidate.job.cache_dir)
        self.assertFalse((candidate.directory / "graphics-cache").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
