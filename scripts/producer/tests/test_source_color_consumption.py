"""Actual private recorder + picture builders; all native/packet proof leaves are TEST stubs."""
from __future__ import annotations

from dataclasses import replace
import json
import subprocess
import unittest
from unittest.mock import Mock, patch

from _source_color_batch_fixture import current_batch_test_pins
from _source_color_consumption_fixture import SourceColorConsumptionFixture
from audio import master
import cut_speed as cut
from guided_source_color_consumption import SourceColorPictureConsumption
import guided_source_color_consumption as consumption
from guided_source_color_consumption_records import copy_proof, cut_request, metadata_size
from cross_runtime_canonical_json import canonical_compact_json


class SourceColorConsumptionTests(unittest.TestCase):
    """Reuse one immutable actual TEST holder; every recorder has private fresh progress."""

    @classmethod
    def setUpClass(cls) -> None:
        """Create real owned metadata once; no source/code file is changed by a fault."""
        cls.fixture = SourceColorConsumptionFixture(current_batch_test_pins())
        cls.addClassCleanup(cls.fixture.cleanup)
        cls.holder = cls.fixture.identity()

    def setUp(self) -> None:
        """Each case gets new actual progress, never a copied or reset successful token."""
        self.recorder = self.fixture.recorder(self.holder)

    def finish(self) -> dict:
        """Require actual cut/master hooks plus both independently supplied TEST proof joins."""
        self.fixture.cuts(self.recorder)
        picture = self.fixture.master(self.recorder)
        self.recorder.observe_master_picture(picture)
        self.recorder.complete_master_copy(picture, copy_proof(picture))
        return self.recorder.record()

    def test_actual_three_occurrences_and_one_master_not_generic_guard_counts(self) -> None:
        """Repeated raw-b occurs twice; additional guard calls never create encode rows."""
        value = self.finish()
        self.assertEqual([row["segment"]["source_id"] for row in value["cuts"]], ["raw-b", "raw-a", "raw-b"])
        self.assertEqual([row["framesBefore"] for row in value["cuts"]], [0, 6, 12])
        self.assertEqual([row["frames"] for row in value["cuts"]], [6, 6, 6])
        self.assertEqual(value["master"]["frameCount"], 18)
        self.assertEqual(self.fixture.inputs.documents["authority"]["frameRate"], "24")
        self.assertEqual(value["cuts"][0]["profile"]["frameRate"], "24/1")
        self.assertFalse(value["colorQualified"])
        self.assertFalse(value["deliveryApproved"])
        self.recorder.assert_current()
        self.assertEqual(self.recorder.record(), value)

    def test_record_is_detached_and_cannot_replace_actual_capability(self) -> None:
        """Editing a returned DTO does not change original records or confer authority."""
        result = self.finish()
        result["cuts"][0]["source"]["sha256"] = "0" * 64
        self.assertNotEqual(self.recorder.record()["cuts"][0]["source"]["sha256"], "0" * 64)
        self.assertRaisesRegex(RuntimeError, "actual held", SourceColorPictureConsumption.assert_metadata, result)
        fake = object.__new__(SourceColorPictureConsumption)
        self.assertRaisesRegex(RuntimeError, "actual held", SourceColorPictureConsumption.assert_metadata, fake)

    def test_record_is_actual_json_domain_without_tuple_coercion(self) -> None:
        """The durable serializer accepts detached data without stringifying owners or tuples."""
        result = self.finish()
        self.assertEqual(json.loads(canonical_compact_json(result)), result)
        self.assertIs(type(result["cuts"]), list)
        self.assertIs(type(result["master"]["argv"]), list)

    def test_missing_cut_or_master_or_copy_observation_never_completes(self) -> None:
        """Merely constructing a source context/recorder cannot bless omitted hooks."""
        self.assertRaisesRegex(RuntimeError, "incomplete", self.recorder.record)
        self.fixture.cuts(self.recorder)
        self.assertRaisesRegex(RuntimeError, "incomplete", self.recorder.record)
        picture = self.fixture.master(self.recorder)
        self.assertRaisesRegex(RuntimeError, "incomplete", self.recorder.record)
        self.recorder.observe_master_picture(picture)
        self.assertRaisesRegex(RuntimeError, "incomplete", self.recorder.record)

    def test_reordered_or_replayed_cut_refuses_before_native(self) -> None:
        """The actual compiler occurrence index is authority, not only source identity."""
        with patch.object(cut, "run_ff") as native, patch.object(cut, "_clamp_part_audio"):
            self.assertRaisesRegex(RuntimeError, "occurrence", cut.encode_segment,
                self.fixture.segment(1), self.fixture.job(self.recorder, 1), self.fixture.part(1), 0)
        native.assert_not_called()
        self.assertRaisesRegex(RuntimeError, "failed encode", self.recorder.record)

    def test_native_failure_is_sticky_and_cannot_be_retried_as_success(self) -> None:
        """Failed subprocess state remains failed even when a later caller supplies good arguments."""
        with patch.object(cut, "run_ff", side_effect=RuntimeError("TEST native failed")), \
                patch.object(cut, "_clamp_part_audio") as clamp:
            self.assertRaisesRegex(RuntimeError, "native failed", cut.encode_segment,
                                   self.fixture.segment(0), self.fixture.job(self.recorder), self.fixture.part(0), 0)
        clamp.assert_not_called()
        self.assertRaisesRegex(RuntimeError, "failed encode", self.fixture.cut, self.recorder)

    def test_original_job_mutation_after_native_cannot_reach_audio_clamp(self) -> None:
        """Only the in-memory frozen TEST job is mutated, never source or dependency bytes."""
        job = self.fixture.job(self.recorder)
        with patch.object(cut, "run_ff", side_effect=lambda _cmd: object.__setattr__(job, "src_path", "/TEST-unopened/other")), \
                patch.object(cut, "_clamp_part_audio") as clamp:
            self.assertRaisesRegex(RuntimeError, "original command", cut.encode_segment,
                                   self.fixture.segment(0), job, self.fixture.part(0), 0)
        clamp.assert_not_called()
        self.assertRaisesRegex(RuntimeError, "failed encode", self.recorder.record)

    def test_changed_argv_post_native_is_not_a_successful_record(self) -> None:
        """Retain actual argv before callbacks instead of reporting its substituted contents."""
        with patch.object(cut, "run_ff", side_effect=lambda cmd: cmd.append("TEST-altered")), \
                patch.object(cut, "_clamp_part_audio") as clamp:
            self.assertRaisesRegex(RuntimeError, "argv changed", cut.encode_segment,
                                   self.fixture.segment(0), self.fixture.job(self.recorder), self.fixture.part(0), 0)
        clamp.assert_not_called()

    def test_final_completion_callback_cannot_change_native_argv(self) -> None:
        """The last recorder guard cannot alter retained argv after the earlier post-run check."""
        argv, calls = [], []

        def changed() -> None:
            """Mutate only the TEST command on its second post-native original guard."""
            if argv:
                calls.append(True)
            if len(calls) == 2:
                argv[0].append("TEST-final-callback")

        self.fixture.guard.side_effect = changed
        try:
            with patch.object(cut, "run_ff", side_effect=lambda cmd: argv.append(cmd)), \
                    patch.object(cut, "_clamp_part_audio") as clamp:
                self.assertRaisesRegex(RuntimeError, "completion callback", cut.encode_segment,
                    self.fixture.segment(0), self.fixture.job(self.recorder), self.fixture.part(0), 0)
            clamp.assert_not_called()
        finally:
            self.fixture.guard.side_effect = None

    def test_post_clamp_failure_and_noninteger_frame_count_refuse(self) -> None:
        """Lossless remux is not a second encode record and must still complete successfully."""
        with patch.object(cut, "run_ff"), patch.object(cut, "_clamp_part_audio", return_value=True):
            self.assertRaisesRegex(RuntimeError, "part completion", cut.encode_segment,
                                   self.fixture.segment(0), self.fixture.job(self.recorder), self.fixture.part(0), 0)
        self.assertRaisesRegex(RuntimeError, "failed encode", self.recorder.record)

    def test_manifestation_paths_frames_and_replay_are_closed(self) -> None:
        """The post-clamp receipt joins exact occurrences, not a pre-remux raw byte hash."""
        for index in range(3):
            self.fixture.cut(self.recorder, index)
        receipt = self.fixture.manifestation()
        wrong = tuple(self.fixture.part(index) for index in (1, 0, 2))
        concat = str(self.fixture.root / "mezzanine.mp4")
        self.assertRaisesRegex(RuntimeError, "path/frame", self.recorder.join_cut_manifestation, receipt, wrong, concat)
        paths = tuple(self.fixture.part(index) for index in range(3))
        self.recorder.join_cut_manifestation(receipt, paths, concat)
        self.assertRaisesRegex(RuntimeError, "replayed", self.recorder.join_cut_manifestation, receipt, paths, concat)

    def test_master_before_manifestation_refuses_before_native(self) -> None:
        """A single master success cannot replace the full ordered cut consumption."""
        with patch.object(master, "_run") as native:
            self.assertRaisesRegex(RuntimeError, "omitted joined cuts", master.encode_picture_only,
                                   self.fixture.spec(self.recorder), self.fixture.guard)
        native.assert_not_called()

    def test_same_length_unrelated_master_input_refuses_before_native(self) -> None:
        """Frame count alone cannot substitute a different file for the actual cut concat."""
        self.fixture.cuts(self.recorder)
        spec = replace(self.fixture.spec(self.recorder), src=str(self.fixture.root / "TEST-unrelated.mp4"))
        with patch.object(master, "_run") as native:
            self.assertRaisesRegex(RuntimeError, "picture inputs", master.encode_picture_only, spec, self.fixture.guard)
        native.assert_not_called()

    def test_reentrant_begin_during_original_callback_cannot_change_sequence(self) -> None:
        """The caller callback cannot create a second pending token inside original admission."""
        job, rejections = replace(self.fixture.job(self.recorder), before_encode=Mock()), []
        request = cut_request((self.fixture.segment(0), job, self.fixture.part(0), 0))

        def reenter() -> None:
            """Only exercise a code callback; every reentrant attempt must hit the private latch."""
            with self.assertRaisesRegex(RuntimeError, "transition"):
                self.recorder.begin("cut", request, ("ffmpeg", job.src_path, self.fixture.part(0)))
            rejections.append(True)

        self.fixture.guard.side_effect = reenter
        try:
            with patch.object(cut, "run_ff") as native, patch.object(cut, "_clamp_part_audio", return_value=6):
                cut.encode_segment(self.fixture.segment(0), job, self.fixture.part(0), 0)
            native.assert_called_once()
            self.assertTrue(rejections)
        finally:
            self.fixture.guard.side_effect = None

    def test_final_detached_copy_cannot_return_after_original_deadline(self) -> None:
        """Advance only the inherited TEST clock during copying, never create a new deadline."""
        self.finish()
        original, now = consumption.deepcopy, self.fixture.now

        def expired(value: object) -> object:
            """The final copy finishes just as the original virtual test allowance expires."""
            result = original(value)
            if type(value) is dict and "scope" in value:
                self.fixture.now = self.fixture.clock.end
            return result

        try:
            with patch.object(consumption, "deepcopy", side_effect=expired):
                self.assertRaisesRegex(RuntimeError, "deadline|time budget", self.recorder.record)
        finally:
            self.fixture.now = now

    def test_metadata_budget_refuses_before_any_native_or_retained_growth(self) -> None:
        """An oversized command is not allowed to accumulate until final JSON publication."""
        with patch.object(consumption, "MAX_CONSUMPTION_BYTES", 1), patch.object(cut, "run_ff") as native:
            self.assertRaisesRegex(RuntimeError, "aggregate bound", cut.encode_segment,
                                   self.fixture.segment(0), self.fixture.job(self.recorder), self.fixture.part(0), 0)
        native.assert_not_called()

    def test_exact_utf8_metadata_budget_boundary(self) -> None:
        """This bound is encoded metadata size, not a claim about Python heap usage."""
        value = {"TEST": ["é", "video", 12]}
        size = len(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8"))
        self.assertEqual(metadata_size(value, size), size)
        self.assertRaisesRegex(RuntimeError, "aggregate bound", metadata_size, value, size - 1)

    def test_options_recorder_substitution_refuses_before_source_probes(self) -> None:
        """Capture options before their first callback rather than adopt a new code capability."""
        replacement = self.fixture.recorder(self.holder)
        options = cut.CutSpeedOptions(str(self.fixture.root), picture_consumption=self.recorder)
        object.__setattr__(options, "before_encode", lambda: object.__setattr__(options, "picture_consumption", replacement))
        with patch.object(cut, "_cut_source_setup") as setup:
            self.assertRaisesRegex(RuntimeError, "cut options changed", cut.render_cut_speed_opts,
                self.fixture.inputs.documents["candidatePlan"], self.fixture.inputs.documents["manifest"],
                str(self.fixture.root / "mezzanine.mp4"), options)
        setup.assert_not_called()

    def test_master_nonzero_return_does_not_record_success(self) -> None:
        """The master runner returns a status unlike cut's raising runner; nonzero stays failed."""
        self.fixture.cuts(self.recorder)
        with patch.object(master, "_run", return_value=subprocess.CompletedProcess([], 1, "", "TEST failed")):
            self.assertRaisesRegex(RuntimeError, "native encode failed", master.encode_picture_only,
                                   self.fixture.spec(self.recorder), self.fixture.guard)
        self.assertRaisesRegex(RuntimeError, "failed encode", self.recorder.record)

    def test_master_spec_mutation_during_command_construction_refuses(self) -> None:
        """Hold the mutable spec before _video_opts rather than adopting changed metadata."""
        self.fixture.cuts(self.recorder)
        spec = self.fixture.spec(self.recorder)
        original = master._video_opts

        def changed(fps: int, exact: str | None) -> list[str]:
            """Change only a TEST argument object while retaining actual option generation."""
            spec.frame_count = 19
            return original(fps, exact)

        with patch.object(master, "_video_opts", side_effect=changed), patch.object(master, "_run") as native:
            self.assertRaisesRegex(RuntimeError, "original command", master.encode_picture_only, spec, self.fixture.guard)
        native.assert_not_called()

    def test_picture_and_copy_proof_require_actual_original_observation(self) -> None:
        """Typed packet observations still require exact path/frames and unchanged original identity."""
        self.fixture.cuts(self.recorder)
        picture = self.fixture.master(self.recorder)
        self.assertRaisesRegex(RuntimeError, "observation", self.recorder.observe_master_picture, {})
        self.recorder.observe_master_picture(picture)
        changed = {**copy_proof(picture), "picturePacketsIdentical": 1}
        self.assertRaisesRegex(RuntimeError, "copy proof", self.recorder.complete_master_copy, picture, changed)
        self.assertRaisesRegex(RuntimeError, "copy proof", self.recorder.complete_master_copy, replace(picture), copy_proof(picture))
        self.recorder.complete_master_copy(picture, copy_proof(picture))
        self.assertRaisesRegex(RuntimeError, "replayed", self.recorder.complete_master_copy, picture, copy_proof(picture))


if __name__ == "__main__":
    unittest.main()
