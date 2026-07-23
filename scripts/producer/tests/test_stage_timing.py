"""stage_timing journal tests — append, ordering, concurrency + planVersion bump.

The journal is the dark-time-attribution fix (PLAN_TIME_GEOMETRY_CONTRACT v3
build slot 0): every stage appends START/END NDJSON rows to
``<dir>/stage_timings.jsonl``. Contract under test: rows append (never
truncate), 0600 on create, per-writer ordering survives concurrent appenders,
telemetry failures return False instead of raising, and every plan WRITE path
bumps ``planVersion`` without ever flipping a base fingerprint.
"""
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest

from _common import *  # noqa: F401,F403
import fingerprints as fp
import stage_timing as st
from edit.plan_refit import bump_plan_version

_PRODUCER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _rows(path: str) -> list[dict]:
    """Parse every journal line; a torn/partial line fails the test loudly."""
    return [json.loads(line) for line in _read(path).splitlines() if line.strip()]


class JournalAppendTests(unittest.TestCase):
    """journal_event: shape, permissions, append-only, best-effort."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.journal = st.journal_path(self.tmp.name)

    def test_appends_one_parseable_row(self) -> None:
        self.assertTrue(st.journal_event(self.tmp.name, "cut_speed", "start"))
        rows = _rows(self.journal)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["stage"], "cut_speed")
        self.assertEqual(row["event"], "start")
        self.assertIsInstance(row["ts"], float)
        self.assertIsInstance(row["mono"], float)

    def test_created_0600_and_never_truncated(self) -> None:
        st.journal_event(self.tmp.name, "a", "start")
        mode = stat.S_IMODE(os.stat(self.journal).st_mode)
        self.assertEqual(mode, 0o600)
        first = _read(self.journal)
        st.journal_event(self.tmp.name, "a", "end")
        after = _read(self.journal)
        self.assertTrue(after.startswith(first), "append truncated prior rows")
        self.assertEqual(len(_rows(self.journal)), 2)

    def test_unknown_event_is_loud(self) -> None:
        with self.assertRaises(ValueError):
            st.journal_event(self.tmp.name, "a", "middle")

    def test_unwritable_dir_returns_false_never_raises(self) -> None:
        missing = os.path.join(self.tmp.name, "no", "such", "dir")
        self.assertFalse(st.journal_event(missing, "a", "start"))


class SpanOrderingTests(unittest.TestCase):
    """stage_span: start-before-end ordering, END even on a raising stage."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_span_orders_start_then_end(self) -> None:
        with st.stage_span(self.tmp.name, "graphics"):
            pass
        with st.stage_span(self.tmp.name, "music"):
            pass
        rows = _rows(st.journal_path(self.tmp.name))
        self.assertEqual([(r["stage"], r["event"]) for r in rows],
                         [("graphics", "start"), ("graphics", "end"),
                          ("music", "start"), ("music", "end")])
        monos = [r["mono"] for r in rows]
        self.assertEqual(monos, sorted(monos), "mono must be non-decreasing")

    def test_span_writes_end_when_stage_raises(self) -> None:
        with self.assertRaises(RuntimeError):
            with st.stage_span(self.tmp.name, "master"):
                raise RuntimeError("stage died")
        rows = _rows(st.journal_path(self.tmp.name))
        self.assertEqual([r["event"] for r in rows], ["start", "end"])

    def test_timed_stage_decorator_uses_ctx_out_dir(self) -> None:
        class Ctx:
            out_dir = self.tmp.name

        @st.timed_stage("compile")
        def fake_stage(ctx: Ctx, value: int) -> int:
            return value * 2

        self.assertEqual(fake_stage(Ctx(), 21), 42)
        rows = _rows(st.journal_path(self.tmp.name))
        self.assertEqual([(r["stage"], r["event"]) for r in rows],
                         [("compile", "start"), ("compile", "end")])


class ConcurrentAppendTests(unittest.TestCase):
    """Concurrent writers may interleave rows but never tear a line."""

    def test_parallel_processes_never_tear_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            per_proc, n_procs = 40, 6
            code = ("import sys; sys.path.insert(0, sys.argv[1]); "
                    "import stage_timing as st\n"
                    "for i in range(int(sys.argv[4])):\n"
                    "    st.journal_event(sys.argv[2], sys.argv[3], "
                    "'start' if i % 2 == 0 else 'end')\n")
            procs = [subprocess.Popen(
                [sys.executable, "-c", code, _PRODUCER_DIR, tmp,
                 f"p{index}", str(per_proc)]) for index in range(n_procs)]
            for proc in procs:
                self.assertEqual(proc.wait(), 0)
            rows = _rows(st.journal_path(tmp))   # json.loads fails on torn rows
            self.assertEqual(len(rows), per_proc * n_procs)
            for index in range(n_procs):
                events = [r["event"] for r in rows if r["stage"] == f"p{index}"]
                expected = ["start" if i % 2 == 0 else "end"
                            for i in range(per_proc)]
                self.assertEqual(events, expected,
                                 "per-writer order lost under concurrency")


class PlanVersionBumpTests(unittest.TestCase):
    """Every plan WRITE bumps planVersion; bumps never flip base fingerprints."""

    def test_bump_increments_defaults_and_copies(self) -> None:
        plan = {"planVersion": 3, "cutTrack": []}
        bumped = bump_plan_version(plan)
        self.assertEqual(bumped["planVersion"], 4)
        self.assertEqual(plan["planVersion"], 3, "input must not mutate")
        self.assertEqual(bump_plan_version({})["planVersion"], 1)
        self.assertEqual(bump_plan_version({"planVersion": "junk"})["planVersion"], 1)

    def test_cli_write_does_not_bump_and_fingerprints_ignore_it(self) -> None:
        old = {"planVersion": 2, "target": {"mode": "longform"},
               "cutTrack": [{"sourceId": "raw", "start": 10.0, "end": 50.0}],
               "graphicsTrack": []}
        new = {**old, "cutTrack": [{"sourceId": "raw", "start": 10.0, "end": 25.0},
                                   {"sourceId": "raw", "start": 30.0, "end": 50.0}]}
        with tempfile.TemporaryDirectory() as tmp:
            old_path = os.path.join(tmp, "base_plan.json")
            new_path = os.path.join(tmp, "edit_plan.json")
            with open(old_path, "w") as handle:
                json.dump(old, handle)
            with open(new_path, "w") as handle:
                json.dump(new, handle)
            proc = subprocess.run(
                [sys.executable,
                 os.path.join(_PRODUCER_DIR, "edit", "plan_refit.py"),
                 old_path, new_path, "--write"],
                capture_output=True, text=True, cwd=_PRODUCER_DIR)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            with open(new_path) as handle:
                written = json.load(handle)
        # The CLI must NOT bump: its callers (save-plan cut-only saves,
        # ai-edit finalize) already bumped before staging the refit input —
        # a CLI-side bump double-counted (planVersion 1→3 on one save).
        self.assertEqual(written["planVersion"], 2,
                         "--write must not double-bump; the caller owns it")
        self.assertEqual(fp.base_fingerprint(written),
                         fp.base_fingerprint({**written, "planVersion": 99}),
                         "planVersion must stay excluded from base prints")
        self.assertEqual(fp.plan_content_hash(written),
                         fp.plan_content_hash({**written, "planVersion": 99}),
                         "planVersion must stay excluded from content hash")


if __name__ == "__main__":
    unittest.main(verbosity=2)
