"""Real special-file regressions at media-receipt readers; no decoder runs."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from headless.external_media_probe import _read_result
from ingest_admission_contract import _read_regular


_CHILD = r"""
import os, sys
from pathlib import Path
from unittest.mock import patch
from headless.external_media_probe import _probe, _read_result
from headless.external_media_probe_policy import MediaProbeLimits
from headless.external_media_snapshot import ExternalMediaSnapshot
from ingest_admission_contract import _read_regular

root, mode = Path(sys.argv[1]), sys.argv[2]
if mode != 'cleanup':
    (root / 'result').mkdir()
    target = root / 'result' / 'result.json'
    os.mkfifo(target, 0o600)
    try:
        if mode == 'probe':
            _read_result(None, str(root), 'unused')
        else:
            _read_regular(target, 1024, 'admission receipt')
    except RuntimeError as error:
        print('REJECTED', error)
    else:
        raise AssertionError('FIFO was accepted')
else:
    def launch(*args):
        os.mkfifo(root / 'result' / 'result.json', 0o600)
        return 'inert-container-id'
    prefix = 'headless.external_media_probe.'
    with patch(prefix+'container_command', return_value=['inert']), \
         patch(prefix+'_launch', side_effect=launch), \
         patch(prefix+'attest_probe_container', return_value={}), \
         patch(prefix+'probe_container', return_value={}), \
         patch(prefix+'remove_container', return_value={'canonicalAbsenceProved':True}) as removal:
        try:
            _probe(None, str(root), ExternalMediaSnapshot('/inert', 'a'*64, 1, 0, 0), MediaProbeLimits())
        except RuntimeError:
            removal.assert_called_once_with(None, str(root), 'inert-container-id')
            print('REJECTED_AND_CLEANUP_CALLED')
        else:
            raise AssertionError('FIFO was accepted')
"""


class MediaReceiptReadSafetyTests(unittest.TestCase):
    """Bound the regression itself so a broken open cannot hang the suite."""

    def _fifo_child(self, mode: str) -> str:
        """Run actual FIFO opens in one owned child with a hard outer timeout."""
        with tempfile.TemporaryDirectory(prefix="sniper-receipt-fifo-") as raw:
            try:
                result = subprocess.run([sys.executable, "-c", _CHILD, raw, mode],
                                        capture_output=True, text=True, timeout=2, check=False)
            except subprocess.TimeoutExpired:
                self.fail(f"{mode} receipt reader blocked on a FIFO before type validation")
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_probe_fifo_rejects_without_waiting_for_a_writer(self) -> None:
        """The container's result mount cannot block the host reader open."""
        self.assertIn("REJECTED", self._fifo_child("probe"))

    def test_ingest_fifo_rejects_without_waiting_for_a_writer(self) -> None:
        """An edited source-set/admission receipt cannot block input verification."""
        self.assertIn("REJECTED", self._fifo_child("ingest"))

    def test_probe_fifo_rejection_still_runs_owned_container_cleanup(self) -> None:
        """Exercise real FIFO/read/wait plus a mocked external container boundary."""
        self.assertIn("REJECTED_AND_CLEANUP_CALLED", self._fifo_child("cleanup"))

    def test_socket_rejects_without_reading(self) -> None:
        """Actual local socket paths are never interpreted as receipt data."""
        with tempfile.TemporaryDirectory(prefix="sniper-receipt-socket-") as raw:
            root = Path(raw)
            (root / "result").mkdir()
            target = root / "result" / "result.json"
            with socket.socket(socket.AF_UNIX) as listener:
                listener.bind(str(target))
                with patch("os.read", side_effect=AssertionError("must not read socket")):
                    with self.assertRaises(OSError):
                        _read_result(None, str(root), "unused")
                    with self.assertRaises(RuntimeError):
                        _read_regular(target, 1024, "receipt")

    def test_device_descriptor_rejects_before_read_and_closes(self) -> None:
        """Type-first rejection closes actual owned device descriptors."""
        readers = (lambda: _read_result(None, "/inert", "unused"),
                   lambda: _read_regular(Path("/inert"), 1024, "receipt"))
        for reader in readers:
            descriptor = os.open(os.devnull, os.O_RDONLY | os.O_NONBLOCK)
            with self.subTest(reader=reader), patch("os.open", return_value=descriptor), \
                    patch("os.read", side_effect=AssertionError("must not read device")):
                with self.assertRaisesRegex(RuntimeError, "bounded"):
                    reader()
            with self.assertRaises(OSError):
                os.fstat(descriptor)

    def test_regular_payload_and_file_identity_contract_stays_unchanged(self) -> None:
        """The narrow open fix does not change parsing or regular-file bytes."""
        with tempfile.TemporaryDirectory(prefix="sniper-receipt-regular-") as raw:
            root = Path(raw)
            (root / "result").mkdir()
            target = root / "result" / "result.json"
            payload = b'{"bounded":true}\n'
            target.write_bytes(payload)
            self.assertEqual(_read_result(None, str(root), "unused"), payload.decode())
            self.assertEqual(_read_regular(target, 1024, "receipt"), payload)


if __name__ == "__main__":
    unittest.main()
