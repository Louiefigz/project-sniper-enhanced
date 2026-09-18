"""TEST ONLY correction consumption at actual cut gates; no real listening."""
from __future__ import annotations

import json
from pathlib import Path
import signal
import time
from typing import Callable
import unittest
from unittest.mock import patch

from _corrected_manifest_fixture import CorrectedManifestFixture
from color.deadline import wall_budget
from cut_preview_io import write_new
from transcript_cut_contract import check
from transcript_cut_evidence import source_evidence
import transcript_cut_evidence as cut_evidence
from transcript_source_authority import bind_result, observe_source, verify_result
import transcript_correction_read as consumer


class CorrectedTranscriptConsumerTests(unittest.TestCase):
    """Use actual local transaction/receipt reads with fake admitted-media fixtures."""

    def setUp(self) -> None:
        """Create a fresh simulated correction and unselected manifest."""
        self.fixture = CorrectedManifestFixture()
        self.addCleanup(self.fixture.close)
        self.fixture.commit()
        self.fixture.publish()

    def evidence(self) -> tuple[dict, list[str]]:
        """Invoke the real source-evidence path on the explicit new manifest."""
        fx = self.fixture
        errors: list[str] = []
        sources, _authority = source_evidence(fx.revised(), str(fx.target), str(fx.manifest.parent),
                                               {"raw-1"}, errors)
        return sources, errors

    def test_exact_committed_correction_is_consumed_and_old_cut_is_not_rewritten(self) -> None:
        """Validate a new cut's correction without rewriting the original cut."""
        fx = self.fixture
        sources, errors = self.evidence()
        self.assertEqual(errors, [])
        self.assertEqual(sources["raw-1"].words[1]["start"], 13.4)
        self.assertEqual(fx.originals, {path: path.read_bytes() for path in fx.originals})
        new_plan = fx.plan.parent / "TEST-new-cut-revision.json"
        plan = json.loads(fx.plan.read_text())
        plan["cutTrack"][0]["start"] = 13.4
        write_new(new_plan, plan)
        result = check(str(new_plan), str(fx.manifest.parent), str(fx.target))
        self.assertTrue(result["ok"], result["errors"])
        self.assertFalse(any("correction authority blocked" in row for row in result["errors"]))
        self.assertEqual(fx.plan.read_bytes(), fx.originals[fx.plan])
        self.assertNotIn("deliveryApproved", result)  # A cut check cannot grant delivery.

    def test_removing_commit_blocks_despite_still_valid_source_digest(self) -> None:
        """A self-consistent source digest cannot substitute for a commit."""
        fx = self.fixture
        transcript = Path(fx.committed["revision"]["path"])
        payload = json.loads(transcript.read_text())
        self.assertIsNone(verify_result(payload, fx.revised()["sources"][0], str(transcript)))
        (transcript.parent / "commit.json").unlink()  # Exact TEST-only store artifact.
        _sources, errors = self.evidence()
        self.assertTrue(any("correction authority blocked" in row for row in errors))

    def test_stale_decision_blocks_actual_cut_gate(self) -> None:
        """The real cut gate rejects changed human-review record bytes."""
        fx = self.fixture
        record = Path(fx.committed["revision"]["recordPath"])
        record.write_bytes(record.read_bytes() + b" ")
        result = check(str(fx.plan), str(fx.manifest.parent), str(fx.target))
        self.assertFalse(result["ok"])
        self.assertTrue(any("correction authority blocked" in row for row in result["errors"]))

    def test_self_consistent_transcript_rebind_cannot_change_reviewed_text(self) -> None:
        """Rehashing changed words does not authorize an unreviewed correction."""
        fx = self.fixture
        path = Path(fx.committed["revision"]["path"])
        payload = json.loads(path.read_text())
        payload.pop("sourceMediaAuthority")
        payload["transcript"][0]["words"][2]["word"] = "TEST-forged-negation"
        row = fx.revised()["sources"][0]
        observed = observe_source(fx.media, (row["sourceSha256"], row["sourceSizeBytes"]))
        rebound = bind_result(payload, observed)
        path.write_text(json.dumps(rebound))
        self.assertIsNone(verify_result(rebound, row, str(path)))
        _sources, errors = self.evidence()
        self.assertTrue(any("correction authority blocked" in error for error in errors))

    def test_copied_corrected_transcript_is_not_original_transaction_authority(self) -> None:
        """The explicit manifest cannot redirect to a transplanted transcript."""
        fx = self.fixture
        copied = fx.manifest.parent / "TEST-copied-corrected.json"
        copied.write_bytes(Path(fx.committed["revision"]["path"]).read_bytes())
        manifest = fx.revised()
        manifest["sources"][0]["transcriptPath"] = copied.name
        fx.target.write_text(json.dumps(manifest))
        _sources, errors = self.evidence()
        self.assertTrue(any("committed transcript pointer" in row for row in errors))

    def test_current_source_duration_cannot_transplant_review(self) -> None:
        """A different current source duration invalidates the original review."""
        fx = self.fixture
        manifest = fx.revised()
        manifest["sources"][0]["duration"] = 100
        fx.target.write_text(json.dumps(manifest))
        _sources, errors = self.evidence()
        self.assertTrue(any("duration differs" in row for row in errors))

    def test_existing_alarm_is_borrowed_not_nested_or_extended(self) -> None:
        """Restore the exact original deadline after a successful short read."""
        expiry = time.monotonic() + 15
        with wall_budget(expiry):
            before = signal.getitimer(signal.ITIMER_REAL)[0]
            _sources, errors = self.evidence()
            after = signal.getitimer(signal.ITIMER_REAL)[0]
            self.assertEqual(errors, [])
            self.assertGreater(after, 0)
            self.assertLess(after, before)

    def test_guard_applies_to_common_reader(self) -> None:
        """An injected common-reader delay consumes the same command expiry."""
        fx = self.fixture
        path = Path(fx.committed["revision"]["path"])
        payload = json.loads(path.read_text())
        def expired(_inputs: object, _proposed: dict, guard: Callable[[], None]) -> dict:
            """Expire the real passed guard without changing production data."""
            with patch.object(consumer.time, "monotonic", return_value=time.monotonic() + 121):
                guard()
        with patch.object(consumer, "inspect_current", side_effect=expired):
            error = consumer.correction_error(payload, fx.revised()["sources"][0], str(path))
        self.assertIn("original work budget", error)

    def test_ordinary_transcript_needs_no_correction_store_or_timer(self) -> None:
        """Leave uncorrected ASR outside the reserved route unchanged."""
        fx = self.fixture
        with patch.object(consumer, "inspect_current") as inspect:
            payload = json.loads(fx.transcript.read_text())
            consumer.require_correction(payload, json.loads(fx.manifest.read_text())["sources"][0], str(fx.transcript))
            inspect.assert_not_called()

    def test_initial_transcript_hash_must_match_strongly_observed_bytes(self) -> None:
        """Detect drift between initial cut evidence and the corrected payload."""
        original = cut_evidence.file_hash
        corrected = self.fixture.committed["revision"]["path"]
        def old_hash(path: str) -> str:
            """Inject stale initial transcript evidence, not a valid authority."""
            return "a" * 64 if path == corrected else original(path)
        with patch.object(cut_evidence, "file_hash", side_effect=old_hash):
            _sources, errors = self.evidence()
        self.assertTrue(any("initial cut evidence observation" in error for error in errors))

    def test_stripping_marker_and_rebinding_cannot_disguise_corrected_bytes(self) -> None:
        """Reproduce the independent review bypass without a real speech record."""
        fx = self.fixture
        path = Path(fx.committed["revision"]["path"])
        payload = json.loads(path.read_text())
        payload.pop("timingCorrectionAuthority")
        payload.pop("sourceMediaAuthority")
        payload["transcript"][0]["words"][2]["word"] = "TEST-forged-negation"
        source = fx.revised()["sources"][0]
        observed = observe_source(fx.media, (source["sourceSha256"], source["sourceSizeBytes"]))
        rebound = bind_result(payload, observed)
        path.write_text(json.dumps(rebound))
        self.assertIsNone(verify_result(rebound, source, str(path)))
        _sources, errors = self.evidence()
        self.assertTrue(any("cannot omit its correction authority" in row for row in errors))

    def test_named_manifest_cannot_move_corrected_pointer_back_to_ordinary_asr(self) -> None:
        """The reserved new manifest keeps an explicit selected-transcript identity."""
        fx = self.fixture
        manifest = fx.revised()
        manifest["sources"][0]["transcriptPath"] = fx.transcript.name
        fx.target.write_text(json.dumps(manifest))
        _sources, errors = self.evidence()
        self.assertTrue(any("committed transcript pointer" in row for row in errors))

    def test_long_parent_alarm_is_shortened_for_blocking_work_and_restored(self) -> None:
        """Interrupt before a long parent expires, then retain its original expiry."""
        fx = self.fixture
        path = Path(fx.committed["revision"]["path"])
        payload = json.loads(path.read_text())
        expiry = time.monotonic() + 1
        with wall_budget(expiry):
            before = signal.getitimer(signal.ITIMER_REAL)[0]
            started = time.monotonic()
            with patch.object(consumer, "WORK_SECONDS", .02), \
                    patch.object(consumer, "_consume", side_effect=lambda *_args: time.sleep(.20)):
                error = consumer.correction_error(payload, fx.revised()["sources"][0], str(path))
            elapsed = time.monotonic() - started
            after = signal.getitimer(signal.ITIMER_REAL)[0]
            self.assertIn("original work budget", error)
            self.assertLess(elapsed, .15)
            self.assertGreater(after, 0)
            self.assertLessEqual(after, before - elapsed + .002)


if __name__ == "__main__":
    unittest.main()
