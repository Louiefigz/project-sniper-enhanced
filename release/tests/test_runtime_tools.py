"""Sniper's own tools: the bash bootstrap (install/lib/runtime_tools*.sh) and the build-side lock.

The installer worker runs for real against a small stand-in lock: one micromamba archive whose
"micromamba" is a script (its SHA-256 is written into the lock), one package file, and a shipped
"ffmpeg" archive carrying the download quarantine. Downloads come from a file:// mirror through
the same SNIPER_TOOLS_BASE_URL the installer tests use. Nothing reaches the network or a real
tool; every stand-in executable is a regular file.

Run: .venv/bin/python -m unittest release.tests.test_runtime_tools
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from release import macho_floor, runtime_tools
from release.tests import _fixture as fx

STUB_MICROMAMBA = r'''#!/bin/bash
# Stand-in micromamba: records how it was run, then lays out the tools a real one would.
# The installer runs it with an emptied environment, so its paths are written in (@LOG@, @TOOLS@).
STUB_LOG="@LOG@"; STUB_TOOLS="@TOOLS@"
{ printf 'ARGV'; printf ' [%s]' "$@"; printf '\nHOME=%s ROOT=%s\n' "$HOME" "$MAMBA_ROOT_PREFIX"; } >> "$STUB_LOG"
prefix=""; file=""
while [ $# -gt 0 ]; do case "$1" in -p) prefix="$2"; shift 2 ;; --file) file="$2"; shift 2 ;; *) shift ;; esac; done
cp "$file" "$STUB_LOG.explicit"
mkdir -p "$prefix/bin" "$prefix/var/cache/fontconfig"
for tool in node npm whisper-cli tesseract yt-dlp git; do cp "$STUB_TOOLS/$tool" "$prefix/bin/$tool"; done
cp "$STUB_TOOLS/python3" "$prefix/bin/python3"
'''


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tar(members: dict[str, bytes], mode: str) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode=mode) as bundle:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), 0o755
            bundle.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


class InstallWorker(unittest.TestCase):
    """ensure_runtime_tools -> runtime_tools_install.sh, end to end with stand-ins."""

    def setUp(self) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="sniper-rt-"))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.pkg = fx.make_package(self.base)
        self.home = self.base / "home"
        self.mirror, self.log = self.base / "mirror", self.base / "micromamba.log"
        self.stub_tools = self.base / "stub-tools"
        self.stub_tools.mkdir()
        for name, body in fx.TOOL_STUBS.items():
            (self.stub_tools / name).write_text(f"#!/bin/bash\n{body}\n")
        (self.stub_tools / "python3").write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
        for stub in self.stub_tools.iterdir():
            stub.chmod(0o755)
        self.ffmpeg_archive = _tar({"bin/ffmpeg": f"#!/bin/bash\n{fx.FFMPEG_STUB}\n".encode(),
                                    "bin/ffprobe": b"#!/bin/bash\necho ffprobe version 8.0.3\n"}, "w:xz")
        self._write_lock()

    def _write_lock(self, bin_sha: str | None = None) -> None:
        micromamba = STUB_MICROMAMBA.replace("@LOG@", str(self.log)).replace("@TOOLS@", str(self.stub_tools)).encode()
        archive = _tar({"bin/micromamba": micromamba}, "w:bz2")
        package = b"a conda package"
        for rel, data in (("tools/micromamba-2.9.0-0.tar.bz2", archive),
                          ("conda-forge/osx-arm64/tiny-1.0-0.conda", package)):
            (self.mirror / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.mirror / rel).write_bytes(data)
        shipped = self.pkg / "install/deps/sniper-ffmpeg-test.tar.xz"
        shipped.write_bytes(self.ffmpeg_archive)
        subprocess.run(["xattr", "-w", "com.apple.quarantine", "0083;66ec1234;Safari;F1", str(shipped)], check=True)
        lock = ["# sniper-runtime-lock-v1 — test", "# platform osx-arm64", "# min-macos 13.0",
                "# tools python=3.14.4", "# kind sha256 bytes path source",
                f"micromamba {_sha(archive)} {len(archive)} tools/micromamba-2.9.0-0.tar.bz2 https://example.invalid/m",
                f"micromamba-bin {bin_sha or _sha(micromamba)} {len(micromamba)} bin/micromamba -",
                f"conda {_sha(package)} {len(package)} conda-forge/osx-arm64/tiny-1.0-0.conda https://example.invalid/t",
                f"local {_sha(self.ffmpeg_archive)} {len(self.ffmpeg_archive)} sniper-ffmpeg-test.tar.xz "
                "install/deps/sniper-ffmpeg-test.tar.xz"]
        (self.pkg / "install/deps/osx-arm64.lock").write_text("\n".join(lock) + "\n")
        self.prefix = fx.runtime_prefix(self.home, self.pkg / "install/deps/osx-arm64.lock")

    def _ensure(self) -> subprocess.CompletedProcess:
        env = {**fx.base_env(self.pkg), "SNIPER_TOOLS_BASE_URL": f"file://{self.mirror}"}
        return fx.bash(self.pkg, "ensure_runtime_tools && echo ENSURED", env, timeout=120)

    def test_fresh_install_follows_the_lock(self) -> None:
        done = self._ensure()
        self.assertIn("ENSURED", done.stdout, done.stdout + done.stderr)
        self.assertEqual((self.prefix / ".sniper-runtime-complete").read_text(), self.prefix.name)
        self.assertTrue((self.prefix.parent / f"{self.prefix.name}.tree.json").exists(), "no integrity record")
        call = self.log.read_text()
        for flag in ("[create]", "[--offline]", "[--platform] [osx-arm64]", "[--always-copy]", "[--no-rc]"):
            self.assertIn(flag, call)
        self.assertIn(f"HOME={self.home}/.project-sniper/mamba-home ROOT={self.home}/.project-sniper/mamba-root", call)
        explicit = Path(f"{self.log}.explicit").read_text().splitlines()
        package = self.home / ".project-sniper/pkgs/conda-forge/osx-arm64/tiny-1.0-0.conda"
        self.assertEqual(explicit, ["@EXPLICIT", f"file://{package}#sha256:{_sha(b'a conda package')}"])
        self.assertFalse((self.home / ".conda").exists() or (self.home / ".mamba").exists(), "wrote to ~/.conda or ~/.mamba")

    def test_the_shipped_ffmpeg_is_installed_without_the_download_quarantine(self) -> None:
        self.assertIn("ENSURED", self._ensure().stdout)
        attrs = subprocess.run(["xattr", str(self.prefix / "bin/ffmpeg")], capture_output=True, text=True).stdout
        self.assertNotIn("com.apple.quarantine", attrs)

    def test_a_changed_ffmpeg_archive_is_refused(self) -> None:
        (self.pkg / "install/deps/sniper-ffmpeg-test.tar.xz").write_bytes(self.ffmpeg_archive + b"x")
        done = self._ensure()
        self.assertNotIn("ENSURED", done.stdout)
        self.assertIn("does not match its pinned SHA-256; this folder is damaged", done.stderr)
        self.assertFalse((self.prefix / ".sniper-runtime-complete").exists())

    def test_a_micromamba_that_is_not_the_pinned_one_is_refused(self) -> None:
        self._write_lock(bin_sha="0" * 64)
        done = self._ensure()
        self.assertIn("micromamba does not match its pinned SHA-256", done.stderr)
        self.assertFalse(self.log.exists(), "an unverified micromamba ran")

    def test_a_package_that_changed_on_the_way_is_deleted_and_reported(self) -> None:
        (self.mirror / "conda-forge/osx-arm64/tiny-1.0-0.conda").write_bytes(b"tampered")
        done = self._ensure()
        self.assertIn("produced the wrong file (checksum mismatch); it was deleted", done.stderr)
        self.assertFalse(self.log.exists(), "micromamba ran without every checked package")

    def test_ready_tools_are_not_installed_again(self) -> None:
        self.assertIn("ENSURED", self._ensure().stdout)
        self.log.unlink()
        done = self._ensure()
        self.assertIn("Sniper's own tools — present", done.stdout)
        self.assertFalse(self.log.exists())

    def test_a_second_installer_waits_for_the_first(self) -> None:
        lockfile = self.home / ".project-sniper/install.lock"
        lockfile.parent.mkdir(parents=True, exist_ok=True)
        holder = subprocess.Popen(["/usr/bin/lockf", "-k", str(lockfile), "/bin/sleep", "3"])
        self.addCleanup(holder.wait)
        subprocess.run(["/bin/sleep", "0.5"], check=True)
        done = self._ensure()
        self.assertIn("Another Sniper installer is setting up the same tools; waiting", done.stdout)
        self.assertIn("ENSURED", done.stdout)


class Preconditions(unittest.TestCase):
    """What is refused before anything is downloaded."""

    def setUp(self) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="sniper-rt-"))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.pkg = fx.make_package(self.base)

    def test_a_home_folder_with_a_space_is_refused(self) -> None:
        env = {**fx.base_env(self.pkg), "HOME": str(self.base / "my home")}
        done = fx.bash(self.pkg, "deps_paths && echo paths", env)
        self.assertNotIn("paths", done.stdout)
        self.assertIn("Your home folder path contains a space", done.stderr)

    def test_an_older_macos_is_refused(self) -> None:
        lock = self.pkg / "install/deps/osx-arm64.lock"
        text = lock.read_text()
        self.assertEqual(text.count("\n# min-macos "), 1)
        lock.write_text(re.sub(r"\n# min-macos \S+\n", "\n# min-macos 99.0\n", text))
        done = fx.bash(self.pkg, "require_macos && echo supported")
        self.assertNotIn("supported", done.stdout)
        self.assertIn("Sniper's tools need macOS 99.0", done.stderr)

    def test_your_own_python_node_and_library_settings_never_reach_sniper(self) -> None:
        env = {**fx.base_env(self.pkg), "PYTHONPATH": "/x", "PYTHONHOME": "/x", "NODE_OPTIONS": "--require /x.js",
               "DYLD_LIBRARY_PATH": "/opt/homebrew/lib", "DYLD_INSERT_LIBRARIES": "/x.dylib",
               "CONDA_PREFIX": "/x", "TESSDATA_PREFIX": "/x", "SSL_CERT_FILE": "/company/ca.pem"}
        done = fx.bash(self.pkg, 'env | sort', env)
        names = {line.split("=", 1)[0] for line in done.stdout.splitlines()}
        self.assertFalse(names & {"PYTHONPATH", "PYTHONHOME", "NODE_OPTIONS", "DYLD_LIBRARY_PATH",
                                  "DYLD_INSERT_LIBRARIES", "CONDA_PREFIX", "TESSDATA_PREFIX"}, names)
        self.assertIn("SSL_CERT_FILE=/company/ca.pem", done.stdout)   # a proxy's certificate is kept
        self.assertIn("PATH=/usr/bin:/bin:/usr/sbin:/sbin", done.stdout.splitlines())

    def test_a_cleared_environment_gets_the_users_own_temporary_folder(self) -> None:
        env = {key: value for key, value in fx.base_env(self.pkg).items() if key != "TMPDIR"}
        done = fx.bash(self.pkg, 'printf "%s" "$TMPDIR"', env)
        own = subprocess.run(["/usr/bin/getconf", "DARWIN_USER_TEMP_DIR"], capture_output=True, text=True).stdout.strip()
        self.assertEqual(done.stdout, own)
        self.assertFalse(done.stdout.startswith("/tmp"))
        kept = fx.bash(self.pkg, 'printf "%s" "$TMPDIR"', {**env, "TMPDIR": "/Volumes/scratch/t/"})
        self.assertEqual(kept.stdout, "/Volumes/scratch/t/")

    def test_this_mac_meets_the_real_lock(self) -> None:
        self.assertEqual(fx.bash(self.pkg, "require_macos && echo supported").stdout.strip(), "supported")


class BuildSideLock(unittest.TestCase):
    """release/runtime_tools.py: the lock the package ships and the checks the build runs."""

    def test_the_shipped_lock_reads_and_names_exactly_one_of_each_special_row(self) -> None:
        header, rows = runtime_tools.read_lock()
        self.assertEqual(header["platform"], "osx-arm64")
        kinds = [row["kind"] for row in rows]
        self.assertEqual((kinds.count("micromamba"), kinds.count("micromamba-bin"), kinds.count("local")), (1, 1, 1))
        self.assertGreater(kinds.count("conda"), 50)

    def test_a_malformed_row_is_refused(self) -> None:
        bad = Path(tempfile.mkdtemp()) / "lock"
        self.addCleanup(shutil.rmtree, bad.parent)
        bad.write_text(runtime_tools.HEADER + "\nconda nothex 12 a b\n")
        with self.assertRaisesRegex(runtime_tools.LockError, "malformed lock row"):
            runtime_tools.read_lock(bad)

    def test_the_macos_floor_is_the_newest_any_part_needs(self) -> None:
        packages = [{"depends": ["__osx >=11.0"]}, {"depends": ["__osx >=12.0", "libfoo"]}]
        self.assertEqual(runtime_tools.min_macos(packages), "13.0")   # the Python wheels need 13
        self.assertEqual(runtime_tools.min_macos([{"depends": ["__osx >=14.2"]}]), "14.2")

    def test_a_shipped_file_that_does_not_match_its_pin_refuses_the_build(self) -> None:
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder)
        (folder / "f").write_bytes(b"changed")
        with mock.patch.object(runtime_tools, "shipped_files", return_value={"install/deps/f": (folder / "f", "0" * 64)}):
            with self.assertRaisesRegex(runtime_tools.LockError, "does not match its pin"):
                runtime_tools.check()


    def test_a_lock_below_the_floor_measured_from_its_binaries_is_refused(self) -> None:
        _, rows = runtime_tools.read_lock()
        record = Path(tempfile.mkdtemp()) / "measured.json"
        self.addCleanup(shutil.rmtree, record.parent)
        record.write_text(json.dumps({"conda_rows_sha256": runtime_tools.conda_rows_sha256(rows),
                                      "min_macos": "99.0", "set_by": ["bin/node"], "macho_files": 1}))
        with mock.patch.object(runtime_tools, "MEASURED", record):
            with self.assertRaisesRegex(runtime_tools.LockError, "bin/node need macOS 99.0"):
                runtime_tools.check()

    def test_a_floor_measured_for_other_packages_does_not_count(self) -> None:
        record = Path(tempfile.mkdtemp()) / "measured.json"
        self.addCleanup(shutil.rmtree, record.parent)
        record.write_text(json.dumps({"conda_rows_sha256": "0" * 64, "min_macos": "11.0", "set_by": [], "macho_files": 1}))
        for measured in (record, record.parent / "absent.json"):
            with mock.patch.object(runtime_tools, "MEASURED", measured):
                with self.assertRaisesRegex(runtime_tools.LockError, "no macOS floor has been measured"):
                    runtime_tools.check()

    def test_measuring_refuses_a_runtime_of_other_packages(self) -> None:
        prefix = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, prefix)
        (prefix / "conda-meta").mkdir()
        (prefix / "conda-meta/other.json").write_text(json.dumps({"sha256": "1" * 64}))
        with mock.patch.object(runtime_tools, "MEASURED", prefix / "measured.json"):
            with self.assertRaisesRegex(runtime_tools.LockError, "not an install of this lock"):
                runtime_tools.measure(prefix)
            self.assertFalse((prefix / "measured.json").exists())


def _macho(cputype: int, floor: tuple[int, int] | None, legacy: bool = False) -> bytes:
    """A minimal 64-bit Mach-O file whose one load command names its macOS floor."""
    encoded = (floor[0] << 16) | (floor[1] << 8) if floor else 0
    if floor is None:
        command = struct.pack("<II", 0x19, 8)                                   # an unrelated command
    elif legacy:
        command = struct.pack("<IIII", 0x24, 16, encoded, 0)                    # LC_VERSION_MIN_MACOSX
    else:
        command = struct.pack("<IIIIII", 0x32, 24, 1, encoded, 0, 0)            # LC_BUILD_VERSION, macOS
    return b"\xcf\xfa\xed\xfe" + struct.pack("<iiIIIII", cputype, 0, 2, 1, len(command), 0, 0) + command


def _fat(*slices: bytes) -> bytes:
    cputypes = [struct.unpack_from("<i", s, 4)[0] for s in slices]
    offset, table, body = 8 + 20 * len(slices), b"", b""
    for cputype, data in zip(cputypes, slices):
        table += struct.pack(">iiIII", cputype, 0, offset + len(body), len(data), 0)
        body += data
    return b"\xca\xfe\xba\xbe" + struct.pack(">I", len(slices)) + table + body


class MachOFloor(unittest.TestCase):
    """The macOS floor read from the files themselves (release/macho_floor.py)."""

    def _write(self, name: str, data: bytes) -> Path:
        path = self.folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder)

    def test_arm64_files_name_their_floor_either_way(self) -> None:
        self.assertEqual(macho_floor.file_floor(self._write("a", _macho(0x0100000C, (13, 5)))), "13.5")
        self.assertEqual(macho_floor.file_floor(self._write("b", _macho(0x0100000C, (12, 0), legacy=True))), "12.0")
        self.assertIsNone(macho_floor.file_floor(self._write("c", _macho(0x0100000C, None))))

    def test_only_the_arm64_code_counts(self) -> None:
        self.assertIsNone(macho_floor.file_floor(self._write("x86", _macho(0x01000007, (10, 15)))))
        fat = _fat(_macho(0x01000007, (10, 15)), _macho(0x0100000C, (14, 0)))
        self.assertEqual(macho_floor.file_floor(self._write("fat", fat)), "14.0")

    def test_other_files_are_not_mistaken_for_binaries(self) -> None:
        java = b"\xca\xfe\xba\xbe\x00\x00\x00\x34" + b"\x00" * 40      # a Java class file shares the magic
        self.assertIsNone(macho_floor.file_floor(self._write("A.class", java)))
        self.assertIsNone(macho_floor.file_floor(self._write("cut", _macho(0x0100000C, (13, 5))[:40])))
        self.assertIsNone(macho_floor.file_floor(self._write("t.txt", b"#!/bin/bash\n")))

    def test_a_folder_reports_its_newest_floor_and_the_files_that_set_it(self) -> None:
        self._write("bin/node", _macho(0x0100000C, (13, 5)))
        self._write("lib/libnode.dylib", _macho(0x0100000C, (13, 5)))
        self._write("bin/python", _macho(0x0100000C, (11, 0)))
        self._write("share/readme", b"text")
        (self.folder / "bin/link").symlink_to("node")
        self.assertEqual(macho_floor.folder_floor(self.folder), ("13.5", ["bin/node", "lib/libnode.dylib"], 3))


if __name__ == "__main__":
    unittest.main()
