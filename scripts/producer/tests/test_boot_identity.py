from __future__ import annotations

import hashlib
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

PRODUCER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PRODUCER_DIR))

from headless.boot_identity import BootIdentityError, read_boot_id  # noqa: E402


def _expected(system: str, token: str) -> str:
    payload = f"sniper-boot-id-v1\0{system}\0{token}".encode("ascii")
    return f"boot-v1-{hashlib.sha256(payload).hexdigest()}"


class BootIdentityTests(unittest.TestCase):
    def test_linux_reads_and_domain_separates_kernel_uuid(self) -> None:
        value = b"12345678-1234-4abc-8def-1234567890ab\n"
        with mock.patch("headless.boot_identity.platform.system", return_value="Linux"), \
                mock.patch("headless.boot_identity.os.open", return_value=41), \
                mock.patch("headless.boot_identity.os.read", return_value=value), \
                mock.patch("headless.boot_identity.os.close") as close:
            actual = read_boot_id()
        self.assertEqual(actual, _expected("linux", value.decode().strip()))
        close.assert_called_once_with(41)

    def test_linux_rejects_malformed_kernel_value(self) -> None:
        with mock.patch("headless.boot_identity.platform.system", return_value="Linux"), \
                mock.patch("headless.boot_identity.os.open", return_value=42), \
                mock.patch("headless.boot_identity.os.read", return_value=b"not-a-uuid"), \
                mock.patch("headless.boot_identity.os.close"):
            with self.assertRaisesRegex(BootIdentityError, "invalid boot ID"):
                read_boot_id()

    def test_darwin_uses_exact_sysctl_and_normalizes_timestamp(self) -> None:
        result = subprocess.CompletedProcess(
            [], 0, "{ sec = 1783353954, usec = 576205 } Mon Jul  6\n", "")
        with mock.patch("headless.boot_identity.platform.system", return_value="Darwin"), \
                mock.patch("headless.boot_identity.subprocess.run",
                           return_value=result) as run:
            actual = read_boot_id()
        self.assertEqual(actual, _expected("darwin", "1783353954.576205"))
        self.assertEqual(run.call_args.args[0],
                         ["/usr/sbin/sysctl", "-n", "kern.boottime"])
        self.assertEqual(run.call_args.kwargs["timeout"], 2)
        self.assertNotIn("HOME", run.call_args.kwargs["env"])

    def test_darwin_fails_closed_on_error_or_invalid_microseconds(self) -> None:
        cases = (
            subprocess.CompletedProcess([], 1, "", "denied"),
            subprocess.CompletedProcess([], 0, "{ sec = 1, usec = 1000000 }", ""),
        )
        for result in cases:
            with self.subTest(stdout=result.stdout), \
                    mock.patch("headless.boot_identity.platform.system",
                               return_value="Darwin"), \
                    mock.patch("headless.boot_identity.subprocess.run",
                               return_value=result):
                with self.assertRaises(BootIdentityError):
                    read_boot_id()

    def test_unsupported_os_fails_closed(self) -> None:
        with mock.patch("headless.boot_identity.platform.system",
                        return_value="Plan9"):
            with self.assertRaisesRegex(BootIdentityError, "unsupported"):
                read_boot_id()


if __name__ == "__main__":
    unittest.main(verbosity=2)
