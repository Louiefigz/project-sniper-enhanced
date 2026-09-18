"""Real synthetic ordinary base→whole master→PCM→AAC submodule evidence.

These fixtures enter below the TS/authenticated14-document gate. They do not
claim server acceptance, a live lease, catalog graphics, listening or approval.
"""
from __future__ import annotations

import contextlib
import copy
import tempfile
import unittest
from pathlib import Path

from audio.program_master_excerpt import ExcerptRanges, extract_master_audio
from cut_preview_io import file_hash, write_new
from guided_opening_inputs import OpeningInputs
from guided_opening_mux import mux_ranges
from guided_opening_picture import compose_ranges, observe_picture
from guided_opening_prepare import prepare_full_program
from guided_opening_read import _full_program
from guided_opening_result import read_ranges
from test_render_audio_cache_media import with_synthetic_music
from test_render_source_audio_media import _fixture


class OpeningPreparationMediaTests(unittest.TestCase):
    """Exercise actual shared production stages without fake media receipts."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(tempfile.mkdtemp(prefix="sniper-opening-preparation-", dir="/private/tmp"))
        print(f"Synthetic ordinary opening preparation evidence: {cls.root}", flush=True)
        plan, manifest = _fixture(cls.root)
        manifest = with_synthetic_music(cls.root, manifest)
        for cut in plan["cutTrack"]:
            cut.pop("audioLeadMs", None)
        plan["target"].update(width=160, height=90, fps=30)
        plan["music"] = {"enabled": True, "assetId": "test-only-bed", "gapDb": 12}
        plan_path = cls.root / "candidate.json"
        write_new(plan_path, plan)
        authority = {"frameRate": "30000/1001", "totalFrames": 120, "target": plan["target"],
            "core": {"startFrame": 0, "endFrameExclusive": 10},
            "review": {"startFrame": 0, "endFrameExclusive": 110}}
        cls.inputs = OpeningInputs(plan_path, file_hash(plan_path), {"executionInputHash": "c" * 64, "documents": {
            "candidatePlan": {"path": str(plan_path), "sha256": file_hash(plan_path)},
            "manifest": {"path": manifest["_path"], "sha256": file_hash(Path(manifest["_path"]))}}},
            {"candidatePlan": plan, "manifest": {key: value for key, value in manifest.items() if key != "_path"},
             "authority": authority})
        cls.output = cls.root / "execution"
        cls.output.mkdir(mode=0o700)
        with (cls.root / "ordinary.log").open("w") as log, contextlib.redirect_stdout(log):
            cls.prepared = prepare_full_program(cls.inputs, cls.output)
        cls.tools = cls.prepared.selection.master.source_bus.admission.tools
        cls.audio_dir = cls.output / "audio"
        cls.audio_dir.mkdir(mode=0o700)
        cls.audio = extract_master_audio(cls.prepared.selection, ExcerptRanges((0, 10), (0, 110), "c" * 64),
                                         cls.audio_dir, lambda: None)
        cls.graphics = []
        cls.pictures = compose_ranges(cls.prepared.base, cls.graphics, (cls.output, authority, cls.tools))
        cls.media = mux_ranges(cls.output, cls.pictures, cls.audio, cls.tools)

    def test_actual_ordinary_base_retains_source_clock_and_whole_master(self) -> None:
        prepared = self.prepared
        self.assertEqual(prepared.evidence["base"]["frames"], 120)
        self.assertEqual(prepared.selection.master.receipt["totalSamples"], 192192)
        self.assertTrue(prepared.selection.master.receipt["wholeProgramMeasurement"]["qualified"])
        self.assertTrue(prepared.evidence["baseAudibleTrackNotSelected"])
        self.assertFalse(prepared.evidence["bodyGraphicsPrepared"])
        self.assertEqual(self.inputs.documents["candidatePlan"]["target"]["fps"], 30)

    def test_actual_core_context_aac_preserve_exact_samples_and_picture_packets(self) -> None:
        for name, frames in (("core", 10), ("review", 110)):
            row = self.media[name]
            with self.subTest(range=name):
                self.assertEqual(row["audioClock"]["presentedSamples"], frames * 16016 // 10)
                self.assertTrue(row["picture"]["picturePacketsIdentical"])
                self.assertEqual(row["sourcePcmSha256"], self.audio[name]["sourceRangePcmSha256"])
                self.assertFalse(row["audioMeasurement"]["independentNormalization"])
                self.assertTrue(row["audioMeasurement"]["excerptLufsIsInformational"])
                self.assertEqual(row["audiblePathAacEncodes"], 1)
                observe_picture(Path(row["path"]), ("30000/1001", frames, (160, 90)), self.tools)

    def test_actual_readback_reobserves_exact_picture_and_full_audio_decode(self) -> None:
        record = {"pictures": self.pictures, "media": self.media}
        read_ranges(record, self.audio, (self.output, self.inputs.documents["authority"], self.tools))

    def test_actual_returned_whole_master_selection_reopens_from_held_event(self) -> None:
        audio_path = self.audio_dir / "audio-result.json"
        # Use this fixture's actual picture result; caption readback must not receive an invented empty proof.
        record = {"fullProgram": self.prepared.evidence, "pictures": self.pictures, "graphics": self.graphics,
            "audio": {"path": str(audio_path),
            "sha256": file_hash(audio_path), "receiptHash": self.audio["receiptHash"]}}
        selection, audio = _full_program(record, self.inputs, self.output)
        self.assertEqual(selection.event_sha256, self.prepared.selection.event_sha256)
        self.assertEqual(audio, self.audio)
        captioned = copy.deepcopy(record)
        captioned["pictures"]["captionLayers"] = {}
        with self.assertRaisesRegex(RuntimeError, "uncaptioned opening acquired a caption layer proof"):
            _full_program(captioned, self.inputs, self.output)

    def test_readback_rejects_changed_frame_and_sample_intent(self) -> None:
        record = {"pictures": self.pictures, "media": copy.deepcopy(self.media)}
        record["media"]["core"]["startSample"] = 1
        with self.assertRaisesRegex(RuntimeError, "PCM authority"):
            read_ranges(record, self.audio, (self.output, self.inputs.documents["authority"], self.tools))

    def test_same_ranges_reuse_exact_mux_not_another_encode(self) -> None:
        root = self.output / "same"
        root.mkdir(mode=0o700)
        pictures = {"ranges": {"core": self.pictures["ranges"]["core"], "review": self.pictures["ranges"]["core"]}}
        audio = {"core": self.audio["core"], "review": self.audio["core"]}
        rows = mux_ranges(root, pictures, audio, self.tools)
        self.assertEqual(rows["core"]["path"], rows["review"]["path"])
        self.assertEqual(len(list(root.glob("*.mp4"))), 1)

    def test_wrong_declared_canvas_never_passes_from_target_metadata_alone(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "clock/canvas"):
            observe_picture(self.prepared.base, ("30000/1001", 120, (1920, 1080)), self.tools)

    def test_unproved_pcm_or_prior_media_is_not_overwritten(self) -> None:
        root = self.output / "negative"
        root.mkdir(mode=0o700)
        prior = root / "core.mp4"
        prior.write_bytes(b"TEST approved existing bytes")
        before = prior.read_bytes()
        audio = copy.deepcopy(self.audio)
        audio["core"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(RuntimeError, "held picture/PCM"):
            mux_ranges(root, self.pictures, audio, self.tools)
        self.assertEqual(prior.read_bytes(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
