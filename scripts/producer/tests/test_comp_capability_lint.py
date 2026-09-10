"""Static official lint with owned TEST HTML and bounded process leaves only."""
from __future__ import annotations

import copy
import json
import os
import subprocess
import tempfile
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from graphics import comp_capability_lint as lint
from graphics import comp_capability_refresh as refresh
from headless.process_runner import ProcessDeadlineError, ProcessOutputLimitError

_HTML = '''<!doctype html><html><head><style>body{margin:0;background:#000}</style>
<script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.14.2/gsap.min.js"></script></head>
<body><div data-composition-id="test-one" data-width="1920" data-height="1080" data-duration="1">
<div id="box">TEST ONLY</div></div><script>window.__timelines={};
const tl=gsap.timeline({paused:true}); tl.set('#box',{opacity:0},0);
tl.to('#box',{opacity:1,duration:1},0); window.__timelines['test-one']=tl;
</script></body></html>'''


class RootLintTests(unittest.TestCase):
    """No HTML JavaScript execution, decoder, renderer, or network admission."""

    def setUp(self) -> None:
        """Use exact owned TEMP entries and actual installed official validator."""
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        temporary = self.stack.enter_context(tempfile.TemporaryDirectory(prefix="root-lint-test-", dir="/private/tmp"))
        self.root = Path(temporary)
        self.motion = self.root / "motion"
        (self.motion / "compositions").mkdir(parents=True)
        self.entry = self.motion / "compositions/test-one.html"
        self.entry.write_text(_HTML)
        self.stack.enter_context(patch.dict(os.environ, {"SNIPER_NODE_PATH": "/opt/homebrew/bin/node", "SECRET_TEST": "must-not-inherit"}))
        self.stack.enter_context(patch.object(lint, "MOTION_DIR", str(self.motion)))
        self.stack.enter_context(patch.object(lint, "_motion_paths", return_value=[self.entry]))
        self.stack.enter_context(patch.object(lint, "composition_paths", return_value=[str(self.entry)]))
        self.stack.enter_context(patch.object(lint, "current_source_digest", side_effect=lambda: lint.file_hash(self.entry)))

    def execute(self) -> dict:
        """Use one original allowance for this static-only engineering test."""
        return lint.preflight_root_lint(self.root, time.monotonic() + 30)

    def test_actual_official_warning_is_retained_without_blocking(self) -> None:
        """Warnings have the same upstream render gate as ordinary strict rendering."""
        value = self.execute()
        self.assertTrue(value["passed"])
        result = value["result"]
        self.assertFalse(result["blocked"])
        self.assertEqual(result["deniedAttempts"], [])
        findings = result["rows"][0]["result"]["results"][0]["result"]["findings"]
        self.assertIn("gsap_timeline_set_initial_hide", [row["code"] for row in findings])

    def test_actual_missing_registry_refuses_and_keeps_exact_diagnostics(self) -> None:
        """Do not duplicate or waive the official HTML-root registry rule."""
        self.entry.write_text(_HTML.replace("window.__timelines", "window.testRegistry"))
        with self.assertRaisesRegex(RuntimeError, "strict errors"):
            self.execute()
        process = json.loads((self.root / "root-lint/process.json").read_text())
        self.assertIn("missing_timeline_registry", process["stdout"])
        self.assertFalse(json.loads((self.root / "root-lint/failure.json").read_text())["passed"])

    def test_environment_and_subprocess_bounds_are_closed(self) -> None:
        """Use actual Node but no inherited tokens, proxy, socket, or loaders."""
        actual = lint.run_text
        def observed(request: lint.ProcessRequest) -> subprocess.CompletedProcess:
            """Observe the genuine owned request without replacing execution."""
            self.assertNotIn("SECRET_TEST", request.environment)
            self.assertNotIn("HOME", request.environment)
            self.assertEqual(request.command[0], os.path.realpath("/opt/homebrew/bin/node"))
            self.assertEqual(request.stdin_text, "")
            self.assertEqual(request.max_output_bytes, 4 * 1024 * 1024)
            self.assertLessEqual(request.timeout_seconds, 30)
            return actual(request)
        with patch.object(lint, "run_text", side_effect=observed):
            self.execute()

    def test_expired_original_deadline_refuses_before_process(self) -> None:
        """The preflight cannot replace an already expired cohort allowance."""
        with patch.object(lint, "run_text") as run:
            with self.assertRaisesRegex(RuntimeError, "deadline"):
                lint.preflight_root_lint(self.root, time.monotonic() - 1)
        run.assert_not_called()

    def test_output_limit_and_timeout_refuse_without_a_render(self) -> None:
        """The shared owned runner's failures remain failures with retained facts."""
        for error in (ProcessDeadlineError("TEST deadline"), ProcessOutputLimitError("TEST output")):
            directory = self.root / type(error).__name__
            directory.mkdir()
            with patch.object(lint, "run_text", side_effect=error), self.assertRaises(type(error)):
                lint.preflight_root_lint(directory, time.monotonic() + 30)
            self.assertFalse(json.loads((directory / "root-lint/failure.json").read_text())["passed"])

    def test_original_entry_same_bytes_new_inode_after_lint_refuses(self) -> None:
        """Only the exact owned TEST input is replaced; no repository mutation."""
        actual = lint.run_text
        before = self.entry.stat().st_ino
        def changed(request: lint.ProcessRequest) -> subprocess.CompletedProcess:
            """Replace only this TEST entry after actual static lint has returned."""
            result = actual(request)
            replacement = self.entry.with_suffix(".replacement")
            replacement.write_bytes(self.entry.read_bytes())
            replacement.replace(self.entry)
            return result
        with patch.object(lint, "run_text", side_effect=changed), self.assertRaisesRegex(RuntimeError, "changed"):
            self.execute()
        self.assertNotEqual(before, self.entry.stat().st_ino)

    def test_last_diagnostic_write_is_charged_to_original_deadline(self) -> None:
        """A final publication cannot return success after the original bound."""
        actual = lint.write_new
        clock = [1000.0]
        def delayed(path: Path, value: dict) -> None:
            """Advance only the original TEST clock after actual diagnostic write."""
            actual(path, value)
            if path.name == "result.json":
                clock[0] = 1031.0
        with patch.object(lint.time, "monotonic", side_effect=lambda: clock[0]), patch.object(lint, "write_new", side_effect=delayed):
            with self.assertRaisesRegex(RuntimeError, "deadline"):
                lint.preflight_root_lint(self.root, 1030.0)
        self.assertFalse(json.loads((self.root / "root-lint/failure.json").read_text())["passed"])

    def test_malformed_version_counts_inventory_and_duplicate_keys_refuse(self) -> None:
        """Faults modify only the returned structured TEST process text."""
        value = self.execute()["result"]
        entries = [{key: row[key] for key in ("kind", "path", "sha256")} for row in value["rows"]]
        for key, invalid in (("schemaVersion", True), ("blocked", 0), ("deniedAttempts", ["fetch"]), ("rows", [])):
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                lint._result(json.dumps({**value, key: invalid}), value["requestSha256"], entries)
        changed = copy.deepcopy(value)
        changed["rows"][0]["result"]["totalWarnings"] += 1
        with self.assertRaisesRegex(RuntimeError, "counts"):
            lint._result(json.dumps(changed), value["requestSha256"], entries)
        with self.assertRaisesRegex(RuntimeError, "duplicate"):
            lint._result('{"schemaVersion":1,' + json.dumps(value)[1:], value["requestSha256"], entries)

    def test_actual_official_video_probe_attempt_is_denied_even_when_swallowed(self) -> None:
        """The upstream optional ffprobe branch cannot invoke a local decoder."""
        (self.motion / "owned.mp4").write_bytes(b"TEST inert bytes, not media")
        self.entry.write_text(_HTML.replace("TEST ONLY", 'TEST ONLY<video src="/owned.mp4"></video>'))
        with self.assertRaisesRegex(RuntimeError, "forbidden"):
            self.execute()
        process = json.loads((self.root / "root-lint/process.json").read_text())
        result = json.loads(process["stdout"])
        self.assertIn("child_process.execFile", result["deniedAttempts"])

    def fake_package(self, code: str) -> Path:
        """TEST-only package leaf probes process policy, never validator success."""
        package = self.root / "packages/lint"
        (package / "dist").mkdir(parents=True)
        (package.parent / "parsers").mkdir()
        (package.parent / "parsers/package.json").write_text('{"version":"0.8.31"}')
        (package / "package.json").write_text(json.dumps({"name": "@hyperframes/lint", "version": "0.8.31",
            "type": "module", "exports": {".": {"import": "./dist/index.js"}}}))
        (package / "dist/index.js").write_text(code)
        return package

    def test_network_attempt_fails_before_any_connection(self) -> None:
        """Only a TEST module calls global fetch; the installed linter does not."""
        package = self.fake_package('export async function lintProject(){await fetch("https://example.invalid");}')
        with patch.object(lint, "_PACKAGE", package), self.assertRaises((RuntimeError, ValueError)):
            self.execute()
        process = json.loads((self.root / "root-lint/process.json").read_text())
        self.assertIn('"deniedAttempts":["fetch"]', process["stderr"])
        self.assertNotEqual(process["returncode"], 0)

    def test_actual_owned_node_hang_is_timed_out_and_reaped(self) -> None:
        """A TEST import loop exercises the existing runner's real hard deadline."""
        package = self.fake_package('while (true) {}')
        with patch.object(lint, "_PACKAGE", package), patch.object(lint, "MAX_SECONDS", 0.1):
            with self.assertRaises(ProcessDeadlineError):
                self.execute()
        self.assertFalse(json.loads((self.root / "root-lint/failure.json").read_text())["passed"])

    def test_final_diagnostic_callback_cannot_replace_original_input(self) -> None:
        """Only an exact canonical TEST input is changed after result publication."""
        actual = lint.write_new
        def changed(path: Path, value: dict) -> None:
            """Fault only the original TEMP input at the final publication seam."""
            actual(path, value)
            if path.name == "result.json":
                replacement = self.entry.with_suffix(".replacement")
                replacement.write_bytes(self.entry.read_bytes())
                replacement.replace(self.entry)
        with patch.object(lint, "write_new", side_effect=changed), self.assertRaisesRegex(RuntimeError, "changed"):
            self.execute()
        self.assertFalse(json.loads((self.root / "root-lint/failure.json").read_text())["passed"])

    def test_aggregate_and_inventory_bounds_refuse_before_hashing(self) -> None:
        """Oversized declared TEST inventory cannot start any payload read."""
        with patch.object(lint, "file_hash") as hashed:
            with self.assertRaisesRegex(RuntimeError, "aggregate"):
                lint._files({self.entry}, maximum=1)
            with self.assertRaisesRegex(RuntimeError, "512"):
                lint._files({self.root / f"unopened-{index}" for index in range(513)})
        hashed.assert_not_called()

    def test_official_package_version_mix_refuses_before_node(self) -> None:
        """A new caller cannot mix validator and parser package versions."""
        package = self.fake_package('export function lintProject(){}')
        (package.parent / "parsers/package.json").write_text('{"version":"0.8.30"}')
        with patch.object(lint, "_PACKAGE", package), patch.object(lint, "run_text") as run:
            with self.assertRaisesRegex(RuntimeError, "package version"):
                self.execute()
        run.assert_not_called()

    def test_refresh_actual_root_error_refuses_before_all_native_preflight(self) -> None:
        """The real official error reaches the coordinator before tools or images."""
        self.entry.write_text(_HTML.replace("window.__timelines", "window.testRegistry"))
        with patch.object(refresh, "_preflight") as tools, patch.object(refresh, "source_state") as sources:
            with patch.object(refresh, "_probe") as render, self.assertRaisesRegex(RuntimeError, "strict errors"):
                refresh.execute(self.root, {"probes": []}, time.monotonic(), False)
        tools.assert_not_called()
        sources.assert_not_called()
        render.assert_not_called()

    def test_refresh_original_elapsed_budget_is_not_restarted(self) -> None:
        """An exhausted original cohort cannot admit even the lint child."""
        with patch.object(refresh, "_preflight") as tools, patch.object(lint, "run_text") as child:
            with self.assertRaisesRegex(RuntimeError, "deadline"):
                refresh.execute(self.root, {"probes": []}, time.monotonic() - 1501, False)
        tools.assert_not_called()
        child.assert_not_called()

    def test_refresh_cannot_rebaseline_original_lint_validator_after_tools(self) -> None:
        """An explicit TEST metadata change between the stages blocks all renders."""
        changed = {"motionSourceDigest": lint.file_hash(self.entry), "rootLintValidator": {"TEST": "changed"}}
        with patch.object(refresh, "_preflight"), patch.object(refresh, "source_state", return_value=changed):
            with patch.object(refresh, "_probe") as render, self.assertRaisesRegex(RuntimeError, "changed before capability"):
                refresh.execute(self.root, {"probes": []}, time.monotonic(), False)
        render.assert_not_called()


if __name__ == "__main__":
    unittest.main()
