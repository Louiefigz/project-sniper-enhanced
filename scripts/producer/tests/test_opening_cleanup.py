"""Filesystem no-start/unknown boundaries; these tests launch no Docker jobs."""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from cut_preview_io import write_new
from guided_opening_claim import HeldOpeningClaim, registration_intent, resource_request
from guided_opening_cleanup import reconcile_order


class OpeningCleanupTests(unittest.TestCase):
    """Never convert missing post-arm evidence into successful absence proof."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="sniper-opening-cleanup-unit-")
        self.root = Path(self.temporary.name).resolve()
        self.claim = HeldOpeningClaim(self.root / "claim.json", "a" * 64, {
            "outputRoot": str(self.root), "executionId": "b" * 36, "inputSha256": "c" * 64,
            "selectedGraphicOrders": [2], "runtime": {"dockerPath": "/TEST/docker", "dockerSocketPath": "/TEST/socket",
                "imageId": "sha256:" + "d" * 64, "userId": "1000:1000"}})
        self.attempt = Path(resource_request(self.claim, 2).attempt_root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_never_initialized_and_initialized_unarmed_make_no_docker_call(self) -> None:
        with patch("headless.claimed_resource_cleanup.reconcile_registered_containers") as called:
            self.assertEqual(reconcile_order(self.claim, 2)["state"], "not-initialized")
            self.attempt.mkdir(parents=True, mode=0o700)
            self.assertEqual(reconcile_order(self.claim, 2)["state"], "initialized-unarmed")
            called.assert_not_called()

    def test_armed_without_ledger_is_unknown_even_if_no_container_was_started(self) -> None:
        self.attempt.mkdir(parents=True, mode=0o700)
        write_new(self.attempt / "registration-intent.json", registration_intent(self.claim, 2))
        with self.assertRaisesRegex(RuntimeError, "UNKNOWN.*no durable ledger"):
            reconcile_order(self.claim, 2)

    def test_ledger_without_preceding_marker_is_unknown_not_empty(self) -> None:
        self.attempt.mkdir(parents=True, mode=0o700)
        write_new(self.attempt / "resource-ledger.json", {"TEST": "unclaimed resource"})
        with self.assertRaisesRegex(RuntimeError, "without its armed"):
            reconcile_order(self.claim, 2)

    def test_wrong_claim_marker_and_unclaimed_order_are_rejected(self) -> None:
        self.attempt.mkdir(parents=True, mode=0o700)
        marker = {**registration_intent(self.claim, 2), "claimSha256": "f" * 64}
        write_new(self.attempt / "registration-intent.json", marker)
        with self.assertRaisesRegex(RuntimeError, "differs from exact claim"):
            reconcile_order(self.claim, 2)
        with self.assertRaisesRegex(RuntimeError, "not claimed"):
            reconcile_order(self.claim, 3)

    def test_linked_ancestor_cannot_hide_or_redirect_resources(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        (self.root / "graphics").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "canonical|unsafe"):
            reconcile_order(self.claim, 2)
        self.assertEqual(list(outside.iterdir()), [])

    def test_real_fifo_marker_is_rejected_without_hanging(self) -> None:
        self.attempt.mkdir(parents=True, mode=0o700)
        os.mkfifo(self.attempt / "registration-intent.json")
        started = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, "bounded regular"):
            reconcile_order(self.claim, 2)
        self.assertLess(time.monotonic() - started, 0.5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
