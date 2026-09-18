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
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from _native_media_fixture import HAVE_NATIVE, DecoyListener, valid_mp4
from headless import native_media_runtime, native_media_sandbox
from headless.native_macho import dependency_paths
from headless.native_media_runtime import LAUNCHER, PROFILE, NativeRuntimeError, generate_profile
from headless.native_media_sandbox import JailLimits, JailRejection, run_decoder, run_inspect, verified_runtime
from headless.native_media_watchdog import JailWatchdog


def _request(decoder: str, root: Path, wall: float = 30, memory: int = 256,
             profile_text: str | None = None) -> tuple[Path, int]:
    """A real launcher request with a generated profile and an arbitrary decoder (tests only)."""
    profile_text = verified_runtime().profile_text if profile_text is None else profile_text
    root = Path(tempfile.mkdtemp(dir=root))
    profile = root / "jail.sb"
    profile.write_text(profile_text, encoding="utf-8")
    request = root / "request.json"
    request.write_text(json.dumps({
        "profilePath": str(profile), "profileSha256": hashlib.sha256(profile_text.encode()).hexdigest(),
        "mode": "exec",
        "memoryMiB": memory, "cpuSeconds": 10, "wallSeconds": wall, "limits": {}, "inputPath": "/dev/null",
        "parameters": {"DECODER": decoder, "INPUT": "/dev/null"}}))
    return request, os.open(root / "attest", os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)


