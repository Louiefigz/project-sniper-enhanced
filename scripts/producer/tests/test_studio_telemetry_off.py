"""The adapted HyperFrames runtime serves the Studio page with its analytics switched off.

HeyGen's published Studio page sends usage events (including the project's name in
its address) to PostHog unless the browser opts out. Sniper serves Studio from its
adapted runtime (studio/native_runtime.py); the patch set replaces the analytics
project key so the page's own isApiKeyConfigured() check fails and nothing is sent.
Browser evidence (recorded requests): outputs/.../evidence/final/studio-requests-*.json.
"""
import json
import os
import re
import unittest

from _common import *  # noqa: F401,F403

from studio.native_runtime import PATCH_ROOT, apply_bytes

_STOCK = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
                      "templates", "motion", "node_modules", "hyperframes", "dist")
_KEY = re.compile(rb"phc_[A-Za-z0-9]{20,}")   # a PostHog project key (the page checks the "phc_" prefix)
_STUDIO_FILES = ("studio/assets/index-CfQexXc6.js", "studio/index.js")


@unittest.skipUnless(os.path.isdir(_STOCK), "the installed HyperFrames package is not present")
class StudioTelemetryOffTests(unittest.TestCase):
    def setUp(self) -> None:
        with open(PATCH_ROOT / "patches.json", encoding="utf-8") as handle:
            self.rows = {row["file"]: row for row in json.load(handle)["files"]}

    def test_both_studio_entry_files_are_patched(self) -> None:
        for name in _STUDIO_FILES:
            self.assertIn(name, self.rows, f"{name} must be adapted (an SDK update needs new rows)")

    def test_patched_studio_files_carry_no_analytics_key(self) -> None:
        for name in _STUDIO_FILES:
            with open(os.path.join(_STOCK, name), "rb") as handle:
                stock = handle.read()
            self.assertRegex(stock, _KEY, f"{name}: the published page has an analytics key")
            patched = apply_bytes(stock, self.rows[name])
            self.assertIsNone(_KEY.search(patched), f"{name}: an analytics key survives the patch")


if __name__ == "__main__":
    unittest.main()
