"""Synthetic decoded-source cache proofs; not creator listening or delivery approval."""
from __future__ import annotations

import contextlib
import array
import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import render as renderer
from audio.render_audio_authority import SOURCE_FLOAT_POLICY_V2, admit_audio
from audio.render_audio_cache import SOURCE_BUS_POINTER, load_source_bus, write_source_bus_pointer
from audio.render_audio_bus import verify_source_bus
from cut_preview_io import digest, file_hash
from cut_manifestation_authority import MANIFESTATION_NAME
from _cut_preview_fixture import ffmpeg
from _ingest_admission_fixture import runner as admission_fixture
from ingest_admission import admit_ingest_candidates, collect_ingest_candidates
from test_render_source_audio_media import _context, _fixture


def with_synthetic_music(root: Path, manifest: dict, music_filter: str | None = None) -> dict:
    """Add generated music with test-only admission; actual media decoders still run."""
    directory = root / "music"
    directory.mkdir()
    original = directory / "bed.wav"
    source = music_filter or "sine=frequency=180:sample_rate=48000:duration=3"
    ffmpeg(["-f", "lavfi", "-i", source,
            "-c:a", "pcm_f32le", str(original)])
    paths = [Path(row["originalPath"]) for row in manifest["sources"]]
    admitted = admit_ingest_candidates(collect_ingest_candidates(paths, None, directory), root / "source", admission_fixture)
    for row in manifest["sources"]:
        item = admitted.media_by_original[row["originalPath"]]
        row.update(path=item.snapshot_path, sourceSha256=item.sha256,
                   admissionReceiptPath=item.receipt_path, admissionReceiptSha256=item.receipt_sha256)
    item = admitted.media_by_original[str(original)]
    manifest["music"] = [{"id": "test-only-bed", "duration": 3,
        "path": item.snapshot_path, "originalPath": item.original_path, "sourceSha256": item.sha256,
        "admissionReceiptPath": item.receipt_path, "admissionReceiptSha256": item.receipt_sha256}]
    manifest["sourceSetAdmission"] = admitted.binding
    Path(manifest["_path"]).write_text(json.dumps({key: value for key, value in manifest.items() if key != "_path"}))
    return manifest


