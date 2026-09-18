"""Closed CLI dispatch and absent-option legacy behavior; no native calls."""
from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from _source_color_cleanup_execution_fixture import SourceColorCleanupExecutionFixture
import guided_opening_cleanup as cli


class SourceColorCleanupCliTests(unittest.TestCase):
    """Only all three explicit flags select the additive V2 cleanup branch."""

    def arguments(self) -> list[str]:
        """Return inert required legacy arguments without reading any named path."""
        return ["cleanup", "/TEST/input", "/TEST/output", "--input-sha256", "a" * 64,
                "--execution-claim", "/TEST/claim", "--execution-claim-sha256", "b" * 64, "--timeout-seconds", "30"]

    def test_partial_and_unknown_flags_fail_before_cleanup_action(self) -> None:
        """Argparse refuses incomplete opt-in and unknown controls before any action."""
        extras = [["--source-color-reservation", "/TEST/active.json"], ["--source-color-reservation-sha256", "c" * 64],
                  ["--source-color-request-sha256", "d" * 64], ["--processes-stopped", "true"],
                  ["--source-color-reservation", "/TEST/active.json", "--source-color-request-sha256", "d" * 64]]
        for extra in extras:
            with patch.object(cli.sys, "argv", self.arguments() + extra), patch.object(cli, "cleanup") as called, \
                    redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                cli.main()
            self.assertEqual(raised.exception.code, 2)
            called.assert_not_called()

    def test_all_flags_preserve_exact_request_and_original_timeout(self) -> None:
        """CLI dispatch carries complete raw refs and hash, never a settlement boolean."""
        extra = ["--source-color-reservation", "/TEST/.sniper-color-resource/active.json",
                 "--source-color-reservation-sha256", "c" * 64, "--source-color-request-sha256", "d" * 64]
        with patch.object(cli.sys, "argv", self.arguments() + extra), patch.object(cli, "cleanup", return_value={"TEST": True}) as called:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(), 0)
        args = called.call_args.args
        self.assertEqual(args[:3], ((Path("/TEST/input"), Path("/TEST/output")), ("a" * 64, Path("/TEST/claim"), "b" * 64), 30))
        self.assertEqual(vars(args[3]), {"reservation_path": Path("/TEST/.sniper-color-resource/active.json"),
                                       "reservation_sha256": "c" * 64, "source_color_hash": "d" * 64})

    def test_absent_flags_keep_original_three_argument_cleanup_result(self) -> None:
        """The actual legacy metadata path neither imports behavior nor reconciles grades."""
        f = SourceColorCleanupExecutionFixture()
        self.addCleanup(f.close)
        with patch.object(cli, "cleanup_source_color", side_effect=AssertionError("legacy cannot enter V2")):
            result = cli.cleanup(f.paths, f.refs, 30)
        self.assertEqual(result["schemaVersion"], 1)
        self.assertNotIn("sourceColor", result)
        self.assertEqual([row["stage"] for row in result["stages"]], ["cleanup-claim-and-controls", "cleanup-controls-after"])
        self.assertEqual(f.events, [])
        self.assertEqual(list(f.output.iterdir()), [])
        self.assertEqual(f.admission.call_count, 2)

    def test_failure_emits_unknown_not_success_or_cleanup_permission(self) -> None:
        """Original CLI error form is unchanged and never proves resource release."""
        output = io.StringIO()
        with patch.object(cli.sys, "argv", self.arguments()), patch.object(cli, "cleanup", side_effect=RuntimeError("TEST failure")):
            with redirect_stdout(output):
                self.assertEqual(cli.main(), 1)
        self.assertEqual(json.loads(output.getvalue()), {"status": "unknown", "cleanupVerified": False, "error": "TEST failure"})


if __name__ == "__main__":
    unittest.main()