def _launcher(decoder: str, arguments: list[str], root: Path,
              profile_text: str | None = None) -> subprocess.CompletedProcess:
    """Run the real launcher with an arbitrary decoder (tests only; production allows two)."""
    request, attest = _request(decoder, root, profile_text=profile_text)
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
        self.assertTrue(native_media_runtime.approved_pair(identity["profileTemplateSha256"], identity["launcherSha256"]))

    def test_input_named_through_a_symlinked_folder_is_decoded_and_attested(self) -> None:
        linked = self.root / "linked"
        linked.symlink_to(self.root, target_is_directory=True)  # like /var -> /private/var
        path = str(linked / "input.mp4")
        done = run_decoder(self.runtime, self.runtime.ffmpeg, ("-nostdin", "-v", "error", "-i", path, "-f", "null", "-"),
                           (path, JailLimits(30, 30)))
        self.assertEqual((done.attestation["input"], done.attestation["inputResolved"]), (path, str(self.media)))

    def test_reads_are_limited_to_the_decoders_own_files(self) -> None:
        other = next(Path("/opt/homebrew/Cellar").glob("python@*/*/Frameworks/Python.framework/Versions/*/lib/*/LICENSE.txt"), None)
        if other is None:
            self.skipTest("no other Homebrew formula file to probe")
        denied = _launcher("/bin/cat", [str(other)], self.root)
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("Operation not permitted", denied.stderr)

    @unittest.skipUnless(shutil.which("cc"), "needs a C compiler for the stand-in decoder")
    def test_a_decoder_outside_homebrew_exposes_only_its_own_files(self) -> None:
        home = self.root / "home"  # the reviewer's layout: a decoder installed under a home folder
        (home / ".ssh").mkdir(parents=True)
        secret = home / ".ssh" / "id_ed25519"
        secret.write_text("PRIVATE KEY")
        (home / "bin").mkdir()
        source = home / "bin" / "reader.c"
        source.write_text('#include <stdio.h>\nint main(int c,char**v){FILE*f=fopen(v[1],"r");'
                          'if(!f){perror(v[1]);return 3;}int ch;while((ch=fgetc(f))!=EOF)putchar(ch);return 0;}')
        decoder = home / "bin" / "ffprobe"
        subprocess.run(["cc", "-o", str(decoder), str(source)], check=True, capture_output=True)
        profile = generate_profile(PROFILE.read_text(encoding="utf-8"), dependency_paths((str(decoder),)).opened)
        self.assertEqual(_launcher(str(decoder), ["/dev/null"], self.root, profile).returncode, 0)
        for other in (secret, source):
            denied = _launcher(str(decoder), [str(other)], self.root, profile)
            self.assertEqual(denied.returncode, 3, other.name)
            self.assertIn("Operation not permitted", denied.stderr)
            self.assertNotIn("PRIVATE", denied.stdout)

    def test_other_processes_are_invisible_inside_the_jail(self) -> None:
        marker = f"sniper-victim-{os.getpid()}-{time.monotonic_ns()}"
        victim = subprocess.Popen(["/bin/sh", "-c", 'exec -a "$0" /bin/sleep 30', marker])
        try:
            seen = subprocess.run(["/usr/bin/pgrep", "-f", marker], capture_output=True, text=True)
            self.assertIn(str(victim.pid), seen.stdout, "control: pgrep outside the jail sees the victim")
            jailed = _launcher("/usr/bin/pgrep", ["-f", marker], self.root)  # not setuid, so it does start
        finally:
            victim.kill()
            victim.wait()
        self.assertNotIn(str(victim.pid), jailed.stdout)
        self.assertIn("Cannot get process list", jailed.stderr)

    def test_watchdog_never_signals_a_process_older_than_itself(self) -> None:
        bystander = subprocess.Popen(["/bin/sleep", "30"])
        attest = os.open(self.root / "bystander-attest", os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(attest, (json.dumps({"pid": bystander.pid}) + "\n").encode())
            watchdog = JailWatchdog(attest, 1, 60)  # a 1-byte ceiling the bystander already exceeds
            watchdog.start()
            time.sleep(0.3)
            watchdog.stop()
            self.assertIsNone(watchdog.exceeded)
            self.assertIsNone(bystander.poll(), "an unrelated process named by pid must survive")
        finally:
            os.close(attest)
            bystander.kill()
            bystander.wait()

    def test_watchdog_enforces_the_cpu_ceiling(self) -> None:
        began = time.monotonic()
        with self.assertRaises(JailRejection) as caught:
            self._ffmpeg("-f", "lavfi", "-i", "mandelbrot=size=1920x1080:rate=30", "-t", "120",
                         "-f", "null", "-", limits=JailLimits(60, 2))
        self.assertEqual(caught.exception.code, "CPU_LIMIT")
        self.assertLess(time.monotonic() - began, 20)

    @unittest.skipUnless(shutil.which("cc"), "needs a C compiler for the re-exec probe")
    def test_watchdog_catches_a_decoder_that_re_execs_to_shed_the_kernel_limit(self) -> None:
        source = self.root / "reexec.c"
        source.write_text('#include <stdlib.h>\n#include <string.h>\n#include <unistd.h>\n'
                          'int main(int c,char**v){if(c<3){char*a[]={v[0],"x","y",0};execv(v[0],a);}'
                          'for(int i=0;i<64;i++){char*p=malloc(16<<20);memset(p,1,16<<20);usleep(20000);}return 0;}')
        binary = self.root / "reexec"
        subprocess.run(["cc", "-O0", "-o", str(binary), str(source)], check=True, capture_output=True)
        request, attest = _request(str(binary), self.root, memory=128)
        watchdog = JailWatchdog(attest, 128 << 20, 60)
        watchdog.start()
        try:
            done = subprocess.run([sys.executable, "-I", "-S", "-B", str(LAUNCHER), str(request), str(attest), "--",
                                   str(binary)], pass_fds=(attest,), capture_output=True, timeout=60)
        finally:
            watchdog.stop()
            os.close(attest)
        self.assertEqual(watchdog.exceeded, "MEMORY_LIMIT")
        self.assertLess(watchdog.peak_bytes, 400 << 20)
        self.assertEqual(done.returncode, -9)

    def test_alarm_ends_an_orphaned_decoder(self) -> None:
        request, attest = _request(self.runtime.ffmpeg, self.root, wall=1)
        try:
            began = time.monotonic()
            done = subprocess.run([sys.executable, "-I", "-S", "-B", str(LAUNCHER), str(request), str(attest), "--",
                                   self.runtime.ffmpeg, "-nostdin", "-v", "error", "-re", "-f", "lavfi", "-i",
                                   "testsrc2=size=64x64:rate=30", "-t", "60", "-f", "null", "-"],
                                  pass_fds=(attest,), capture_output=True, timeout=30)
        finally:
            os.close(attest)
        self.assertEqual(done.returncode, -14)  # SIGALRM, with no supervisor watching
        self.assertLess(time.monotonic() - began, 15)

    def test_svg_inspection_is_linear_and_jailed(self) -> None:
        hostile = self.root / "many-open-tags.svg"
        hostile.write_text("<svg " * 60000)
        began = time.monotonic()
        result, attestation = run_inspect(self.runtime, str(hostile), {"maxBytes": 1 << 30, "maxWidth": 8192,
                                                                      "maxHeight": 8192})
        self.assertLess(time.monotonic() - began, 5)
        self.assertEqual((attestation["mode"], attestation["sandboxed"]), ("inspect", True))
        self.assertIn("rejected", result)


if __name__ == "__main__":
    unittest.main()
