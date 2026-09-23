"""The package test gate tolerates only declared tests failing on withheld paths,
never reports a failure it did not record, and never reuses an earlier run's result."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from release.package_selftest import Withheld, classify, main

APP = Path("/pkg")
WITHHELD = Withheld(frozenset({"docs/producer/command-driven-editing/contracts/p4-live-exit-closure-v1.json"}),
                    ("templates/motion/container",))


def row(test_id: str, outcome: str, missing: str | None = None, exc_type: str | None = None) -> dict:
    """A recorded outcome; `missing` makes its terminal exception FileNotFoundError for that path."""
    result = {"id": test_id, "outcome": outcome, "detail": ""}
    if missing:
        result["exc"] = {"type": "builtins.FileNotFoundError", "errno": 2, "filename": missing}
    elif exc_type:
        result["exc"] = {"type": exc_type, "errno": None, "filename": None}
    return result


class PackageSelftestGateTests(unittest.TestCase):
    def test_declared_test_failing_on_a_withheld_file_is_tolerated(self) -> None:
        result = classify([row("test_x.A.test_ok", "pass"),
                           row("test_p4_exit_closure_artifact.P.t", "error",
                               "/pkg/docs/producer/command-driven-editing/contracts/p4-live-exit-closure-v1.json"),
                           row("test_render_layout_transport.L.t", "error",
                               "/pkg/templates/motion/container/layout_observer_browser.mjs")], APP, WITHHELD)
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["toleratedWithheldEvidence"]), 2)

    def test_declared_test_failing_for_another_reason_fails_the_gate(self) -> None:
        result = classify([row("test_x.A.test_ok", "pass"),
                           row("test_p4_exit_closure_artifact.P.t", "fail", exc_type="builtins.AssertionError")],
                          APP, WITHHELD)
        self.assertFalse(result["passed"])

    def test_declared_test_missing_a_shipped_file_fails_the_gate(self) -> None:
        result = classify([row("test_x.A.test_ok", "pass"),
                           row("test_p4_exit_closure_artifact.P.t", "error", "/pkg/scripts/producer/render.py")],
                          APP, WITHHELD)
        self.assertFalse(result["passed"])

    def test_a_fixture_error_is_matched_to_its_declared_class(self) -> None:
        result = classify([row("test_x.A.test_ok", "pass"),
                           row("setUpClass (test_p4_exit_closure_artifact.P)", "error",
                               "/pkg/docs/producer/command-driven-editing/contracts/p4-live-exit-closure-v1.json")],
                          APP, WITHHELD)
        self.assertTrue(result["passed"])

    def test_a_failure_text_naming_a_withheld_path_is_not_enough(self) -> None:
        # The old gate matched traceback text; only the structured terminal exception counts now.
        failing = {"id": "test_p4_exit_closure_artifact.P.t", "outcome": "fail",
                   "detail": "FileNotFoundError: [Errno 2] No such file or directory: "
                             "'/pkg/docs/producer/command-driven-editing/contracts/p4-live-exit-closure-v1.json'"
                             "\nDuring handling of the above exception, another exception occurred:\nAssertionError: x",
                   "exc": {"type": "builtins.AssertionError", "errno": None, "filename": None}}
        self.assertFalse(classify([row("test_x.A.test_ok", "pass"), failing], APP, WITHHELD)["passed"])

    def test_undeclared_failure_fails_the_gate_even_on_a_withheld_path(self) -> None:
        result = classify([row("test_x.A.test_ok", "pass"),
                           row("test_ingest_admission.I.t", "error",
                               "/pkg/docs/producer/command-driven-editing/contracts/p4-live-exit-closure-v1.json")],
                          APP, WITHHELD)
        self.assertFalse(result["passed"])
        self.assertEqual(result["gateFailures"][0]["id"], "test_ingest_admission.I.t")


PASSING = "import unittest\nclass A(unittest.TestCase):\n    def test_ok(self): self.assertTrue(True)\n"


class PackageSelftestRunTests(unittest.TestCase):
    """The whole gate against a fake installed package (real runner, fixture interpreters)."""

    def setUp(self) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="sniper-gate-test-"))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.tests = self.base / "scripts/producer/tests"
        self.tests.mkdir(parents=True)
        self.withheld = self.base / "withheld.json"
        self.withheld.write_text("[]")
        self.out = self.base / "result.json"
        # A regular wrapper FILE around this interpreter, never a link to it.
        self._python(f'exec "{sys.executable}" "$@"')

    def _python(self, body: str) -> None:
        python = self.base / ".venv/bin/python3"
        python.parent.mkdir(parents=True, exist_ok=True)
        python.write_text("#!/bin/sh\n" + body + "\n")
        python.chmod(0o755)

    def _gate(self, source: str) -> tuple[int, dict]:
        (self.tests / "test_example.py").write_text(source)
        code = main([str(self.base), "--withheld", str(self.withheld), "--out", str(self.out)])
        return code, json.loads(self.out.read_text())

    def test_a_clean_run_passes(self) -> None:
        code, result = self._gate(PASSING)
        self.assertEqual((code, result["passed"], result["counts"]["pass"]), (0, True, 1))

    def test_a_failed_subtest_fails_the_gate(self) -> None:
        code, result = self._gate(PASSING + "    def test_sub(self):\n        with self.subTest(case='buyer workflow'):\n"
                                  "            self.assertEqual(1, 2)\n")
        self.assertEqual((code, result["passed"]), (1, False))
        self.assertEqual(result["gateFailures"][0]["id"], "test_example.A.test_sub")
        self.assertIn("buyer workflow", result["gateFailures"][0]["subtest"])

    def test_an_errored_subtest_fails_the_gate(self) -> None:
        code, result = self._gate(PASSING + "    def test_sub(self):\n        with self.subTest(n=1):\n"
                                  "            raise KeyError('boom')\n")
        self.assertEqual((code, result["passed"], result["gateFailures"][0]["outcome"]), (1, False, "error"))

    def test_an_unexpected_success_fails_the_gate(self) -> None:
        code, result = self._gate(PASSING + "    @unittest.expectedFailure\n    def test_x(self): pass\n")
        self.assertEqual((code, result["passed"]), (1, False))

    def test_a_crashed_runner_never_reuses_an_earlier_pass(self) -> None:
        self.assertEqual(self._gate(PASSING)[0], 0)  # an earlier passing run with the same --out
        stale = self.base / "result.rows.json"  # the old fixed side file, too
        stale.write_text(json.dumps([{"id": "old.A.test_ok", "outcome": "pass", "detail": ""}]))
        self._python("exit 17")
        code, result = self._gate(PASSING)
        self.assertEqual((code, result["passed"]), (2, False))
        self.assertIn("exited 17", result["infrastructureError"])

    def test_a_truncated_result_fails_the_gate(self) -> None:
        self._python('printf \'{"nonce": \' > "$4"; exit 0')
        code, result = self._gate(PASSING)
        self.assertEqual((code, result["passed"]), (2, False))
        self.assertIn("no readable result", result["infrastructureError"])

    def test_a_result_from_another_run_is_refused(self) -> None:
        foreign = {"nonce": "0" * 32, "complete": True, "rows": [{"id": "x.A.test_ok", "outcome": "pass", "detail": ""}],
                   "summary": {"testsRun": 1, "failures": 0, "errors": 0, "unexpectedSuccesses": 0, "wasSuccessful": True}}
        self._python(f"printf '%s' '{json.dumps(foreign)}' > \"$4\"; exit 0")
        code, result = self._gate(PASSING)
        self.assertEqual((code, result["passed"]), (2, False))
        self.assertIn("not this run", result["infrastructureError"])

    def _declared_artifact_test(self, body: str) -> None:
        withheld = self.base / "docs/withheld.json"  # absent from the fake package, listed as withheld
        self.withheld.write_text(json.dumps([{"path": "docs/withheld.json", "reason": "retained evidence"}]))
        (self.tests / "test_p4_exit_closure_artifact.py").write_text(
            "import unittest\nfrom pathlib import Path\nEVIDENCE = Path(" + repr(str(withheld)) + ")\n"
            "class P(unittest.TestCase):\n" + body)

    def test_missing_withheld_evidence_alone_is_tolerated(self) -> None:
        self._declared_artifact_test("    def test_fresh(self):\n        EVIDENCE.read_text()\n")
        code, result = self._gate(PASSING)
        self.assertEqual((code, result["passed"], len(result["toleratedWithheldEvidence"])), (0, True, 1))

    def test_a_regression_raised_while_handling_missing_evidence_fails_the_gate(self) -> None:
        # The independent review's reproduction: AssertionError after catching FileNotFoundError.
        self._declared_artifact_test("    def test_fresh(self):\n        try:\n            EVIDENCE.read_text()\n"
                                     "        except FileNotFoundError:\n"
                                     "            raise AssertionError('REAL REGRESSION')\n")
        code, result = self._gate(PASSING)
        self.assertEqual((code, result["passed"]), (1, False))
        self.assertEqual(result["toleratedWithheldEvidence"], [])

    def test_a_runtime_error_chained_from_missing_evidence_fails_the_gate(self) -> None:
        self._declared_artifact_test("    def test_fresh(self):\n        try:\n            EVIDENCE.read_text()\n"
                                     "        except FileNotFoundError as error:\n"
                                     "            raise RuntimeError('broken') from error\n")
        self.assertEqual(self._gate(PASSING)[0], 1)

    def test_a_subtest_regression_after_missing_evidence_fails_the_gate(self) -> None:
        self._declared_artifact_test("    def test_fresh(self):\n        with self.subTest(case='x'):\n"
                                     "            try:\n                EVIDENCE.read_text()\n"
                                     "            except FileNotFoundError:\n"
                                     "                self.fail('REAL REGRESSION')\n")
        code, result = self._gate(PASSING)
        self.assertEqual((code, result["passed"]), (1, False))

    def test_a_missing_shipped_file_is_not_excused(self) -> None:
        # Same declared test, but the missing file is not in the withheld manifest.
        self.withheld.write_text("[]")
        (self.tests / "test_p4_exit_closure_artifact.py").write_text(
            "import unittest\nfrom pathlib import Path\nclass P(unittest.TestCase):\n"
            "    def test_fresh(self):\n        Path(" + repr(str(self.base / "scripts/x.py")) + ").read_text()\n")
        self.assertEqual(self._gate(PASSING)[0], 1)

    def test_rows_that_disagree_with_unittest_totals_fail_the_gate(self) -> None:
        summary = {"testsRun": 2, "failures": 1, "errors": 0, "unexpectedSuccesses": 0, "wasSuccessful": False}
        result = classify([row("test_x.A.test_ok", "pass")], APP, WITHHELD, summary)
        self.assertFalse(result["passed"])
        self.assertEqual(result["gateFailures"][0]["id"], "<unittest totals>")


if __name__ == "__main__":
    unittest.main()
