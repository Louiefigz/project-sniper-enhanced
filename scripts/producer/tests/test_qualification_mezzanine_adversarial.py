"""Cancellation, TOCTOU, audio, and cleanup tests for qualification media."""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from headless.external_media_snapshot import MAX_EXTERNAL_MEDIA_BYTES
from headless.qualification_mezzanine_policy import (
    QualificationLaunch,
    _worker_source,
)
from headless.qualification_mezzanine_runtime import (
    _LAUNCH_RECONCILE_SECONDS,
    _LAUNCH_TIMEOUT_SECONDS,
    _container_state,
    _control_plane_timeout,
    _launch,
    _wait_result,
    run_isolated_transcode,
)
from qualification_mezzanine import (
    QualificationRequest,
    QualificationRunners,
    build_qualification_mezzanine,
)
from qualification_mezzanine_files import observe_qualified_output
from qualification_mezzanine_fixture import envelope, runtime, source_fact
from qualification_mezzanine_publish import (
    PublishFile,
    cleanup_attempt,
    close_attempt,
    new_attempt,
    publication_transaction,
    seal_stage_media,
    write_stage,
)


def _request(root: Path) -> QualificationRequest:
    source = root / "source.mp4"
    source.write_bytes(b"host-hash-only")
    return QualificationRequest(
        str(source), str(root / "qualified.mp4"),
        str(root / "qualified.mp4.qualification.json"), 10800, 24)


def _runners(request: QualificationRequest, mutate: str = "") \
        -> QualificationRunners:
    def observe(path: str):
        return source_fact(path)

    def transcode(_source: str, output: str, _timeout: int, _fps: int) -> dict:
        payload = b"qualified-media"
        (Path(output) / "qualified.mp4").write_bytes(payload)
        value = envelope(MAX_EXTERNAL_MEDIA_BYTES + 1, len(payload))
        if mutate == "source-hash":
            value["worker"]["sourceProbe"]["facts"]["sha256"] = "d" * 64
        if mutate == "short-audio":
            audio = value["worker"]["outputProbe"]["facts"]["audio"]
            audio["decodedSamplesPerChannel"] -= 2048
            audio["codecPaddingSamplesPerChannel"] -= 2048
            audio["decodedDurationSeconds"] = \
                audio["decodedSamplesPerChannel"] / 48000
        return value

    return QualificationRunners(observe, transcode)


def _stage_pair(root: Path):
    attempt = new_attempt(root)
    media_path = attempt.path / "qualified.mp4"
    media_path.write_bytes(b"qualified-media")
    observed = observe_qualified_output(str(media_path))
    media = seal_stage_media(attempt, "qualified.mp4", observed)
    evidence = write_stage(attempt, "qualification.json", b"{}\n")
    files = (
        PublishFile("qualified.mp4", "final.mp4", media),
        PublishFile("qualification.json", "final.json", evidence),
    )
    return attempt, files


