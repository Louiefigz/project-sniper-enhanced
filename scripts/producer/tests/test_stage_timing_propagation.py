"""Production spawn boundaries preserve lineage without changing renderer commands."""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from _common import *  # noqa: F401,F403
import assemble
import current_render_graph_cli as graph_cli
import draft_render
import render
import native_work_lease
from native_render_processes import ProcessRequest
from native_render_resources import GIB, parse_snapshot
from stage_timing import stage_span
from stage_timing_context import LINEAGE_VARIABLES, PARENT_SPAN, lineage_environment
from stage_timing_report import summarize_timings
from studio import native_budget_owner, native_budget_store, studio_review
from studio.native_run_config import launch_environment
from studio.native_short_pipeline import NativeShortPipeline
from test_native_render_resources import raw_sample
from _native_pool_fixture import pool_lease_double

PRODUCER = str(Path(__file__).resolve().parents[1])
_HERMETIC = mock.patch.dict(os.environ)


def setUpModule() -> None:
    """Exported SNIPER_TIMING_* from the caller's shell must not change these results."""
    _HERMETIC.start()
    for name in LINEAGE_VARIABLES:
        os.environ.pop(name, None)


def tearDownModule() -> None:
    _HERMETIC.stop()


LEAF = """import sys
sys.path.insert(0, sys.argv[1])
from stage_timing import stage_span
with stage_span(sys.argv[2], 'grandchild'):
    pass
"""
CHILD = """import sys
sys.path.insert(0, sys.argv[1])
import render
from stage_timing import stage_span
with stage_span(sys.argv[2], 'python_child'):
    render._run_stage_cli(sys.argv[3], [sys.argv[1], sys.argv[2]], 'probe')
"""

NATIVE_CHILD = """import json, os, sys
sys.path.insert(0, sys.argv[1])
from stage_timing import stage_span
root, output = sys.argv[2], sys.argv[3]
with stage_span(root, 'native_child_TEST'):
    names = sorted(os.environ)
    lineage = {name: os.environ[name] for name in names if name.startswith('SNIPER_TIMING_')}
    with open(os.path.join(root, 'child-environment.json'), 'w') as handle:
        json.dump({'names': names, 'lineage': lineage}, handle)
with open(output, 'w') as handle:
    handle.write('TEST child result, not media')
"""
LAUNCH_LINEAGE = {
    "SNIPER_TIMING_RUN_ID": "launch-run", "SNIPER_TIMING_ATTEMPT_ID": "launch-attempt",
    "SNIPER_TIMING_ATTEMPT_NO": "4", "SNIPER_TIMING_PARENT_SPAN_ID": "outer-parent",
    "SNIPER_TIMING_TASK_ID": "task-clip-3", "SNIPER_TIMING_CLAIM_EPOCH": "7",
    "SNIPER_TIMING_HOST_TURN_ID": "turn-TEST-1",
}
# PYTHONDONTWRITEBYTECODE keeps the owner's Python child in this TEST closed environment from writing bytecode
# into the checkout (FOLLOWUP-C6 item 5; X154). It is an ordinary closed-environment entry, forwarded as-is.
CLOSED = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "TMPDIR": "/private/tmp", "PYTHONDONTWRITEBYTECODE": "1",
          "SNIPER_TIMING_PARENT_SPAN_ID": "stale-config-parent", "SNIPER_TIMING_TASK_ID": "stale-task"}


