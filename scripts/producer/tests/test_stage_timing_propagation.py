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
from stage_timing import stage_span
from stage_timing_context import PARENT_SPAN
from studio import studio_review

PRODUCER = str(Path(__file__).resolve().parents[1])
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
                code, events = graph_cli._run_child(SimpleNamespace(command=command))
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
        self.assertEqual(command[-3:], ["--skip-graphics", "--approval-dir", str(self.root)])
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
        self.assertEqual(spawn.call_args.args[0][-3:], ["--approval-dir", str(self.root), "--no-audit"])
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
