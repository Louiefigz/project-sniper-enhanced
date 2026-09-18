"""Crash-safe retry behavior for attempt-owned overlay seal publication."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _common import pl  # noqa: F401
from headless import overlay_seal_store


class OverlaySealStoreTests(unittest.TestCase):
    def test_failed_pending_write_does_not_poison_same_seal_retry(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            attempt = Path(root).resolve() / "attempt-a"
            attempt.mkdir(mode=0o700)
            os.chmod(attempt, 0o700)
            with mock.patch.object(
                    overlay_seal_store, "write_pending_replace",
                    side_effect=RuntimeError("injected")), \
                    self.assertRaisesRegex(RuntimeError, "injected"):
                overlay_seal_store.store_overlay_receipt(
                    str(attempt), "a" * 64, lambda _directory: b"{}\n")
            seals = attempt / "work" / "overlay-seals"
            self.assertFalse(any(path.name.startswith(".pending-")
                                 for path in seals.iterdir()))
            locator = overlay_seal_store.store_overlay_receipt(
                str(attempt), "a" * 64, lambda _directory: b"{}\n")
            self.assertTrue(Path(locator.path).is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