class SourceBusCacheMediaTests(unittest.TestCase):
    """Actual FFmpeg source cut/PCM and cache reads, before final assembly qualification."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(tempfile.mkdtemp(prefix="sniper-source-cache-", dir="/private/tmp"))
        cls.plan, cls.manifest = _fixture(cls.root)
        cls.manifest = with_synthetic_music(cls.root, cls.manifest)
        cls.ctx = _context(cls.root, cls.plan, cls.manifest, SOURCE_FLOAT_POLICY_V2)
        cls.ctx.audio_admission = admit_audio(cls.plan, cls.manifest, (SOURCE_FLOAT_POLICY_V2, False))
        with (cls.root / "cut-cache-fixture.log").open("w") as log, contextlib.redirect_stdout(log):
            renderer.compile_stage(cls.ctx)
            cls.base = renderer.cut_stage(cls.ctx)
        cls.bus = cls.ctx.source_audio_bus
        cls.pointer = write_source_bus_pointer(cls.base, cls.ctx.out_dir, cls.bus)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.root)

    def test_exact_bus_reopens_with_actual_ordered_pcm_and_channel_proofs(self) -> None:
        bus = load_source_bus(self.plan, self.manifest, (self.ctx.out_dir, self.base), self.bus.receipt["receiptHash"])
        self.assertEqual(bus.sha256, self.bus.sha256)
        self.assertEqual(bus.samples, 192192)
        self.assertEqual(bus.receipt["schemaVersion"], 2)
        self.assertFalse(bus.receipt["masteringApplied"])

    def test_missing_held_execution_never_uses_pointer_as_its_own_authority(self) -> None:
        """A structurally valid current bus still requires a separately held selection."""
        with self.assertRaisesRegex(RuntimeError, 'separately held'):
            load_source_bus(self.plan, self.manifest, (self.ctx.out_dir, self.base))
        with self.assertRaisesRegex(RuntimeError, 'held'):
            load_source_bus(self.plan, self.manifest, (self.ctx.out_dir, self.base), '0' * 64)

    def test_resealed_changed_pcm_cannot_replace_held_source_execution(self) -> None:
        """Mutually consistent private bytes do not prove source-derived content."""
        receipt_path = Path(self.bus.directory) / 'bus-receipt.json'
        pointer_path = Path(self.ctx.out_dir) / SOURCE_BUS_POINTER
        paths = [Path(row['path']) for row in self.bus.receipt['parts']]
        paths += [Path(self.bus.path), receipt_path, pointer_path]
        before = {path: path.read_bytes() for path in paths}
        receipt = copy.deepcopy(self.bus.receipt)
        try:
            joined = b''
            for row in receipt['parts']:
                samples = array.array('f', before[Path(row['path'])])
                changed = array.array('f', (value * 0.5 for value in samples)).tobytes()
                Path(row['path']).write_bytes(changed)
                row['sha256'] = file_hash(Path(row['path']))
                joined += changed
            raw = self.root / 'TEST-ONLY-forged.f32'
            raw.write_bytes(joined)
            ffmpeg(['-f', 'f32le', '-ar', '48000', '-ac', '2', '-i', str(raw),
                    '-c:a', 'pcm_f32le', self.bus.path])
            receipt['sha256'] = file_hash(Path(self.bus.path))
            receipt['receiptHash'] = digest({key: value for key, value in receipt.items() if key != 'receiptHash'})
            receipt_path.write_text(json.dumps(receipt))
            pointer = copy.deepcopy(self.pointer)
            pointer.update(receiptHash=receipt['receiptHash'], receiptFileSha256=file_hash(receipt_path),
                           busSha256=receipt['sha256'])
            pointer_path.write_text(json.dumps(pointer))
            with self.assertRaisesRegex(RuntimeError, 'held|execution|authority'):
                load_source_bus(self.plan, self.manifest, (self.ctx.out_dir, self.base), self.bus.receipt["receiptHash"])
        finally:
            for path, raw in before.items():
                path.write_bytes(raw)

    def test_graphic_music_selection_changes_do_not_reinterpret_origin_plan_hash(self) -> None:
        changed = copy.deepcopy(self.plan)
        changed["music"] = {"enabled": True, "assetId": "test-only-bed", "gapDb": 12}
        changed["graphicsTrack"] = [{"kind": "statement-card", "outStart": 0, "outEnd": 1}]
        bus = load_source_bus(changed, self.manifest, (self.ctx.out_dir, self.base), self.bus.receipt["receiptHash"])
        self.assertEqual(bus.receipt["planHash"], self.bus.receipt["planHash"])
        self.assertNotEqual(bus.admission.plan_hash, self.bus.admission.plan_hash)
        self.assertEqual(bus.receipt["audioInputHash"], bus.admission.audio_input_hash)

    def test_changed_cut_and_unqualified_audio_effects_reject(self) -> None:
        changed = copy.deepcopy(self.plan)
        changed["cutTrack"][0]["end"] = 0.9
        with self.assertRaisesRegex(RuntimeError, "consumed inputs"):
            load_source_bus(changed, self.manifest, (self.ctx.out_dir, self.base), self.bus.receipt["receiptHash"])
        for key, value in (("audioGain", [{"start": 0, "end": 1, "gainDb": 1}]),
                           ("audioEnhance", {"preset": "light"})):
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, "rejects|has not qualified"):
                load_source_bus({**self.plan, key: value}, self.manifest, (self.ctx.out_dir, self.base), self.bus.receipt["receiptHash"])

    def test_moved_immutable_generation_paths_do_not_silently_rebind(self) -> None:
        root, inner = Path(self.ctx.out_dir), Path(self.ctx.out_dir) / "base_work"
        inner.mkdir()
        old = Path(self.bus.directory)
        moved = inner / old.name
        old.rename(moved)
        receipt_path = moved / "bus-receipt.json"
        original_receipt = receipt_path.read_bytes()
        pointer_path = root / SOURCE_BUS_POINTER
        original_pointer = pointer_path.read_bytes()
        try:
            # An unchanged already-sealed generation is selected from its original
            # path in production; moving immutable artifact paths is not allowed.
            with self.assertRaises((RuntimeError, FileNotFoundError)):
                load_source_bus(self.plan, self.manifest, (str(root), self.base), self.bus.receipt["receiptHash"])
        finally:
            receipt_path.write_bytes(original_receipt)
            moved.rename(old)
            pointer_path.write_bytes(original_pointer)
            inner.rmdir()

    def test_bus_follows_explicit_manifestation_root_after_base_sidecar_handoff(self) -> None:
        source = Path(self.ctx.out_dir)
        names = (MANIFESTATION_NAME, "timeline_map.json", SOURCE_BUS_POINTER)
        try:
            for name in names:
                shutil.copyfile(source / name, self.root / name)
            bus = load_source_bus(self.plan, self.manifest, (str(self.root), self.base), self.bus.receipt["receiptHash"])
            self.assertEqual(bus.manifestation_root, str(self.root))
            self.assertEqual(bus.directory, self.bus.directory)
            self.assertEqual(bus.sha256, self.bus.sha256)
        finally:
            for name in names:
                (self.root / name).unlink(missing_ok=True)

    def test_missing_or_old_pointer_rejects_instead_of_using_base_aac(self) -> None:
        pointer = Path(self.ctx.out_dir) / SOURCE_BUS_POINTER
        original = pointer.read_bytes()
        try:
            pointer.unlink()
            with self.assertRaises(FileNotFoundError):
                load_source_bus(self.plan, self.manifest, (self.ctx.out_dir, self.base), self.bus.receipt["receiptHash"])
            pointer.write_text(json.dumps({"schemaVersion": 1}))
            with self.assertRaisesRegex(RuntimeError, "predates v2"):
                load_source_bus(self.plan, self.manifest, (self.ctx.out_dir, self.base), self.bus.receipt["receiptHash"])
        finally:
            pointer.write_bytes(original)

    def test_current_source_proof_stays_sensitive_to_silent_source_bytes(self) -> None:
        source = Path(next(row["path"] for row in self.manifest["sources"] if row["id"] == "silent"))
        original = source.read_bytes()
        try:
            source.write_bytes(original + b"TEST ONLY source byte drift")
            with self.assertRaises((RuntimeError, ValueError)):
                load_source_bus(self.plan, self.manifest, (self.ctx.out_dir, self.base), self.bus.receipt["receiptHash"])
        finally:
            source.write_bytes(original)
        verify_source_bus(self.bus, self.plan)


if __name__ == "__main__":
    unittest.main(verbosity=2)
