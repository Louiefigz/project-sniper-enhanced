"""The package test gate tolerates only declared tests failing on withheld paths."""
from __future__ import annotations

import unittest
from pathlib import Path

from release.package_selftest import classify

APP = Path("/pkg/app")
WITHHELD = {"docs/producer/command-driven-editing/contracts/p4-live-exit-closure-v1.json", "templates/motion/container"}


def row(test_id: str, outcome: str, missing: str | None = None, text: str = "") -> dict:
    detail = text + (f"FileNotFoundError: [Errno 2] No such file or directory: '{missing}'" if missing else "")
    return {"id": test_id, "outcome": outcome, "detail": detail}


class PackageSelftestGateTests(unittest.TestCase):
    def test_declared_test_failing_on_a_withheld_file_is_tolerated(self) -> None:
        result = classify([row("test_x.A.test_ok", "pass"),
                           row("test_p4_exit_closure_artifact.P.t", "error",
                               "/pkg/app/docs/producer/command-driven-editing/contracts/p4-live-exit-closure-v1.json"),
                           row("test_render_layout_transport.L.t", "error",
                               "/pkg/app/templates/motion/container/layout_observer_browser.mjs")], APP, WITHHELD)
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["toleratedWithheldEvidence"]), 2)

    def test_declared_test_failing_for_another_reason_fails_the_gate(self) -> None:
        result = classify([row("test_x.A.test_ok", "pass"),
                           row("test_p4_exit_closure_artifact.P.t", "fail", text="AssertionError: stale")], APP, WITHHELD)
        self.assertFalse(result["passed"])

    def test_declared_test_missing_a_shipped_file_fails_the_gate(self) -> None:
        result = classify([row("test_x.A.test_ok", "pass"),
                           row("test_p4_exit_closure_artifact.P.t", "error", "/pkg/app/scripts/producer/render.py")],
                          APP, WITHHELD)
        self.assertFalse(result["passed"])

    def test_undeclared_failure_fails_the_gate_even_on_a_withheld_path(self) -> None:
        result = classify([row("test_x.A.test_ok", "pass"),
                           row("test_ingest_admission.I.t", "error",
                               "/pkg/app/docs/producer/command-driven-editing/contracts/p4-live-exit-closure-v1.json")],
                          APP, WITHHELD)
        self.assertFalse(result["passed"])
        self.assertEqual(result["gateFailures"][0]["id"], "test_ingest_admission.I.t")


if __name__ == "__main__":
    unittest.main()