class NativeLaunchLineageTests(unittest.TestCase):
    """A real sandboxed TEST child through the pipeline owner; never a render or media tool."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="native-launch-lineage-")
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name).resolve()
        self.project, self.root, runtime = base / "project", base / "attempt", base / "runtime"
        for directory in (self.project, self.root, runtime / "dist"):
            directory.mkdir(parents=True)
        (runtime / "dist/cli.js").write_text("TEST executable fixture, never run")
        self.request = {"project": str(self.project), "output": str(self.root),
                        "runtime": str(runtime), "pins": {}}
        (self.root / "export-request.json").write_text(json.dumps(self.request))
        secrets = {"UNRELATED_API_KEY": "TEST-NOT-A-SECRET", "ANTHROPIC_API_KEY": "TEST-NOT-A-SECRET"}
        self.enterContext(mock.patch.dict(os.environ, {**LAUNCH_LINEAGE, **secrets}))
        budgets = base / "production-budgets"
        self.enterContext(mock.patch.object(native_budget_store, "default_root", return_value=budgets))
        self.enterContext(mock.patch.object(native_budget_owner, "default_root", return_value=budgets))
        self.enterContext(mock.patch.object(native_work_lease, "state_root", return_value=base / "pool"))
        self.enterContext(mock.patch("studio.native_run.NativeWorkLease.acquire",
                                     return_value=pool_lease_double()))
        snapshot = parse_snapshot(raw_sample(), ProcessRequest(), 40 * GIB)
        self.enterContext(mock.patch("studio.native_measurement_retry.read_snapshot", return_value=snapshot))
        self.enterContext(mock.patch("studio.native_run.NativeRun.sample"))  # sampling: native resource tests

    def test_pipeline_owner_child_links_to_its_owner_span_with_only_allowlisted_lineage(self) -> None:
        output = self.root / "child-result.json"
        child = [sys.executable, "-c", NATIVE_CHILD, PRODUCER, str(self.root), str(output)]
        pipeline = NativeShortPipeline(self.request, dict(CLOSED))
        spawn = mock.Mock(wraps=subprocess.Popen)  # the real launch, observed
        with contextlib.redirect_stdout(io.StringIO()), mock.patch("studio.native_run.subprocess.Popen", spawn):
            pipeline.supervise("TEST", child, output.name, "TEST-child-complete")
        expected = {name for name in CLOSED if name not in LINEAGE_VARIABLES} | LINEAGE_VARIABLES
        launches = [call for call in spawn.call_args_list  # the process-table probe also spawns
                    if call.args[0][:2] == ["/usr/bin/sandbox-exec", "-f"]]
        self.assertEqual(len(launches), 1)
        self.assertEqual(set(launches[0].kwargs["env"]), expected)
        observed = json.loads((self.root / "child-environment.json").read_text())
        # macOS CoreFoundation sets this inside the child at startup; it is never inherited.
        self.assertEqual(set(observed["names"]) - {"__CF_USER_TEXT_ENCODING"}, expected)
        self.assertNotIn("UNRELATED_API_KEY", observed["names"])
        rows = [json.loads(line) for line in (self.root / "stage_timings.jsonl").read_text().splitlines()]
        starts = {row["stage"]: row for row in rows if row["event"] == "start"}
        owner, child_row = starts["native_owner_TEST"], starts["native_child_TEST"]
        self.assertEqual(owner["parentSpanId"], "outer-parent")
        self.assertEqual(child_row["parentSpanId"], owner["spanId"])
        self.assertEqual(observed["lineage"]["SNIPER_TIMING_PARENT_SPAN_ID"], owner["spanId"])
        self.assertNotEqual(child_row["writerId"], owner["writerId"])
        lineage = ("runId", "attemptId", "attemptNo", "taskId", "claimEpoch", "hostTurnId")
        self.assertEqual({key: child_row[key] for key in lineage},
                         {"runId": "launch-run", "attemptId": "launch-attempt", "attemptNo": 4,
                          "taskId": "task-clip-3", "claimEpoch": 7, "hostTurnId": "turn-TEST-1"})
        for stage, activity in (("native_queue_admission", "native-queue-wait"),
                                ("native_pressure_admission", "pressure-wait")):
            self.assertEqual(starts[stage]["parentSpanId"], owner["spanId"])
            self.assertEqual(starts[stage]["metadata"], {"activity": activity})
        report = summarize_timings(rows)
        self.assertTrue(report["allRecordedSpansPaired"], report["issues"])
        categories = report["attribution"]["categories"]
        self.assertEqual(categories["nativeQueueWaiting"]["status"], "measured")
        self.assertEqual(categories["pressureWaiting"]["status"], "measured")
        self.assertEqual(categories["modelExecution"]["status"], "unknown")
        self.assertEqual(pipeline.stages[0]["status"], "TEST-child-complete")

    def test_launch_environment_replaces_stale_lineage_and_adds_nothing_else(self) -> None:
        with mock.patch.dict(os.environ, {"SNIPER_TIMING_TASK_ID": "bad id with spaces"}):
            forwarded = launch_environment(dict(CLOSED))
            self.assertEqual(set(forwarded), (set(CLOSED) - LINEAGE_VARIABLES) | set(lineage_environment()))
        self.assertEqual(forwarded["PATH"], CLOSED["PATH"])
        self.assertEqual(forwarded["PYTHONDONTWRITEBYTECODE"], "1")   # FOLLOWUP-C6 item 5 (X180 m8): no bytecode
        self.assertEqual(forwarded["SNIPER_TIMING_PARENT_SPAN_ID"], "outer-parent")
        self.assertNotIn("SNIPER_TIMING_TASK_ID", forwarded, "a rejected task id is not forwarded")
        for orphan in ("SNIPER_TIMING_CLAIM_EPOCH", "SNIPER_TIMING_HOST_TURN_ID"):
            self.assertNotIn(orphan, forwarded, "an epoch or turn without its task is never forwarded")
        self.assertNotIn("UNRELATED_API_KEY", forwarded)
        with mock.patch.dict(os.environ, {"SNIPER_TIMING_PARENT_SPAN_ID": "", "SNIPER_TIMING_TASK_ID": ""}):
            bare = launch_environment(dict(CLOSED))
        self.assertNotIn("SNIPER_TIMING_PARENT_SPAN_ID", bare, "no open span: stale config parent removed")
        self.assertNotIn("SNIPER_TIMING_TASK_ID", bare)


class TimingPropagationTests(unittest.TestCase):
    """Real no-media children plus injected subprocess seams; never run FFmpeg or AI."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="timing-propagation-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        patch = mock.patch.dict(os.environ, {
            "SNIPER_TIMING_RUN_ID": "lineage-run",
            "SNIPER_TIMING_ATTEMPT_ID": "resumed-attempt",
            "SNIPER_TIMING_ATTEMPT_NO": "3",
            "SNIPER_TIMING_PARENT_SPAN_ID": "outer-ts-parent",
            "TIMING_PROPAGATION_SENTINEL": "preserve-me",
        })
        patch.start()
        self.addCleanup(patch.stop)
        self.initial = dict(os.environ)

    def assert_environment(self, environment: dict, parent: str | None) -> None:
        self.assertEqual(environment["SNIPER_TIMING_RUN_ID"], "lineage-run")
        self.assertEqual(environment["SNIPER_TIMING_ATTEMPT_ID"], "resumed-attempt")
        self.assertEqual(environment["SNIPER_TIMING_ATTEMPT_NO"], "3")
        self.assertEqual(environment["SNIPER_TIMING_PARENT_SPAN_ID"], parent)
        self.assertEqual(environment["TIMING_PROPAGATION_SENTINEL"], "preserve-me")
        self.assertEqual(dict(os.environ), self.initial)

    def read_rows(self) -> list[dict]:
        return [json.loads(line) for line in
                (self.root / "stage_timings.jsonl").read_text().splitlines()]

    def test_graph_bridge_and_render_sibling_keep_three_process_lineage(self) -> None:
        leaf = self.root / "leaf.py"
        leaf.write_text(LEAF)
        command = (sys.executable, "-c", CHILD, PRODUCER, str(self.root), str(leaf))
        with stage_span(str(self.root), "graph_parent"):
            with contextlib.redirect_stdout(io.StringIO()):
                code, events = graph_cli._run_child(SimpleNamespace(command=command, phase="render"))
        self.assertEqual(code, 0)
        self.assertEqual(events, [{"status": "stage_done", "stage": "probe"}])
        starts = {row["stage"]: row for row in self.read_rows() if row["event"] == "start"}
        self.assertEqual(starts["python_child"]["parentSpanId"], starts["graph_parent"]["spanId"])
        self.assertEqual(starts["grandchild"]["parentSpanId"], starts["python_child"]["spanId"])
        self.assertEqual(len({row["writerId"] for row in starts.values()}), 3)
        for row in starts.values():
            self.assertEqual((row["runId"], row["attemptId"], row["attemptNo"]),
                             ("lineage-run", "resumed-attempt", 3))
        self.assertEqual(dict(os.environ), self.initial)

    def test_base_rebuild_passes_parent_and_preserves_nonzero_failure(self) -> None:
        manifest = self.root / "manifest.json"
        manifest.write_text("{}")
        process = SimpleNamespace(stdout=[], wait=lambda: 1)
        with mock.patch.object(assemble, "_settle_audio_intent"), \
                mock.patch.object(assemble, "_base_state", return_value="missing"), \
                mock.patch.object(assemble.subprocess, "Popen", return_value=process) as spawn:
            with stage_span(str(self.root), "base_check"), contextlib.redirect_stdout(io.StringIO()):
                parent = PARENT_SPAN.get()
                with self.assertRaisesRegex(RuntimeError, "base rebuild failed"):
                    assemble.ensure_base(str(self.root / "base.mp4"),
                                         str(self.root / "plan.json"), {}, None, str(manifest))
        command = spawn.call_args.args[0]
        self.assertEqual(command[0], sys.executable)
        self.assertTrue(command[1].endswith("render.py"))
        self.assertEqual(command[-5:], ["--skip-graphics", "--approval-dir", str(self.root),
                                        "--audio-clock-policy", "legacy-v1"])
        self.assertEqual(spawn.call_args.kwargs["stderr"], subprocess.DEVNULL)
        self.assert_environment(spawn.call_args.kwargs["env"], parent)

    def test_render_audit_inherits_audit_span_and_existing_pythonpath(self) -> None:
        result = subprocess.CompletedProcess([], 0, '{"overall":"pass","failed":0}', "")
        ctx = render.RenderCtx({}, {}, str(self.root), str(self.root))
        with mock.patch.object(render.subprocess, "run", return_value=result) as spawn:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(render.audit_stage(ctx)["overall"], "pass")
        audit = next(row for row in self.read_rows() if row["event"] == "start")
        environment = spawn.call_args.kwargs["env"]
        self.assert_environment(environment, audit["spanId"])
        self.assertEqual(environment["PYTHONPATH"],
                         render.SCRIPT_DIR + os.pathsep + self.initial.get("PYTHONPATH", ""))
        self.assertTrue(spawn.call_args.args[0][1].endswith("audit/audit_render.py"))

    def test_draft_render_inherits_context_without_changing_draft_authority_flags(self) -> None:
        job = draft_render.DraftJob("plan.json", "manifest.json", str(self.root))
        process = SimpleNamespace(stdout=[], wait=lambda: 0)
        with mock.patch.object(draft_render.subprocess, "Popen", return_value=process) as spawn:
            with stage_span(str(self.root), "draft_parent"), contextlib.redirect_stdout(io.StringIO()):
                parent = PARENT_SPAN.get()
                draft_render.run_base_render(job)
        self.assertEqual(spawn.call_args.args[0][-4:],
                         ["--approval-dir", str(self.root), "--draft-only", "--no-audit"])
        self.assert_environment(spawn.call_args.kwargs["env"], parent)

    def test_studio_sync_and_assemble_keep_parent_and_do_not_mutate_environment(self) -> None:
        paths = studio_review.ProducerPaths(str(self.root))
        result = subprocess.CompletedProcess([], 0)
        with mock.patch.object(studio_review.subprocess, "run", return_value=result) as spawn:
            with stage_span(str(self.root), "studio_parent"):
                parent = PARENT_SPAN.get()
                self.assertEqual(studio_review.cmd_sync(paths, apply=True, assemble=True), 0)
        self.assertEqual(spawn.call_count, 2)
        self.assertEqual(spawn.call_args_list[0].args[0][0], sys.executable)
        self.assertIn("--apply", spawn.call_args_list[0].args[0])
        self.assertEqual(spawn.call_args_list[1].args[0], studio_review._assemble_args(paths))
        for call in spawn.call_args_list:
            self.assertIs(call.kwargs["check"], False)
            self.assert_environment(call.kwargs["env"], parent)


if __name__ == "__main__":
    unittest.main(verbosity=2)
