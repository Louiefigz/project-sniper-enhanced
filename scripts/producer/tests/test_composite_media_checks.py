"""Boundaries for secret-free media checks used by the new compositor."""
from __future__ import annotations

import ast
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _common import pl  # noqa: F401
from headless import composite_media_checks as checks


def _completed(stdout: str = "", stderr: str = "",
               returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["ffmpeg"], returncode, stdout, stderr)


class CompositeMediaCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = os.path.realpath(self.temporary.name)
        self.config = checks.MediaCommandConfig(
            "/approved/bin/ffmpeg", self.root, 12.5)

    def test_run_command_uses_closed_process_request(self) -> None:
        with mock.patch.object(checks, "run_text", return_value=_completed()) as run:
            result = checks.run_media_command(self.config, ("-v", "error"))
        self.assertEqual(result.returncode, 0)
        request = run.call_args.args[0]
        self.assertEqual(
            request.command,
            ("/approved/bin/ffmpeg", "-hide_banner", "-nostdin", "-v", "error"))
        self.assertEqual(request.stdin_text, "")
        self.assertEqual(request.cwd, self.root)
        self.assertEqual(request.timeout_seconds, 12.5)
        self.assertEqual(request.environment, {
            "AV_LOG_FORCE_NOCOLOR": "1", "LANG": "C", "LC_ALL": "C",
            "TZ": "UTC",
        })

    def test_run_command_rejects_invalid_direct_config_construction(self) -> None:
        invalid = (
            checks.MediaCommandConfig("ffmpeg", self.root, 1),
            checks.MediaCommandConfig("/ffmpeg", "relative", 1),
            checks.MediaCommandConfig("/ffmpeg", self.root, True),
            checks.MediaCommandConfig("/ffmpeg", self.root, float("nan")),
        )
        with mock.patch.object(checks, "run_text") as run:
            for config in invalid:
                with self.subTest(config=config), self.assertRaises(
                        checks.CompositeMediaCheckError):
                    checks.run_media_command(config, ("-version",))
        run.assert_not_called()

    def test_run_command_reports_only_bounded_stderr_tail(self) -> None:
        stderr = "SECRET_PREFIX:" + "x" * 300
        with mock.patch.object(
                checks, "run_text", return_value=_completed(stderr=stderr, returncode=9)):
            with self.assertRaises(checks.CompositeMediaCheckError) as raised:
                checks.run_media_command(self.config, ("-version",))
        message = str(raised.exception)
        self.assertNotIn("SECRET_PREFIX", message)
        self.assertTrue(message.endswith("x" * 240))


class CompositeMediaHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = os.path.realpath(self.temporary.name)
        self.config = checks.MediaCommandConfig("/approved/ffmpeg", self.root, 30)

    def test_audio_hash_stream_copies_and_requires_one_stream(self) -> None:
        digest = "a" * 64
        with mock.patch.object(
                checks, "run_media_command",
                return_value=_completed(f"0,a,SHA256={digest}\n")) as run:
            actual = checks.audio_stream_sha256("/candidate/final.mp4", self.config)
        self.assertEqual(actual, digest)
        arguments = run.call_args.args[1]
        self.assertIn(("-map", "0:a", "-c:a", "copy"), tuple(
            arguments[index:index + 4] for index in range(len(arguments) - 3)))
        self.assertIn("streamhash", arguments)
        self.assertEqual(arguments[-1], "-")

    def test_audio_hash_rejects_zero_multiple_or_malformed_streams(self) -> None:
        outputs = (
            "",
            f"0,a,SHA256={'a' * 64}\n1,a,SHA256={'b' * 64}\n",
            f"0,v,SHA256={'a' * 64}\n",
            "0,a,SHA256=1234\n",
            f"SHA256={'a' * 64}\n",
        )
        for stdout in outputs:
            with self.subTest(stdout=stdout), mock.patch.object(
                    checks, "run_media_command",
                    return_value=_completed(stdout)):
                with self.assertRaises(checks.CompositeMediaCheckError):
                    checks.audio_stream_sha256("/candidate/final.mp4", self.config)

    def test_extract_frame_zero_creates_one_nonempty_regular_png(self) -> None:
        output = os.path.join(self.root, "cover.pending")

        def create_cover(*_args: object) -> subprocess.CompletedProcess:
            Path(output).write_bytes(b"PNG")
            return _completed()

        with mock.patch.object(
                checks, "run_media_command", side_effect=create_cover) as run:
            size = checks.extract_frame_zero(
                "/candidate/final.mp4", output, self.config)
        self.assertEqual(size, 3)
        arguments = run.call_args.args[1]
        self.assertIn(r"select=eq(n\,0)", arguments)
        self.assertEqual(arguments.count("-frames:v"), 1)
        self.assertEqual(arguments[arguments.index("-frames:v") + 1], "1")
        self.assertEqual(arguments[-2:], ("-n", output))

    def test_extract_frame_zero_rejects_existing_or_empty_output(self) -> None:
        existing = os.path.join(self.root, "existing.png")
        Path(existing).write_bytes(b"old")
        with mock.patch.object(checks, "run_media_command") as run:
            with self.assertRaises(checks.CompositeMediaCheckError):
                checks.extract_frame_zero("/candidate/final.mp4", existing, self.config)
        run.assert_not_called()

        empty = os.path.join(self.root, "empty.png")

        def create_empty(*_args: object) -> subprocess.CompletedProcess:
            Path(empty).touch()
            return _completed()

        with mock.patch.object(checks, "run_media_command", side_effect=create_empty):
            with self.assertRaises(checks.CompositeMediaCheckError):
                checks.extract_frame_zero("/candidate/final.mp4", empty, self.config)

    def test_full_decode_uses_xerror_and_no_bounded_duration(self) -> None:
        with mock.patch.object(
                checks, "run_media_command", return_value=_completed()) as run:
            result = checks.full_decode_xerror("/candidate/final.mp4", self.config)
        self.assertIsNone(result)
        arguments = run.call_args.args[1]
        self.assertIn("-xerror", arguments)
        self.assertEqual(arguments[-2:], ("null", "-"))
        self.assertNotIn("-t", arguments)
        self.assertNotIn("-ss", arguments)

    def test_module_imports_no_legacy_or_product_specific_paths(self) -> None:
        source = Path(checks.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        forbidden = ("palmier", "assemble", "graphics", "render")
        self.assertFalse(any(
            name.startswith(prefix) for name in imported for prefix in forbidden))


if __name__ == "__main__":
    unittest.main(verbosity=2)
