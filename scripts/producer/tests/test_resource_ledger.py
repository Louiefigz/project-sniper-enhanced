"""Durable Docker resource registration and startup-reconciliation tests."""
from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _common import pl  # noqa: F401
from headless import resource_ledger as ledger

_IMAGE = "sha256:" + "a" * 64


class ResourceLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.attempt = Path(self.temp.name).resolve() / "attempt-a"
        self.attempt.mkdir(mode=0o700)
        os.chmod(self.attempt, 0o700)
        self.work = self.attempt / "work"
        self.work.mkdir(mode=0o700)
        self.scratch = self.work / "tmp"
        self.scratch.mkdir(mode=0o700)

    def _request(self, socket: str = "/private/docker.sock") -> ledger.ResourceRequest:
        return ledger.ResourceRequest(
            str(self.attempt), "attempt-a", "/usr/bin/docker", socket,
            _IMAGE, "501:20")

    def test_lease_is_durable_before_yield_and_removed_after_proof(self) -> None:
        request = self._request()
        with mock.patch.object(ledger, "_cleanup", return_value={}) as cleanup:
            with ledger.container_lease(request) as name:
                self.assertEqual(ledger.registered_containers(request), (name,))
                path = self.attempt / ledger.LEDGER_NAME
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                value = json.loads(path.read_text())
                self.assertEqual(value["resources"][0]["state"], "REGISTERED")
            self.assertEqual(ledger.registered_containers(request), ())
            self.assertEqual(ledger.removed_containers(request), (name,))
        cleanup.assert_called_once_with(request, name, False)

    def test_body_failure_uses_late_create_reconciliation(self) -> None:
        request = self._request()
        with mock.patch.object(ledger, "_cleanup", return_value={}) as cleanup:
            with self.assertRaisesRegex(RuntimeError, "worker failed"):
                with ledger.container_lease(request) as name:
                    raise RuntimeError("worker failed")
        cleanup.assert_called_once_with(request, name, True)
        self.assertEqual(ledger.registered_containers(request), ())

    def test_cleanup_failure_remains_registered_for_startup(self) -> None:
        request = self._request()
        with mock.patch.object(ledger, "_cleanup",
                               side_effect=RuntimeError("daemon unavailable")):
            with self.assertRaisesRegex(RuntimeError, "daemon unavailable"):
                with ledger.container_lease(request) as name:
                    pass
        self.assertEqual(ledger.registered_containers(request), (name,))
        with mock.patch.object(ledger, "_cleanup", return_value={"removed": True}) as clean:
            receipts = ledger.reconcile_registered_containers(request)
        self.assertEqual(receipts, ({"removed": True},))
        clean.assert_called_once_with(request, name, True)
        self.assertEqual(ledger.registered_containers(request), ())

    def test_other_control_plane_cannot_reconcile_active_name(self) -> None:
        request = self._request()
        with mock.patch.object(ledger, "_cleanup",
                               side_effect=RuntimeError("leave active")):
            with self.assertRaises(RuntimeError):
                with ledger.container_lease(request):
                    pass
        other = self._request("/private/other-docker.sock")
        with self.assertRaisesRegex(ledger.ResourceLedgerError,
                                    "another Docker control plane"):
            ledger.registered_containers(other)

    def test_noncanonical_or_tampered_ledger_fails_closed(self) -> None:
        request = self._request()
        alias = ledger.ResourceRequest(
            str(self.attempt / ".." / "attempt-a"), request.attempt_id,
            request.docker, request.docker_socket, request.image_id,
            request.user_id)
        with self.assertRaisesRegex(ledger.ResourceLedgerError, "canonical"):
            ledger.registered_containers(alias)
        path = self.attempt / ledger.LEDGER_NAME
        path.write_text('{"attemptId":"attempt-a","resources":[],"schemaVersion":1}\n ')
        os.chmod(path, 0o600)
        with self.assertRaisesRegex(ledger.ResourceLedgerError, "canonical"):
            ledger.registered_containers(request)


if __name__ == "__main__":
    unittest.main(verbosity=2)
