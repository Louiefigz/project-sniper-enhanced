"""Adversarial original body replay lifetimes over exact inert TEST metadata.

Initial admission/pipeline and ffprobe leaves are explicit TEST substitutes.
No native child, original source payload mutation or real media approval occurs.
"""
from __future__ import annotations

from copy import copy, deepcopy
from contextlib import ExitStack
from dataclasses import replace
from datetime import datetime, timezone
import os
from pathlib import Path
import signal
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from _body_source_color_work_fixture import BodySourceColorWorkFixture
from cut_preview_io import digest, file_hash, write_new
from guided_body_execution import BodyExecutionClock
from guided_body_media import _receipt
from guided_body_read import BodyReadAuthority, read_body_record, read_result
from guided_body_source_color_result import body_source_result_fields, recheck_body_source_result
from guided_body_work import (BodyWork, body_source_color_readback, read_body_inputs,
                             read_body_preparation, replay_body_source_color)
from guided_source_color_read_scope import SourceColorReadScope


class BodySourceColorWorkFaultTests(unittest.TestCase):
    """Only original registered work and completed sibling replay may make evidence."""

    def setUp(self) -> None:
        """Use one explicitly TEST monotonic/wall epoch and actual local metadata."""
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

    def test_copied_work_cannot_erase_all_source_discriminators(self) -> None:
        """A copied original body cannot claim legacy permission by deleting metadata."""
        original = self.f.work()
        forged = copy(original)
        forged.control = replace(original.control, value=deepcopy(original.control.value),
                                 documents=deepcopy(original.control.documents))
        forged.control.value["schemaVersion"] = 1
        forged.control.value.pop("sourceColorReplay")
        forged.control.documents["openingResult"]["schemaVersion"] = 1
        forged.control.documents["openingResult"].pop("sourceColorEvidence")
        self.assertRaises(RuntimeError, BodyWork.guard, forged)
        self.assertRaises(RuntimeError, body_source_result_fields, forged)
        self.assertEqual(self.f.picture.native_calls, [])

    def test_changed_original_source_reference_is_rejected_before_source_reader(self) -> None:
        """Control data cannot select a different input before later work construction."""
        self._source_reference_fault(False)

    def test_erased_source_tags_cannot_skip_original_pre_source_validation(self) -> None:
        """Legacy dispatch cannot hide changed original control bytes from the entry join."""
        self._source_reference_fault(True)

    def _source_reference_fault(self, downgrade: bool) -> None:
        """Change only caller metadata; the source reader must receive no foreign input."""
        original = self.f.control.value["references"]["openingInput"]
        archive = self.f.references["archive"]
        original.update(path=archive["path"], sha256=archive["sha256"])
        if downgrade:
            self.f.control.value["schemaVersion"] = 1
            self.f.control.value.pop("sourceColorReplay")
            self.f.control.documents["openingResult"]["schemaVersion"] = 1
            self.f.control.documents["openingResult"].pop("sourceColorEvidence")
        with patch("guided_body_work.read_current_inputs", return_value=self.f.original_inputs) as source:
            failure = None
            try:
                read_body_inputs(self.f.control, self.f.clock)
            except RuntimeError as error:
                failure = error
        self.assertEqual(source.call_count, 0, "changed original reference reached the source reader")
        self.assertIsNotNone(failure)

    def _metadata_targets(self, fixture: BodySourceColorWorkFixture) -> tuple[Path, ...]:
        """Return six literal original controls; never choose a source or tool target."""
        return (fixture.inputs.path, Path(fixture.opening["claimPath"]), fixture.output / "media-result.json",
                Path(fixture.references["sidecar"]["path"]), Path(fixture.references["archive"]["path"]),
                fixture.output / "source-color-evidence.json")

    def _rewrite_control(self, fixture: BodySourceColorWorkFixture, target: Path) -> None:
        """Touch same bytes only in an exact canonical user-owned TEST control file."""
        self.assertIn(target, self._metadata_targets(fixture))
        self.assertTrue(target.is_relative_to(fixture.root))
        self.assertEqual(target.resolve(strict=True), target)
        info = target.lstat()
        self.assertTrue(stat.S_ISREG(info.st_mode))
        self.assertEqual((info.st_uid, info.st_nlink), (os.geteuid(), 1))
        target.write_bytes(target.read_bytes())

    def test_all_six_original_controls_are_held_before_source_admission(self) -> None:
        """Same-byte source-reader callback replacement cannot establish a new baseline."""
        for index in range(6):
            self._source_admission_fault(index)

    def _source_admission_fault(self, index: int) -> None:
        """Each independent original seed gets exactly one allowlisted callback fault."""
        fixture = BodySourceColorWorkFixture()
        self.addCleanup(fixture.cleanup)
        target = self._metadata_targets(fixture)[index]
        calls = []

        def admission(*_args: object) -> object:
            """TEST initial admission returns original capture after one metadata fault."""
            calls.append(index)
            self._rewrite_control(fixture, target)
            return fixture.original_inputs

        with fixture.leaves(), patch("guided_body_work.read_current_inputs", side_effect=admission):
            self.assertRaisesRegex(RuntimeError, "changed", read_body_inputs, fixture.control, fixture.clock)
        self.assertEqual(calls, [index])
        self.assertEqual(fixture.picture.native_calls, [])

    def test_original_body_watermark_cannot_move_back_before_a_work_guard(self) -> None:
        """Changing both current wall sample and public watermark cannot renew time."""
        work = self.f.work()
        self.wall[0] += 10
        BodyWork.guard(work)
        self.wall[0] -= 5
        work.clock.previous_wall_ms -= 5
        self.assertRaisesRegex(RuntimeError, "watermark|backwards|rolled", BodyWork.guard, work)
        self.assertEqual(self.f.picture.native_calls, [])

    def test_first_replay_failure_never_starts_consumption_or_preparation(self) -> None:
        """One failed actual observation phase cannot be retried or projected as complete."""
        work = self.f.work()
        with patch.object(SourceColorReadScope, "replay_observations", side_effect=RuntimeError("TEST raw failure")), \
                patch.object(SourceColorReadScope, "replay_consumption") as consumption:
            self.assertRaisesRegex(RuntimeError, "raw failure", replay_body_source_color, work)
        consumption.assert_not_called()
        self.assertEqual(work.clock.events[-1]["status"], "failed")
        self.assertRaisesRegex(RuntimeError, "incomplete", body_source_color_readback, work)
        with patch("guided_body_work._full_program") as preparation:
            self.assertRaisesRegex(RuntimeError, "incomplete", read_body_preparation, work)
        preparation.assert_not_called()

    def test_both_actual_replays_are_sibling_timed_phases_on_the_original_clock(self) -> None:
        """Real raw observation and packet readers run once beneath separate body timers."""
        work = self.f.work()
        actions = (SourceColorReadScope.replay_observations, SourceColorReadScope.replay_consumption)
        phases = []

        def observed(scope: SourceColorReadScope) -> None:
            """Wrap each actual reader only to inspect the already-running original phase."""
            index = len(phases)
            phases.append((len(work.clock.events), signal.getitimer(signal.ITIMER_REAL)[0]))
            self.assertIs(work.clock, self.f.clock)
            self.assertIs(type(work.clock), BodyExecutionClock)
            actions[index](scope)

        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)
        with patch.object(SourceColorReadScope, "replay_observations", observed), \
                patch.object(SourceColorReadScope, "replay_consumption", observed):
            replay_body_source_color(work)
        self.assertEqual([row[0] for row in phases], [0, 1])
        self.assertTrue(all(row[1] > 0 for row in phases))
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)
        self.assertTrue(body_source_color_readback(work)["basePictureConsumptionVerified"])

    def test_result_join_serialization_tail_consumes_the_same_original_body_cutoff(self) -> None:
        """Actual final semantic comparison time is work, not a renewed allowance."""
        self._result_tail_fault(False)

    def test_result_join_cannot_replace_its_original_guard_at_final_comparison(self) -> None:
        """A late instance-method shadow cannot waive the original finite final guard."""
        self._result_tail_fault(True)

    def _result_tail_fault(self, shadow: bool) -> None:
        """Finish the actual final digest after the cutoff without changing raw evidence."""
        work = self.f.work()
        replay_body_source_color(work)
        record = body_source_result_fields(work)
        calls = []

        def measured(value: object) -> str:
            """Model only the final actual digest finishing after the original cutoff."""
            actual = digest(value)
            calls.append(actual)
            if len(calls) == 2 * len(record):
                self.mono[0] = work.clock.end + 0.001
                if shadow:
                    work.guard = lambda: None
            return actual

        with patch("guided_body_source_color_result.digest", side_effect=measured):
            self.assertRaisesRegex(RuntimeError, "deadline|expired|changed", recheck_body_source_result, record, work)
        self.assertEqual(len(calls), 2 * len(record))

    def _body_receipt(self) -> BodyReadAuthority:
        """Create actual replay/receipt/entry with explicitly unqualified TEST AV data."""
        work = self.f.work()
        replay_body_source_color(work)
        owner = SimpleNamespace(evidence=[], resolved_clips=(), composition={"TEST": "not rendered"}, caption_screen=None)
        record = _receipt(work, owner, ({"programDeliveryReceipt": {"TEST": "not delivered"}}, {"TEST": "not decoded"}))
        invocation, root = work.control.invocation, work.control.root
        write_new(root / "body-worker-entry.json", {"schemaVersion": 1, "kind": "guided-body-worker-entry",
            "activationPath": str(invocation.activation_path), "activationSha256": invocation.activation_sha256,
            "inputSha256": invocation.input_sha256})
        return BodyReadAuthority(invocation, file_hash(root / "body-result.json"), record["receiptHash"])

    def _readback_leaves(self) -> ExitStack:
        """Keep actual final raw receipt/entry and replay join; only whole-AV leaves are TEST."""
        stack = ExitStack()
        stack.enter_context(patch("guided_body_inputs.verify_runtime_controls"))
        for name in ("read_body_preparation", "_graphics", "read_body_graphics", "_screen", "verify_body_media_files"):
            stack.enter_context(patch("guided_body_read." + name))
        stack.enter_context(patch.object(BodyWork, "revalidate", BodyWork.guard))
        return stack

    def _rewrite_body_output(self, name: str, raw: bytes) -> None:
        """Write only literal original current TEST output controls, never arbitrary refs."""
        self.assertIn(name, ("body-result.json", "body-worker-entry.json"))
        target = self.f.control.root / name
        self.assertTrue(target.is_relative_to(self.f.root))
        self.assertEqual(target.resolve(strict=True), target)
        info = target.lstat()
        self.assertTrue(stat.S_ISREG(info.st_mode))
        self.assertEqual((info.st_uid, info.st_nlink), (os.geteuid(), 1))
        target.write_bytes(raw)

    def test_current_body_result_raw_authority_cannot_be_rebound_during_readback(self) -> None:
        """A new raw serialization cannot replace the externally supplied original SHA."""
        held = self._body_receipt()
        original_sha, changed = held.receipt_sha256, []

        def media(_record: dict, _work: BodyWork) -> None:
            """TEST AV leaf races only original TEMP receipt bytes and caller metadata."""
            target = self.f.control.root / "body-result.json"
            self._rewrite_body_output("body-result.json", target.read_bytes() + b"\n")
            object.__setattr__(held, "receipt_sha256", file_hash(target))
            changed.append(held.receipt_sha256)

        with self._readback_leaves(), patch("guided_body_read._media", side_effect=media):
            self.assertRaisesRegex(RuntimeError, "original|changed|authority", read_result, self.f.control.root, held, 300)
        self.assertEqual(len(changed), 1)
        self.assertNotEqual(changed[0], original_sha)

    def test_current_worker_entry_identity_is_held_across_readback(self) -> None:
        """Equal worker-entry bytes do not permit a later original-file replacement."""
        held = self._body_receipt()
        changed = []

        def media(_record: dict, _work: BodyWork) -> None:
            """TEST AV leaf touches only the named original single-link entry control."""
            target = self.f.control.root / "body-worker-entry.json"
            before = target.lstat().st_mtime_ns
            self._rewrite_body_output("body-worker-entry.json", target.read_bytes())
            changed.append(target.lstat().st_mtime_ns != before)

        with self._readback_leaves(), patch("guided_body_read._media", side_effect=media):
            self.assertRaisesRegex(RuntimeError, "original|changed|entry", read_result, self.f.control.root, held, 300)
        self.assertEqual(changed, [True])

    def test_failure_marker_after_final_actual_raw_read_keeps_result_unselectable(self) -> None:
        """An orphan failure cannot hide between final raw receipt read and return."""
        held = self._body_receipt()
        calls = []

        def observed(root: Path, authority: BodyReadAuthority) -> dict:
            """Retain the actual reader; fault only after its second completed raw check."""
            value = read_body_record(root, authority)
            calls.append(value)
            if len(calls) == 2:
                self.assertEqual(root, self.f.control.root)
                self.assertTrue(root.is_relative_to(self.f.root))
                self.assertEqual(root.resolve(strict=True), root)
                self.assertEqual(root.lstat().st_uid, os.geteuid())
                write_new(root / "body-failed.json", {"TEST": "late failure marker; no native worker"})
            return value

        with self._readback_leaves(), patch("guided_body_read._media"), \
                patch("guided_body_read.read_body_record", side_effect=observed):
            self.assertRaisesRegex(RuntimeError, "failed|failure|changed", read_result, self.f.control.root, held, 300)
        self.assertEqual(len(calls), 2)
        self.assertTrue((self.f.control.root / "body-failed.json").exists())
