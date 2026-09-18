"""Pinned negative runtime health checks must not become quality approval."""
from __future__ import annotations

import subprocess
import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from headless import container_policy, container_renderer
from headless.render_log_guard import CLI_PATH, CLI_SHA256, MAX_LOG_BYTES, RenderLogGuard, require_supported_cli

READY = b"[initSession:screenshot] pollHfReady complete (150ms)\n"
DONE = READY + b"[initSession:screenshot] pollSubCompositionTimelines complete (ready) (160ms)\n"


def _test_approval() -> dict:
    """Synthetic marker-policy input only, never an actual image attestation."""
    return {"probedClosure": {"hyperframesVersion": "0.8.31", "sha256": {CLI_PATH: CLI_SHA256}}}


class RenderLogGuardTests(unittest.TestCase):
    def test_known_fatal_indicators_fail_even_with_success_markers(self) -> None:
        errors = (b"[Browser:PAGEERROR] missing icon", b"[FileServer] 404 Not Found: /icons/youtube.svg",
                  b"[Browser:HTTP500] asset", b"[non-blocking] Failed to load resource",
                  b"[FrameCapture] Sub-composition timelines not registered after45000ms")
        for error in errors:
            with self.subTest(error=error), self.assertRaisesRegex(RuntimeError, "health failed"):
                RenderLogGuard().observe(DONE + error, 1, finished=True)

    def test_missing_timeline_stops_after_five_seconds_not_forty_five(self) -> None:
        guard = RenderLogGuard()
        guard.observe(READY, 10)
        with self.assertRaisesRegex(RuntimeError, "within5 seconds"):
            guard.observe(READY, 15)

    def test_new_runtime_failed_timeline_outcome_is_not_ready(self) -> None:
        """Actual 0.8.31 outcome text must fail before a process can finish."""
        for outcome in (b"timeout", b"script_failure"):
            log = READY + b"[initSession:screenshot] pollSubCompositionTimelines complete (" + outcome + b") (160ms)\n"
            with self.subTest(outcome=outcome), self.assertRaisesRegex(RuntimeError, "health failed"):
                RenderLogGuard().observe(log, 1)

    def test_only_explicit_ready_outcome_completes_runtime_readiness(self) -> None:
        """Missing, unknown and legacy outcomes cannot borrow success spelling."""
        for suffix in (b"", b" (160ms)", b" (unknown)", b" (ready-ish)"):
            log = READY + b"[initSession:screenshot] pollSubCompositionTimelines complete" + suffix
            with self.subTest(suffix=suffix), self.assertRaisesRegex(RuntimeError, "readiness"):
                RenderLogGuard().observe(log, 1, finished=True)
        for mode in (b"screenshot", b"beginframe"):
            RenderLogGuard().observe(DONE.replace(b"screenshot", mode), 1, finished=True)

    def test_no_diagnostics_or_incomplete_timeline_cannot_promote_success(self) -> None:
        for value in (b"", READY, b"[initSession:unknown] pollHfReady complete"):
            with self.subTest(value=value), self.assertRaisesRegex(RuntimeError, "readiness"):
                RenderLogGuard().observe(value, 1, finished=True)

    def test_full_append_only_log_catches_error_outside_last_four_kilobytes(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "PAGEERROR"):
            RenderLogGuard().observe(b"[Browser:PAGEERROR] early\n" + b"x" * 8192 + DONE, 1, True)
        guard = RenderLogGuard()
        guard.observe(READY, 1)
        with self.assertRaisesRegex(RuntimeError, "truncated"):
            guard.observe(b"changed", 2)

    def test_partial_utf8_can_complete_but_invalid_or_overlong_logs_fail(self) -> None:
        guard = RenderLogGuard()
        guard.observe(DONE + b"\xf0\x9f", 1)
        guard.observe(DONE + "😀".encode(), 2, finished=True)
        with self.assertRaises(UnicodeDecodeError):
            RenderLogGuard().observe(DONE + b"\xff", 1, finished=True)
        with self.assertRaisesRegex(RuntimeError, "overflowed"):
            RenderLogGuard().observe(b"x" * (MAX_LOG_BYTES + 1), 1)

    def test_guard_requires_exact_audited_cli_identity(self) -> None:
        """Both literal version and exact actual installed source bytes matter."""
        require_supported_cli(_test_approval())
        for version, digest in (("0.7.33", CLI_SHA256), ("0.8.31", "a" * 64), ("0.8.32", CLI_SHA256)):
            value = {"probedClosure": {"hyperframesVersion": version, "sha256": {CLI_PATH: digest}}}
            with self.subTest(version=version, digest=digest), self.assertRaisesRegex(RuntimeError, "audited"):
                require_supported_cli(value)

    def test_runtime_pins_and_readiness_markers_match_actual_installed_cli(self) -> None:
        """Read bytes only: no CLI import, browser or actual image approval."""
        from headless.render_layout_contract import CLI_SHA256 as layout_sha
        package = Path(__file__).resolve().parents[3] / "templates/motion/node_modules/hyperframes"
        raw = (package / "dist/cli.js").read_bytes()
        self.assertEqual(json.loads((package / "package.json").read_bytes())["version"], "0.8.31")
        self.assertEqual(hashlib.sha256(raw).hexdigest(), CLI_SHA256)
        self.assertEqual(layout_sha, CLI_SHA256)
        self.assertIn(b'logInitPhase("pollHfReady complete")', raw)
        self.assertIn(b'logInitPhase(`pollSubCompositionTimelines complete (${session.subTimelineWaitOutcome})`)', raw)

    def test_zero_exit_with_page_error_never_streams_output(self) -> None:
        runtime = container_policy.DockerRuntime("/docker", "/socket", "image", "501:20", _test_approval())
        status = subprocess.CompletedProcess([], 0, "0\n", "")
        with patch.object(container_policy, "_exec_cat", return_value=status), \
                patch.object(container_policy, "read_render_log", return_value=DONE + b"[Browser:PAGEERROR] asset"), \
                patch.object(container_policy, "_stream_output") as stream, self.assertRaisesRegex(RuntimeError, "health failed"):
            container_policy.wait_and_copy(runtime, "/config", "owned-container", "/output")
        stream.assert_not_called()

    def test_health_policy_bytes_invalidate_container_cache_identity(self) -> None:
        runtime = container_policy.DockerRuntime("/bin/true", "/socket", "image", "501:20", container_policy._read_approval())
        outputs = []
        for guard_hash in ("before", "after"):
            with patch.object(container_renderer, "required_runtime", return_value=runtime), \
                    patch.object(container_renderer, "daemon_identity", return_value={}), \
                    patch.object(container_renderer, "file_sha256", side_effect=lambda path: guard_hash if str(path).endswith("render_log_guard.py") else "same"), \
                    patch.dict("os.environ", {"SNIPER_PROOF_FFMPEG_PATH": "/usr/bin/true", "SNIPER_PROOF_FFPROBE_PATH": "/usr/bin/true"}):
                outputs.append(json.loads(container_renderer.cache_identity("/inert")))
        self.assertEqual(outputs[0]["digests"]["renderLogHealthPolicy"], "before")
        self.assertEqual(outputs[1]["digests"]["renderLogHealthPolicy"], "after")
        self.assertNotEqual(outputs[0], outputs[1])


if __name__ == "__main__":
    unittest.main()
