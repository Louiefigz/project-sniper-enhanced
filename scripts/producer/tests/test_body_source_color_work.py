"""Actual source/consumption metadata replay, TEST admission/pipeline/native leaves.

These tests do not qualify whole-program audio, original native observation,
user consent or a complete body output. No native process executes.
"""
from __future__ import annotations

from copy import copy, deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from _body_source_color_work_fixture import BodySourceColorWorkFixture
from cut_preview_io import digest
from guided_body_execution import body_clock
from guided_body_work import (BodyWork, body_source_color_readback, prepare_body_work,
    read_body_inputs, read_body_preparation, replay_body_source_color)
from guided_source_color_read_scope import SourceColorReadScope
from guided_opening_inputs import _json


class BodySourceColorWorkTests(unittest.TestCase):
    """Both actual raw replay groups share one already-bound original body clock."""

    def setUp(self) -> None:
        """Create original TEST controls before the first actual body input seed."""
        self.mono = [1000.0]
        self.wall = [int(datetime(2026, 9, 8, tzinfo=timezone.utc).timestamp() * 1000) + 63_000]
        for timer in (patch("time.monotonic", side_effect=lambda: self.mono[0]),
                      patch("time.time_ns", side_effect=lambda: self.wall[0] * 1_000_000)):
            timer.start()
            self.addCleanup(timer.stop)
        self.f = BodySourceColorWorkFixture()
        self.addCleanup(self.f.cleanup)
        self.leaves = self.f.leaves()
        self.addCleanup(self.leaves.close)

    def test_real_replays_share_original_clock_and_project_actual_records(self) -> None:
        """The genuine private groups complete once; no generated body/master is claimed."""
        work = self.f.work()
        self.assertIs(work.inputs, self.f.original_inputs)
        self.assertIs(work.clock, self.f.clock)
        original_end, original_wall = work.clock.end, work.clock.wall_deadline_ms
        replay_body_source_color(work)
        result = body_source_color_readback(work)
        self.assertEqual(result["observationRecordHash"], digest(self.f.section))
        self.assertEqual(result["consumptionRecordHash"], digest(self.f.picture.consumed))
        self.assertEqual(result["sourceColorEvidence"], self.f.record["sourceColorEvidence"])
        self.assertEqual([row["stage"] for row in work.clock.events],
            ["body-original-source-color-observations", "body-original-base-picture-consumption"])
        self.assertEqual((work.clock.end, work.clock.wall_deadline_ms), (original_end, original_wall))
        self.assertTrue(result["sourceColorRecordsReplayed"])
        self.assertFalse(result["colorQualified"])
        self.assertFalse(result["bodyApproved"])
        calls = len(self.f.picture.native_calls)
        self.assertGreater(calls, 0)
        for _ in range(3):
            BodyWork.guard(work)
        self.assertEqual(len(self.f.picture.native_calls), calls)

    def test_no_legacy_runtime_claim_reader_can_run_for_source2(self) -> None:
        """The old claim's runtime/socket is data, not current ownership to restore."""
        with patch("guided_body_work.read_execution_claim", side_effect=AssertionError("TEST old runtime")):
            work = self.f.work()
            replay_body_source_color(work)

    def test_seed_is_same_control_input_and_clock_and_is_single_use(self) -> None:
        """Copies and omissions do not inherit actual original-entry registration."""
        read = read_body_inputs(self.f.control, self.f.clock)
        for seed in (None, copy(read.source_color_entry)):
            self.assertRaises(RuntimeError, prepare_body_work, self.f.control, read.inputs, self.f.clock, seed)
        other = body_clock(300)
        other.bind_wall(self.f.clock.wall_deadline_ms, self.wall[0])
        self.assertRaises(RuntimeError, prepare_body_work, self.f.control, read.inputs, other, read.source_color_entry)
        self.assertRaises(RuntimeError, prepare_body_work, copy(self.f.control), read.inputs, self.f.clock, read.source_color_entry)
        self.assertRaises(RuntimeError, prepare_body_work, self.f.control, copy(read.inputs), self.f.clock, read.source_color_entry)
        prepare_body_work(self.f.control, read.inputs, self.f.clock, read.source_color_entry)
        self.assertRaises(RuntimeError, prepare_body_work, self.f.control, read.inputs, self.f.clock, read.source_color_entry)

    def test_missing_replays_cannot_reuse_whole_master_or_project_completion(self) -> None:
        """Registration alone does not satisfy either actual replay group."""
        work = self.f.work()
        with patch("guided_body_work._full_program", side_effect=AssertionError("TEST no master read")):
            self.assertRaisesRegex(RuntimeError, "incomplete", read_body_preparation, work)
        self.assertRaisesRegex(RuntimeError, "incomplete", body_source_color_readback, work)

    def test_replay_is_not_repeated_or_retried_after_partial_failure(self) -> None:
        """A failed phase stays incomplete and cannot acquire a fresh allowance."""
        work = self.f.work()
        with patch.object(SourceColorReadScope, "replay_consumption", side_effect=RuntimeError("TEST packet failure")):
            self.assertRaisesRegex(RuntimeError, "packet failure", replay_body_source_color, work)
        self.assertEqual(work.clock.events[-1]["status"], "failed")
        self.assertRaisesRegex(RuntimeError, "twice|retry", replay_body_source_color, work)
        self.assertRaisesRegex(RuntimeError, "incomplete", body_source_color_readback, work)

    def test_copied_work_and_mutated_discriminator_do_not_drop_obligations(self) -> None:
        """Original private work identity wins before a caller-mutated schema tag."""
        work = self.f.work()
        self.assertRaises(RuntimeError, BodyWork.guard, copy(work))
        work.control.value["schemaVersion"] = 1
        self.assertRaisesRegex(RuntimeError, "original", BodyWork.guard, work)

    def test_bound_body_wall_expiry_blocks_replay_despite_monotonic_time_left(self) -> None:
        """No historical grade-phase expiry or fresh clock substitutes for current body time."""
        work = self.f.work()
        self.wall[0] = work.clock.wall_deadline_ms
        self.assertGreater(work.clock.end, self.mono[0])
        self.assertRaises(RuntimeError, replay_body_source_color, work)
        self.assertEqual(self.f.picture.native_calls, [])

    def test_new_work_cannot_reconstruct_a_downgraded_source_control(self) -> None:
        """Actual construction also joins raw input, not only the private copied-work fence."""
        original = self.f.work()
        forged = replace(original.control, value=deepcopy(original.control.value),
                         documents=deepcopy(original.control.documents))
        forged.value["schemaVersion"] = 1
        forged.value.pop("sourceColorReplay")
        forged.documents["openingResult"]["schemaVersion"] = 1
        forged.documents["openingResult"].pop("sourceColorEvidence")
        self.assertRaisesRegex(RuntimeError, "original raw input", BodyWork,
            forged, original.inputs, original.clock, original.pipeline, original.files)
        self.assertEqual(self.f.picture.native_calls, [])

    def test_constructor_retains_control_before_its_original_json_read(self) -> None:
        """A real bounded reader return cannot silently replace the pre-read control."""
        original = self.f.work()

        def changed(*args: object) -> tuple:
            """Only in-memory TEST metadata changes, after the actual original raw read."""
            result = _json(*args)
            original.control.value["schemaVersion"] = 1
            return result

        with patch("guided_body_source_color_entry._json", side_effect=changed):
            self.assertRaisesRegex(RuntimeError, "original", BodyWork,
                original.control, original.inputs, original.clock, original.pipeline, original.files)

    def test_repeated_guards_never_reparse_original_control_json(self) -> None:
        """Original raw construction proof is retained, not reopened on each guard."""
        work = self.f.work()
        with patch("guided_body_source_color_entry._json", side_effect=AssertionError("TEST no JSON replay")):
            for _ in range(3):
                BodyWork.guard(work)
        self.assertEqual(self.f.picture.native_calls, [])

    def test_constructor_raw_read_cannot_rebaseline_actual_pipeline_return(self) -> None:
        """Current pipeline metadata is captured before the added bounded raw-control read."""
        original = self.f.work()

        def changed(*args: object) -> tuple:
            """Mutate only the inert actual pipeline DTO after original JSON read returns."""
            result = _json(*args)
            original.pipeline["TEST"] = "changed before construction finished"
            return result

        with patch("guided_body_source_color_entry._json", side_effect=changed):
            self.assertRaisesRegex(RuntimeError, "original", BodyWork,
                original.control, original.inputs, original.clock, original.pipeline, original.files)
