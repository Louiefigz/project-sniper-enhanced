"""Retained render-build manifest evidence regressions."""
from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from _common import pl  # noqa: F401
from _current_render_build_fixture import current_manifest
from headless.render_build_receipt import (
    RenderBuildLocator,
    load_render_build,
    store_render_build,
)


class RenderBuildReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.attempt = Path(self.temp.name).resolve() / "attempt-a"
        self.attempt.mkdir(mode=0o700)
        os.chmod(self.attempt, 0o700)
        self.manifest = current_manifest()

    def test_round_trip_is_idempotent_and_private(self) -> None:
        first = store_render_build(str(self.attempt), self.manifest)
        second = store_render_build(str(self.attempt), dict(self.manifest))
        self.assertEqual(first, second)
        self.assertEqual(load_render_build(str(self.attempt), first), self.manifest)
        self.assertEqual(stat.S_IMODE(Path(first.path).stat().st_mode), 0o600)

    def test_missing_tampered_or_forged_receipt_fails_closed(self) -> None:
        locator = store_render_build(str(self.attempt), self.manifest)
        forged = RenderBuildLocator(
            str(Path(locator.path).with_name("elsewhere.json")),
            locator.build_digest)
        with self.assertRaisesRegex(RuntimeError, "locator"):
            load_render_build(str(self.attempt), forged)
        Path(locator.path).write_bytes(b"{}\n")
        os.chmod(locator.path, 0o600)
        with self.assertRaises(RuntimeError):
            load_render_build(str(self.attempt), locator)

    def test_hardlink_and_public_mode_are_rejected(self) -> None:
        locator = store_render_build(str(self.attempt), self.manifest)
        path = Path(locator.path)
        alias = path.with_name("alias.json")
        os.link(path, alias)
        with self.assertRaises(RuntimeError):
            load_render_build(str(self.attempt), locator)
        alias.unlink()
        path.chmod(0o644)
        with self.assertRaises(RuntimeError):
            load_render_build(str(self.attempt), locator)


if __name__ == "__main__":
    unittest.main(verbosity=2)
