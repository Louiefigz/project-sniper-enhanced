"""Active network-proof positive and negative controls."""
from __future__ import annotations

import unittest
from unittest import mock
import threading

from _common import pl  # noqa: F401
from headless import network_probe


class NetworkProbeTests(unittest.TestCase):
    def _decoy(self) -> network_probe._Decoy:
        return network_probe._Decoy(mock.Mock(), threading.Event(), mock.Mock(),
                                    43123, b"a" * 32)

    def test_host_loopback_decoy_has_a_real_positive_control(self) -> None:
        try:
            with network_probe._host_decoy() as decoy:
                self.assertGreater(decoy.port, 0)
                self.assertEqual(len(decoy.nonce), 32)
        except PermissionError:
            self.skipTest("test sandbox denies loopback bind")

    def test_host_loopback_decoy_closes_socket_when_bind_fails(self) -> None:
        server = mock.Mock()
        server.bind.side_effect = PermissionError("denied")
        with mock.patch("headless.network_probe.socket.socket",
                        return_value=server), self.assertRaises(PermissionError):
            with network_probe._host_decoy():
                self.fail("bind failure must not yield a decoy")
        server.close.assert_called_once_with()

    def test_exact_container_denials_validate(self) -> None:
        decoy = self._decoy()
        denied = {"reached": False, "error": "ENETUNREACH"}
        value = {"schemaVersion": 1, "decoyPort": decoy.port,
                 "ownLoopback": {"ok": True},
                 "hostLoopbackDecoy": denied, "externalIpv4": denied,
                 "externalIpv6": denied,
                 "dns": {"resolved": False, "error": "EAI_AGAIN"}}
        proof = network_probe._validate(value, decoy)
        self.assertTrue(proof["hostDecoyPositive"])

    def test_broken_probe_without_own_loopback_is_rejected(self) -> None:
        decoy = self._decoy()
        denied = {"reached": False, "error": "TIMEOUT"}
        value = {"schemaVersion": 1, "decoyPort": decoy.port,
                 "ownLoopback": {"ok": False},
                 "hostLoopbackDecoy": denied, "externalIpv4": denied,
                 "externalIpv6": denied,
                 "dns": {"resolved": False, "error": "TIMEOUT"}}
        with self.assertRaisesRegex(RuntimeError, "denial proof"):
            network_probe._validate(value, decoy)


if __name__ == "__main__":
    unittest.main(verbosity=2)
