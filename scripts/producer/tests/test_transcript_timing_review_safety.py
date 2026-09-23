"""Adversarial stored timing-review bindings, immutable history and no-follow reads."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]

from _timing_review_fixture import TimingReviewFixture
from cut_preview_io import digest
from transcript_cut_contract import check
from transcript_cut_evidence import SourceEvidence
from transcript_timing_review_authority import _windows
from transcript_timing_review_contract import record_bytes
from transcript_timing_review import execute
import transcript_timing_review_store as store


class TimingReviewSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = TimingReviewFixture()
        self.addCleanup(self.fixture.close)
        self.prepared = self.fixture.prepare()
        self.root = next((self.fixture.manifest.parent / ".sniper-timing-reviews").iterdir())

    def _resolved(self) -> dict:
        return self.fixture.record(self.fixture.submission(self.prepared))

    def test_missing_false_wrong_window_and_incompatible_disposition_reject(self) -> None:
        original = self.fixture.submission(self.prepared)
        mutations = [
            lambda row: row.pop("listenedToSourceWindows"),
            lambda row: row["listenedToSourceWindows"][0].update(listened=False),
            lambda row: row["listenedToSourceWindows"][0].update(windowHash="0" * 64),
            lambda row: row["sourceWindows"][0].update(start=1),
            lambda row: row.update(disposition="kept-audited"),
            lambda row: row.update(comparedExactCutBoundary=1),
        ]
        for mutate in mutations:
            sent = copy.deepcopy(original)
            mutate(sent["reviews"][0])
            with self.assertRaises((RuntimeError, ValueError)):
                self.fixture.record(sent)
        self.assertEqual(list((self.root / "decisions").iterdir()), [])

    def test_missing_anomaly_and_duplicate_or_partial_window_review_reject(self) -> None:
        sent = self.fixture.submission(self.prepared)
        self.assertEqual(len(sent["reviews"][0]["listenedToSourceWindows"]), 2)
        variants = [copy.deepcopy(sent) for _ in range(3)]
        variants[0]["reviews"].pop()
        variants[1]["reviews"][0]["listenedToSourceWindows"].pop()
        variants[2]["reviews"][0]["listenedToSourceWindows"][1] = variants[2]["reviews"][0]["listenedToSourceWindows"][0]
        for variant in variants:
            with self.assertRaisesRegex(RuntimeError, "every exact anomaly|both source contexts|not exact"):
                self.fixture.record(variant)

    def test_self_consistently_resealed_request_window_is_not_authority(self) -> None:
        self._resolved()
        file = self.root / "request.json"
        request = json.loads(file.read_bytes())
        anomaly = request["anomalies"][0]
        anomaly["sourceWindows"][0]["end"] += 1
        anomaly["anomalyHash"] = digest({key: value for key, value in anomaly.items() if key != "anomalyHash"})
        request["requestHash"] = digest({key: value for key, value in request.items() if key != "requestHash"})
        file.write_bytes(record_bytes(request))
        self.assertFalse(self.fixture.check()["ok"])

    def test_latest_unresolved_tail_deletion_cannot_reactivate_old_approval(self) -> None:
        resolved = self._resolved()
        self.fixture.record(self.fixture.submission(resolved, resolved=False))
        (self.root / "decisions" / "0002.json").rename(self.fixture.root / "retained-second.json")
        result = self.fixture.check()
        self.assertFalse(result["ok"])
        self.assertIn("head differs", " ".join(result["errors"]))

    def test_missing_head_partial_append_and_extra_fork_fail_closed(self) -> None:
        self._resolved()
        head = self.root / "head.json"
        original = head.read_bytes()
        head.unlink()
        self.assertFalse(self.fixture.check()["ok"])
        head.write_bytes(original)
        extra = self.root / "decisions" / "0001-fork.json"
        extra.write_bytes((self.root / "decisions" / "0001.json").read_bytes())
        self.assertFalse(self.fixture.check()["ok"])
        extra.unlink()
        (self.root / "decisions" / "0002.json").write_bytes(b"{")
        self.assertFalse(self.fixture.check()["ok"])

    def test_crash_before_head_commit_is_blocked_not_latest_good_fallback(self) -> None:
        with patch.object(store, "_advance_head", side_effect=RuntimeError("TEST interrupted publication")):
            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                self._resolved()
        self.assertTrue((self.root / "decisions" / "0001.json").exists())
        self.assertFalse(self.fixture.check()["ok"])

    def test_head_change_during_commit_is_not_overwritten(self) -> None:
        real = store.write_new
        changed = b'{"TEST":"unexpected concurrently changed head"}\n'

        def mutate(path: Path, value: dict) -> None:
            real(path, value)
            if path.name.startswith(".head-"):
                (self.root / "head.json").write_bytes(changed)

        with patch.object(store, "write_new", side_effect=mutate):
            with self.assertRaises(RuntimeError):
                self._resolved()
        self.assertEqual((self.root / "head.json").read_bytes(), changed)
        self.assertFalse(self.fixture.check()["ok"])

    def test_sequence_gap_malformed_head_and_resealed_wrong_disposition_reject(self) -> None:
        self._resolved()
        file = self.root / "decisions" / "0001.json"
        original = file.read_bytes()
        row = json.loads(original)
        row["submission"]["reviews"][0]["disposition"] = "kept-audited"
        row["decisionHash"] = digest({key: value for key, value in row.items() if key != "decisionHash"})
        file.write_bytes(record_bytes(row))
        self.assertFalse(self.fixture.check()["ok"])
        file.write_bytes(original)
        file.rename(self.root / "decisions" / "0002.json")
        self.assertFalse(self.fixture.check()["ok"])
        (self.root / "decisions" / "0002.json").rename(file)
        head = json.loads((self.root / "head.json").read_bytes())
        head["sequence"] = True
        (self.root / "head.json").write_bytes(record_bytes(head))
        self.assertFalse(self.fixture.check()["ok"])

    def test_all_thirtytwo_records_are_bounded_and_thirtythird_is_rejected(self) -> None:
        current = self.prepared
        for _index in range(32):
            current = self.fixture.record(self.fixture.submission(current, resolved=False))
        with self.assertRaisesRegex(RuntimeError, "chain is full"):
            self.fixture.record(self.fixture.submission(current))
        self.assertEqual(len(list((self.root / "decisions").iterdir())), 32)
        self.assertFalse(self.fixture.check()["ok"])

    def test_concurrent_cli_submissions_cannot_both_append_at_the_same_head(self) -> None:
        command = str(Path(__file__).resolve().parents[1] / "transcript_timing_review.py")
        processes = []
        try:
            for index in range(2):
                file = self.fixture.root / f"TEST-submission-{index}.json"
                file.write_text(json.dumps(self.fixture.submission(self.prepared)))
                processes.append(subprocess.Popen([sys.executable, command, "record", *self.fixture.paths, str(file)],
                                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE))
            output = [process.communicate(timeout=5) for process in processes]
            self.assertEqual(sorted(process.returncode for process in processes), [0, 1], output)
            self.assertEqual(len(list((self.root / "decisions").iterdir())), 1)
            self.assertTrue(self.fixture.check()["ok"])
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=3)

    def test_noncanonical_duplicate_key_record_and_oversized_submission_reject(self) -> None:
        self._resolved()
        file = self.root / "decisions" / "0001.json"
        raw = file.read_bytes()
        file.write_bytes(b'{"schemaVersion":1,' + raw[1:])
        self.assertFalse(self.fixture.check()["ok"])
        file.write_bytes(raw)
        supplied = self.fixture.root / "too-large.json"
        supplied.write_bytes(b" " * (1024 * 1024 + 1))
        with self.assertRaisesRegex(RuntimeError, "exceeds byte limit: 1048577 > 1048576"):
            execute("record", self.fixture.paths, supplied)

    def test_symlink_hardlink_and_fifo_records_fail_without_blocking(self) -> None:
        self._resolved()
        file = self.root / "decisions" / "0001.json"
        retained = self.fixture.root / "original-decision.json"
        file.rename(retained)
        file.symlink_to(retained)
        self.assertFalse(self.fixture.check()["ok"])
        file.unlink()
        os.link(retained, file)
        self.assertFalse(self.fixture.check()["ok"])
        file.unlink()
        os.mkfifo(file)
        result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "transcript_cut_contract.py"),
                                 *self.fixture.paths], capture_output=True, timeout=3, check=False)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(json.loads(result.stdout)["ok"])

    def test_external_snapshot_fifo_is_type_rejected_before_a_blocking_read(self) -> None:
        fifo = self.fixture.root / "source.fifo"
        os.mkfifo(fifo)
        source_root = Path(__file__).resolve().parents[1]
        code = "from headless.external_media_snapshot import _source_fd; import sys; _source_fd(sys.argv[1])"
        result = subprocess.run([sys.executable, "-c", code, str(fifo)], cwd=source_root,
                                capture_output=True, timeout=3, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"one bounded regular file", result.stderr)

    def test_actual_gate_plan_copy_and_only_style_target_additions_reuse_exact_review(self) -> None:
        self._resolved()
        copied = self.fixture.root / "operations" / "readiness" / "gate-plan.json"
        copied.parent.mkdir(parents=True)
        plan = json.loads(self.fixture.plan.read_bytes())
        plan["target"].update(graphicsStyle="overlay-rich", graphicsStyleRationale="TEST visual-only selection.")
        plan["graphicsTrack"] = [{"id": "TEST-only", "outStart": 0, "outEnd": 1}]
        copied.write_text(json.dumps(plan, indent=2))
        result = check(str(copied), self.fixture.paths[1], self.fixture.paths[2])
        self.assertTrue(result["ok"], result["errors"])
        self.assertFalse((copied.parent / ".sniper-timing-reviews").exists())
        for field, value in (("mode", "short"), ("fps", 24), ("aspect", "9:16")):
            changed = copy.deepcopy(plan)
            changed["target"][field] = value
            copied.write_text(json.dumps(changed))
            # The short scope has no hook anomaly; it cannot select the earlier timing fact.
            result = check(str(copied), self.fixture.paths[1], self.fixture.paths[2])
            quality = result["metrics"]["receipt"]["outputQuality"]
            self.assertNotEqual(quality.get("timingReview", {}).get("state"), "resolved")
            if field != "mode":
                self.assertFalse(result["ok"])
            with self.assertRaises((OSError, RuntimeError)):
                execute("status", (str(copied), *self.fixture.paths[1:]))

    def test_other_manifest_path_cannot_select_this_manifest_namespace(self) -> None:
        self._resolved()
        other = self.fixture.manifest.parent / "other-manifest.json"
        other.write_bytes(self.fixture.manifest.read_bytes())
        self.assertFalse(check(self.fixture.paths[0], self.fixture.paths[1], str(other))["ok"])

    def test_distant_boundary_uses_two_short_contexts_without_truncating_suspect(self) -> None:
        word = {"word": "If", "start": 0.37, "end": 8.64}
        source = SourceEvidence("raw-1", 700, "TEST.json", [word])
        windows = _windows(word, 600, source)
        self.assertEqual(len(windows), 2)
        self.assertEqual((windows[1]["start"], windows[1]["end"]), (598, 602))
        self.assertLessEqual(windows[0]["start"], word["start"])
        self.assertGreaterEqual(windows[0]["end"], word["end"])
        self.assertLess(sum(row["end"] - row["start"] for row in windows), 15)


if __name__ == "__main__":
    unittest.main(verbosity=2)