class QualificationPublicationAdversarialTests(unittest.TestCase):
    def test_keyboard_interrupt_between_links_rolls_back_first_link(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root, original = Path(raw), os.link
            attempt, files = _stage_pair(root)
            calls = 0

            def interrupt(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise KeyboardInterrupt
                return original(*args, **kwargs)

            try:
                with patch(
                        "qualification_mezzanine_publish.os.link",
                        side_effect=interrupt), self.assertRaises(
                            KeyboardInterrupt):
                    with publication_transaction(attempt, files):
                        pass
                self.assertFalse((root / "final.mp4").exists())
                self.assertFalse((root / "final.json").exists())
            finally:
                cleanup_attempt(attempt)
                close_attempt(attempt)

    def test_stage_symlink_never_reaches_descriptor_chmod(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root, attempt = Path(raw), new_attempt(Path(raw))
            victim = root / "victim"
            victim.write_bytes(b"victim")
            os.chmod(victim, 0o600)
            (attempt.path / "qualified.mp4").symlink_to(victim)
            fake = source_fact(str(attempt.path / "qualified.mp4"))
            try:
                with self.assertRaises(OSError):
                    seal_stage_media(attempt, "qualified.mp4", fake)
                self.assertEqual(stat.S_IMODE(os.stat(victim).st_mode), 0o600)
            finally:
                cleanup_attempt(attempt)
                close_attempt(attempt)

    def test_post_publish_verify_failure_removes_both_final_names(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root, request = Path(raw), _request(Path(raw))
            with patch(
                    "qualification_mezzanine.verify_qualification_evidence",
                    side_effect=RuntimeError("verify fault")), self.assertRaisesRegex(
                        RuntimeError, "verify fault"):
                build_qualification_mezzanine(request, _runners(request))
            self.assertFalse(os.path.lexists(request.output))
            self.assertFalse(os.path.lexists(request.evidence))

    def test_post_publish_stage_cleanup_failure_rolls_back_and_retries(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root, request = Path(raw), _request(Path(raw))
            from qualification_mezzanine_publish import cleanup_attempt as real
            calls = 0

            def fail_once(attempt, strict=True):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise RuntimeError("cleanup fault")
                return real(attempt, strict)

            with patch(
                    "qualification_mezzanine.cleanup_attempt",
                    side_effect=fail_once), self.assertRaisesRegex(
                        RuntimeError, "cleanup fault"):
                build_qualification_mezzanine(request, _runners(request))
            self.assertFalse(os.path.lexists(request.output))
            self.assertFalse(os.path.lexists(request.evidence))


class QualificationAuthorityAdversarialTests(unittest.TestCase):
    def test_control_plane_bound_never_exceeds_request_or_ten_minutes(
            self) -> None:
        for requested, expected in ((300, 300), (600, 600), (10800, 600)):
            with self.subTest(requested=requested):
                launch = QualificationLaunch(
                    "/source", "/output", "qualification-name",
                    requested, 24)
                self.assertEqual(_control_plane_timeout(launch), expected)

    def test_launch_timeout_emits_only_proved_safe_retry_receipt(self) -> None:
        launch = QualificationLaunch(
            "/source", "/output", "qualification-name", 10800, 24)
        expired = subprocess.TimeoutExpired(["docker"], _LAUNCH_TIMEOUT_SECONDS)
        runner = Mock(side_effect=expired)
        reconciliation = Mock()
        with patch(
                "headless.qualification_mezzanine_runtime.subprocess.run",
                runner), patch(
                "headless.qualification_mezzanine_runtime."
                "reconcile_launch_abort",
                reconciliation), patch(
                "headless.qualification_mezzanine_runtime.time.monotonic",
                side_effect=[10.0, 612.25]), self.assertRaisesRegex(
                    RuntimeError,
                    r"launchTimeoutSeconds=600; "
                    r"reconcileTimeoutSeconds=600; "
                    r"elapsedSeconds=602\.250; "
                    r"canonicalAbsenceProved=true; retryAllowed=true"):
            _launch(runtime(), "/config", ["docker"], launch)
        self.assertEqual(
            runner.call_args.kwargs["timeout"], _LAUNCH_TIMEOUT_SECONDS)
        reconciliation.assert_called_once_with(
            runtime(), "/config", launch.name, _LAUNCH_RECONCILE_SECONDS)

    def test_launch_timeout_forbids_retry_when_absence_is_unproved(self) -> None:
        launch = QualificationLaunch(
            "/source", "/output", "qualification-name", 10800, 24)
        expired = subprocess.TimeoutExpired(["docker"], _LAUNCH_TIMEOUT_SECONDS)
        with patch(
                "headless.qualification_mezzanine_runtime.subprocess.run",
                side_effect=expired), patch(
                "headless.qualification_mezzanine_runtime."
                "reconcile_launch_abort",
                side_effect=RuntimeError("late create remains")), patch(
                "headless.qualification_mezzanine_runtime.time.monotonic",
                side_effect=[10.0, 1210.0]), self.assertRaisesRegex(
                    RuntimeError,
                    r"launchTimeoutSeconds=600; "
                    r"reconcileTimeoutSeconds=600; "
                    r"elapsedSeconds=1200\.000; "
                    r"canonicalAbsenceProved=false; retryAllowed=false"):
            _launch(runtime(), "/config", ["docker"], launch)

    def test_inspect_timeout_is_transient_state_unavailability(self) -> None:
        expired = subprocess.TimeoutExpired(["docker", "inspect"], 15)
        with patch(
                "headless.qualification_mezzanine_runtime.subprocess.run",
                side_effect=expired):
            self.assertIsNone(
                _container_state(runtime(), "/config", "qualification-name"))

    def test_wait_retries_unavailable_state_and_accepts_later_result(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            request = QualificationLaunch(
                "/source", raw, "qualification-name", 300, 24)
            sleeps = []

            def publish(delay: float) -> None:
                sleeps.append(delay)
                if len(sleeps) == 2:
                    Path(raw, "result.json").write_text(
                        '{"schemaVersion":1,"ok":true}', encoding="utf-8")

            with patch(
                    "headless.qualification_mezzanine_runtime._container_state",
                    return_value=None) as state, patch(
                    "headless.qualification_mezzanine_runtime.time.sleep",
                    side_effect=publish):
                result = _wait_result(runtime(), "/config", request)
        self.assertTrue(result["ok"])
        self.assertEqual(state.call_count, 2)
        self.assertEqual(sleeps[0], 0.1)
        self.assertAlmostEqual(sleeps[1], 0.15)

    def test_mounted_source_hash_mismatch_and_short_audio_fail_closed(self) -> None:
        for mutation in ("source-hash", "short-audio"):
            with self.subTest(mutation=mutation), \
                    tempfile.TemporaryDirectory() as raw:
                request = _request(Path(raw))
                with self.assertRaises(RuntimeError):
                    build_qualification_mezzanine(
                        request, _runners(request, mutation))
                self.assertFalse(os.path.lexists(request.output))
                self.assertFalse(os.path.lexists(request.evidence))

    def test_runtime_always_removes_container_when_wait_fails(self) -> None:
        removal = Mock(return_value={"canonicalAbsenceProved": True})
        with patch(
                "headless.qualification_mezzanine_runtime.required_runtime",
                return_value=runtime()), patch(
                "headless.qualification_mezzanine_runtime.attest_image",
                return_value={"Id": "image", "Architecture": "arm64",
                              "Os": "linux"}), patch(
                "headless.qualification_mezzanine_runtime.container_command",
                return_value=["docker"]), patch(
                "headless.qualification_mezzanine_runtime._launch"), patch(
                "headless.qualification_mezzanine_runtime."
                "attest_qualification_container",
                return_value={"networkMode": "none"}), patch(
                "headless.qualification_mezzanine_runtime._wait_result",
                side_effect=RuntimeError("timeout")), patch(
                "headless.qualification_mezzanine_runtime.remove_container",
                removal), self.assertRaisesRegex(RuntimeError, "timeout"):
            run_isolated_transcode("/source", "/output", 300, 24)
        removal.assert_called_once()

    @unittest.skipUnless(shutil.which("node"), "node required")
    def test_composed_worker_binds_hash_audio_and_uses_no_shell(self) -> None:
        source = _worker_source()
        self.assertIn("sourceHashBefore", source)
        self.assertIn("sourceHashAfter", source)
        self.assertIn("apad=whole_len=", source)
        self.assertIn("decodedAudioSamples", source)
        self.assertNotIn("shell: true", source)
        checked = subprocess.run(
            ["node", "--check", "-"], input=source, capture_output=True,
            text=True, check=False)
        self.assertEqual(checked.returncode, 0, checked.stderr)


if __name__ == "__main__":
    unittest.main()
