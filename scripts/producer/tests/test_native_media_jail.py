"""Real-process properties of the native admission jail on this Mac.

Every test launches the actual launcher and decoder under the shipped profile:
denied reads, writes, network and process creation; the kernel memory cap; the
CPU ceiling; the wall-clock deadline and process-group reap; attestation and
approval enforcement. Nothing here mocks the sandbox itself.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from _native_media_fixture import HAVE_NATIVE, DecoyListener, valid_mp4
from headless import native_media_runtime, native_media_sandbox
from headless.native_media_runtime import LAUNCHER, PROFILE, NativeRuntimeError
from headless.native_media_sandbox import JailLimits, JailRejection, run_decoder, verified_runtime


def _launcher(decoder: str, arguments: list[str], root: Path) -> subprocess.CompletedProcess:
    """Run the real launcher with an arbitrary decoder (tests only; production allows two)."""
    runtime = verified_runtime()
    root = Path(tempfile.mkdtemp(dir=root))
    request = root / "request.json"
    request.write_text(json.dumps({
        "profilePath": str(PROFILE), "profileSha256": runtime.identity["profileSha256"],
        "memoryMiB": 256, "cpuSeconds": 10,
        "parameters": {"DECODER": decoder, "LIBROOT": runtime.library_root,
                       "LINKROOT": runtime.link_root, "INPUT": "/dev/null"}}))
    attest = os.open(root / "attest", os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        return subprocess.run([sys.executable, "-I", "-S", "-B", str(LAUNCHER), str(request), str(attest), "--",
                               decoder, *arguments], pass_fds=(attest,), capture_output=True, text=True,
                              timeout=30, env={"PATH": "/usr/bin:/bin"})
    finally:
        os.close(attest)


@unittest.skipUnless(HAVE_NATIVE, "needs macOS, sandbox-exec and ffmpeg")
class NativeJailPropertyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.runtime = verified_runtime()
        self.media = valid_mp4(self.root / "input.mp4")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _ffmpeg(self, *arguments: str, limits: JailLimits = JailLimits(30, 30)):
        return run_decoder(self.runtime, self.runtime.ffmpeg, ("-nostdin", "-v", "error", *arguments),
                           (str(self.media), limits))

    def test_admitted_input_decodes_with_attestation(self) -> None:
        done = self._ffmpeg("-i", str(self.media), "-f", "null", "-")
        self.assertEqual(done.stderr, "")
        self.assertTrue(done.attestation["sandboxed"])
        self.assertEqual(done.attestation["rlimits"]["RLIMIT_FSIZE"], [0, 0])
        self.assertEqual(done.attestation["memoryMiB"], 768)

    def test_reading_any_other_file_is_denied(self) -> None:
        secret = self.root / "secret.mp4"
        secret.write_bytes(self.media.read_bytes())
        with self.assertRaises(JailRejection) as caught:
            self._ffmpeg("-i", str(secret), "-f", "null", "-")
        self.assertIn("Operation not permitted", str(caught.exception))

    def test_writing_is_denied(self) -> None:
        target = self.root / "written.mp4"
        with self.assertRaises(JailRejection) as caught:
            self._ffmpeg("-i", str(self.media), "-t", "1", str(target))
        self.assertIn("Operation not permitted", str(caught.exception))
        self.assertFalse(target.exists())

    def test_network_is_denied_before_any_connection(self) -> None:
        decoy = DecoyListener()
        try:
            for url in (f"http://127.0.0.1:{decoy.port}/x.mp4", "http://1.1.1.1/x.mp4"):
                with self.assertRaises(JailRejection) as caught:
                    self._ffmpeg("-rw_timeout", "3000000", "-i", url, "-f", "null", "-")
                self.assertIn("Operation not permitted", str(caught.exception))
        finally:
            decoy.close()
        self.assertEqual(decoy.connections, 0)

    def test_process_creation_and_other_executables_are_denied(self) -> None:
        forked = _launcher("/bin/sh", ["-c", 'x=$(/bin/echo leaked); printf "[%s]" "$x"'], self.root)
        self.assertNotIn("[leaked]", forked.stdout)
        self.assertIn("Operation not permitted", forked.stderr)
        execed = _launcher("/bin/sh", ["-c", "exec /bin/echo leaked"], self.root)
        self.assertNotEqual(execed.returncode, 0)
        self.assertNotIn("leaked", execed.stdout)

    def test_kernel_memory_cap_kills_an_oversized_decode(self) -> None:
        arguments = ("-f", "lavfi", "-i", "color=size=3840x2160:rate=30", "-t", "2",
                     "-vf", "tmix=frames=16", "-f", "null", "-")
        with self.assertRaises(JailRejection) as caught:
            self._ffmpeg(*arguments, limits=JailLimits(60, 60, memory_mib=64))
        self.assertEqual(caught.exception.code, "MEMORY_LIMIT")
        self._ffmpeg(*arguments, limits=JailLimits(120, 120))  # same work passes under the real 768 MiB cap

    def test_cpu_heavy_runaway_is_bounded_by_the_wall_deadline(self) -> None:
        # macOS sends one SIGXCPU at RLIMIT_CPU and never escalates at the hard
        # limit; ffmpeg treats SIGXCPU as a graceful-stop request. The enforced
        # bound is the supervisor's deadline plus process-group reap.
        began = time.monotonic()
        with self.assertRaises(JailRejection) as caught:
            self._ffmpeg("-f", "lavfi", "-i", "mandelbrot=size=1920x1080:rate=30", "-t", "120",
                         "-f", "null", "-", limits=JailLimits(3, 1))
        self.assertIn(caught.exception.code, {"DECODE_TIMEOUT", "CPU_LIMIT", "DECODER_EXIT_255"})
        self.assertLess(time.monotonic() - began, 8)
        leftover = subprocess.run(["/usr/bin/pgrep", "-f", "mandelbrot=size=1920x1080"], capture_output=True)
        self.assertEqual(leftover.stdout.strip(), b"")

    def test_wall_deadline_reaps_the_decoder(self) -> None:
        with self.assertRaises(JailRejection) as caught:
            self._ffmpeg("-re", "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=30", "-t", "60",
                         "-f", "null", "-", limits=JailLimits(1.5, 60))
        self.assertEqual(caught.exception.code, "DECODE_TIMEOUT")
        leftover = subprocess.run(["/usr/bin/pgrep", "-f", str(self.media) + " -f null"], capture_output=True)
        self.assertEqual(leftover.stdout.strip(), b"")

    def test_output_without_attestation_is_refused(self) -> None:
        with mock.patch.object(native_media_sandbox, "_read_attestation", return_value=None):
            with self.assertRaises(JailRejection) as caught:
                self._ffmpeg("-i", str(self.media), "-f", "null", "-")
        self.assertEqual(caught.exception.code, "JAIL_UNATTESTED")

    def test_only_identified_decoders_may_run(self) -> None:
        with self.assertRaises(NativeRuntimeError):
            run_decoder(self.runtime, "/bin/sh", ("-c", "true"), (str(self.media), JailLimits(5, 5)))

    def test_tampered_profile_is_refused_by_the_launcher(self) -> None:
        with mock.patch.dict(self.runtime.identity, {"profileSha256": hashlib.sha256(b"other").hexdigest()}):
            with self.assertRaises(JailRejection) as caught:
                self._ffmpeg("-i", str(self.media), "-f", "null", "-")
        self.assertEqual(caught.exception.code, "JAIL_UNAVAILABLE")

    def test_unapproved_jail_files_are_refused(self) -> None:
        native_media_runtime._CACHE.clear()
        try:
            with mock.patch.object(native_media_runtime, "approved_pair", return_value=False):
                with self.assertRaisesRegex(NativeRuntimeError, "not the approved"):
                    native_media_runtime.required_native_runtime()
        finally:
            native_media_runtime._CACHE.clear()

    def test_shipped_profile_and_launcher_are_the_approved_pair(self) -> None:
        identity = native_media_runtime.required_native_runtime().identity
        self.assertTrue(native_media_runtime.approved_pair(identity["profileSha256"], identity["launcherSha256"]))


if __name__ == "__main__":
    unittest.main()
