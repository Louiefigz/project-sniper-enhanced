"""Manual markers: one process per command, exact linked v2 spans in an explicit run."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from _common import *  # noqa: F401,F403
import stage_timing as st
import stage_timing_markers as markers
from stage_timing_context import LINEAGE_VARIABLES
from stage_timing_report import summarize_timings

_PRODUCER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HERMETIC = mock.patch.dict(os.environ)


def setUpModule() -> None:
    """Exported SNIPER_TIMING_* from the caller's shell must not change these results."""
    _HERMETIC.start()
    for name in LINEAGE_VARIABLES:
        os.environ.pop(name, None)


def tearDownModule() -> None:
    _HERMETIC.stop()


class ManualMarkerTests(unittest.TestCase):
    """The documented CLI, one process per marker, writes exact linked v2 spans."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.journal = Path(st.journal_path(self.tmp.name))

    def command(self, *args: str) -> list[str]:
        """The marker command line an agent runs; never the caller's lineage."""
        return [sys.executable, os.path.join(_PRODUCER_DIR, "stage_timing.py"), self.tmp.name, *args]

    def mark(self, *args: str, code: int = 0, env: dict | None = None) -> dict:
        """Run one marker command as the agent would; return its JSON outcome."""
        proc = subprocess.run(self.command(*args), capture_output=True, text=True, cwd=_PRODUCER_DIR,
                              env={**os.environ, **(env or {})})
        self.assertEqual(proc.returncode, code, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)

    def rows(self) -> list[dict]:
        text = self.journal.read_text() if self.journal.exists() else ""
        return [json.loads(line) for line in text.splitlines()]

    def test_documented_markers_pair_exactly_across_processes(self) -> None:
        for stage, event in (("production_total", "start"), ("clip_a_asset_search", "start"),
                             ("clip_a_asset_search", "end"), ("production_total", "end")):
            outcome = self.mark(stage, event, "--run-id", "batch-1")
            self.assertTrue(outcome["recorded"])
            self.assertFalse(outcome["qualityApproved"] or outcome["authoritative"])
        rows = self.rows()
        self.assertTrue(all(r["schemaVersion"] == 2 and r["clock"] == "wall-epoch" for r in rows))
        self.assertEqual({r["runId"] for r in rows}, {"batch-1"})
        report = summarize_timings(rows)
        self.assertTrue(report["allRecordedSpansPaired"], report["issues"])
        self.assertEqual({s["attribution"] for s in report["spans"]}, {"manual-wall-clock"})
        self.assertEqual(report["recordedWindow"]["status"], "recorded-window")

    def test_a_marker_without_a_run_is_refused_before_writing(self) -> None:
        for args in (("production_total", "start"), ("clip_c", "handoff", "--phase", "ready",
                                                      "--task-id", "author-c")):
            self.assertIn("needs its run", self.mark(*args, code=1)["reason"])
        self.assertEqual(self.rows(), [])

    def test_markers_join_parent_run_and_carry_task_and_activity(self) -> None:
        env = {"SNIPER_TIMING_RUN_ID": "batch-run", "SNIPER_TIMING_TASK_ID": "env-task"}
        parent = self.mark("production_total", "start", env=env)["spanId"]
        self.mark("clip_b_author", "start", "--parent-span-id", parent, "--activity", "model",
                  "--task-id", "author-b", "--claim-epoch", "3", "--host-turn-id", "turn-9")
        self.mark("clip_b_author", "end", "--status", "failed")
        starts = {r["stage"]: r for r in self.rows() if r["event"] == "start"}
        child = starts["clip_b_author"]
        self.assertEqual((child["parentSpanId"], child["runId"]), (parent, "batch-run"))
        self.assertEqual((child["taskId"], child["claimEpoch"], child["hostTurnId"]), ("author-b", 3, "turn-9"))
        self.assertEqual(starts["production_total"]["taskId"], "env-task")
        self.mark("x", "start", "--parent-span-id", parent, "--run-id", "other-run", code=1)
        report = summarize_timings(self.rows())
        self.assertEqual(report["executionStatusCounts"]["failed"], 1)
        self.assertEqual(report["attribution"]["categories"]["modelExecution"]["status"], "measured")

    def test_ambiguous_missing_and_replayed_ends_are_refused_without_writing(self) -> None:
        first = self.mark("critic", "start", "--run-id", "r1")["spanId"]
        self.mark("critic", "start", "--run-id", "r1")
        before = self.journal.read_text()
        self.assertIn("2 open manual starts", self.mark("critic", "end", "--run-id", "r1", code=1)["reason"])
        self.mark("missing_label", "end", code=1)
        self.mark("critic", "start", "--parent-span-id", "no-such-span", code=1)
        self.assertEqual(self.journal.read_text(), before)
        self.assertEqual(self.mark("critic", "end", "--span-id", first)["spanId"], first)
        self.mark("critic", "end", "--span-id", first, code=1)  # a replayed end finds no open start
        self.mark("critic", "end")
        self.assertTrue(summarize_timings(self.rows())["allRecordedSpansPaired"])

    def test_an_end_closes_only_a_start_of_its_own_run(self) -> None:
        self.mark("critic", "start", "--run-id", "run-a")
        self.mark("critic", "start", "--run-id", "run-b")
        self.assertIn("2 run(s)", self.mark("critic", "end", code=1)["reason"])
        self.mark("critic", "end", env={"SNIPER_TIMING_RUN_ID": "run-b"})
        self.assertEqual(self.rows()[-1]["runId"], "run-b")
        self.mark("critic", "end", env={"SNIPER_TIMING_RUN_ID": "run-b"}, code=1)
        self.mark("critic", "end")
        self.assertEqual([r["runId"] for r in self.rows() if r["event"] == "end"], ["run-b", "run-a"])

    def test_an_end_after_a_wall_clock_step_back_is_refused(self) -> None:
        start = {"schemaVersion": 2, "writerId": markers.MANUAL_WRITER, "clock": markers.WALL_CLOCK,
                 "event": "start", "stage": "critic", "spanId": "s1", "runId": "r", "ts": time.time() + 1000}
        args = markers._parser().parse_args([self.tmp.name, "critic", "end"])
        with self.assertRaisesRegex(markers.MarkerRefused, "stepped back"):
            markers.end(args, [start])

    def test_concurrent_ends_close_one_start_exactly_once(self) -> None:
        self.mark("critic", "start", "--run-id", "r")
        ends = [subprocess.Popen(self.command("critic", "end"), cwd=_PRODUCER_DIR, stdout=subprocess.DEVNULL)
                for _ in range(4)]
        self.assertEqual(sorted(process.wait() for process in ends), [0, 1, 1, 1])
        self.assertEqual(sum(r["event"] == "end" for r in self.rows()), 1)

    def test_an_unwritable_folder_or_planted_lock_link_reports_not_crashes(self) -> None:
        target = Path(self.tmp.name) / "elsewhere"
        (Path(self.tmp.name) / "stage_timings.jsonl.lock").symlink_to(target)  # dangling
        outcome = self.mark("critic", "start", "--run-id", "r")
        self.assertEqual((outcome["recorded"], outcome["reason"].split(":")[0]), (False, "journal-unwritable"))
        self.assertFalse(target.exists(), "O_NOFOLLOW: the link target is never created")
        readonly = Path(self.tmp.name) / "readonly"
        readonly.mkdir()
        readonly.chmod(0o500)
        self.addCleanup(readonly.chmod, 0o700)
        proc = subprocess.run([*self.command("x")[:2], str(readonly), "critic", "start", "--run-id", "r"],
                              capture_output=True, text=True, cwd=_PRODUCER_DIR)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["reason"].startswith("journal-unwritable"))

    def test_a_start_without_a_numeric_wall_time_is_refused_not_crashed(self) -> None:
        start = {"schemaVersion": 2, "writerId": markers.MANUAL_WRITER, "clock": markers.WALL_CLOCK,
                 "event": "start", "stage": "critic", "spanId": "s1", "runId": "r", "ts": "yesterday"}
        args = markers._parser().parse_args([self.tmp.name, "critic", "end"])
        with self.assertRaisesRegex(markers.MarkerRefused, "no numeric wall-clock time"):
            markers.end(args, [start])

    def test_run_id_never_adopts_another_runs_inherited_lineage(self) -> None:
        refused = self.mark("critic", "start", "--run-id", "X", env={"SNIPER_TIMING_RUN_ID": "Y"}, code=1)
        self.assertIn("disagrees", refused["reason"])
        self.mark("critic", "start", "--run-id", "X", env={"SNIPER_TIMING_TASK_ID": "y-task"}, code=1)
        self.mark("critic", "handoff", "--phase", "ready", "--task-id", "t", "--run-id", "X",
                  env={"SNIPER_TIMING_PARENT_SPAN_ID": "y-parent"}, code=1)
        self.assertEqual(self.rows(), [])
        self.mark("critic", "start", "--run-id", "X", env={"SNIPER_TIMING_RUN_ID": "X"})
        self.assertEqual(self.rows()[0]["runId"], "X")

    def test_an_exact_span_id_end_ignores_an_environment_naming_another_run(self) -> None:
        span = self.mark("critic", "start", "--run-id", "run-a")["spanId"]
        closed = self.mark("critic", "end", "--span-id", span, env={"SNIPER_TIMING_RUN_ID": "run-b"})
        self.assertEqual(closed["spanId"], span)
        self.assertEqual(self.rows()[-1]["runId"], "run-a")

    def test_an_out_of_range_claim_epoch_is_a_usage_error(self) -> None:
        proc = subprocess.run(self.command("critic", "start", "--run-id", "r", "--task-id", "t",
                                           "--claim-epoch", str(2**53)), capture_output=True, text=True,
                              cwd=_PRODUCER_DIR)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--claim-epoch must be an integer from 0", proc.stderr)
        self.assertEqual(self.rows(), [])

    def test_handoff_markers_record_or_refuse_the_task_vocabulary(self) -> None:
        batch = self.mark("production_total", "start", env={"SNIPER_TIMING_RUN_ID": "batch-7"})["spanId"]
        refused = self.mark("clip_c", "handoff", "--phase", "artifact-published", "--parent-span-id", batch,
                            "--task-id", "author-c", "--claim-epoch", "1", code=1)
        self.assertIn("handoff-missing-artifact", refused["reason"])
        self.assertTrue(self.mark("clip_c", "handoff", "--phase", "artifact-published", "--task-id",
                                  "author-c", "--claim-epoch", "1", "--artifact-sha256", "c" * 64,
                                  "--parent-span-id", batch)["eventId"])
        event = self.rows()[-1]
        self.assertEqual((event["runId"], event["parentSpanId"], event["taskId"]), ("batch-7", batch, "author-c"))
        handoffs = summarize_timings(self.rows())["handoffs"]
        self.assertEqual(handoffs["publications"][0]["status"], "awaiting-acceptance")
        self.assertEqual(len(self.rows()), 2)

    def test_start_records_the_handed_over_title_and_script_identities(self) -> None:
        title, script = "ab" * 32, "cd" * 32
        for bad in (["clip-1-title"], [f"clip-1-title={title}", f"clip-1-title={script}"],
                    [f"clip-1-title={title.upper()}"]):
            args = [item for value in bad for item in ("--handover", value)]
            outcome = self.mark("production_total", "start", "--run-id", "b", *args, code=1)
            self.assertIn("handover", outcome["reason"])
            self.assertEqual(self.rows(), [])
        self.mark("production_total", "start", "--run-id", "b", "--handover", f"clip-1-title={title}",
                  "--handover", f"clip-1-script={script}")
        self.mark("production_total", "end", "--run-id", "b")
        self.assertNotIn("handover", self.rows()[-1], "identities are recorded once, at the start")
        window = summarize_timings(self.rows())["recordedWindow"]
        self.assertEqual(window["handover"], [{"label": "clip-1-title", "sha256": title},
                                              {"label": "clip-1-script", "sha256": script}])


if __name__ == "__main__":
    unittest.main(verbosity=2)
