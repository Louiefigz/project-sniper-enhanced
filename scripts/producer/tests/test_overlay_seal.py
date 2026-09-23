"""Inert overlay storage/dispatch units and real retired-source refusal."""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock

from _common import pl  # noqa: F401
from _retired_r0_artifact_fixture import capture_test_metadata, resolve_test_metadata
from headless import render_worker
from headless.overlay_seal import (
    OverlayPrepareRequest,
    OverlaySealBinding,
    effective_render_intent,
    load_overlay,
    prepare_overlay,
)
from headless.overlay_seal_store import OverlaySealLocator

PRODUCER_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = PRODUCER_DIR.parents[1]
REQUEST_DIGEST = hashlib.sha256(b"attempt-request").hexdigest()
BUILD_DIGEST = hashlib.sha256(b"attempt-build").hexdigest()


def _entry(start: float = 0, anchor: str = "free-band") -> dict:
    return {"kind": "section-marker", "outStart": start,
            "outEnd": start + 2.5, "anchor": anchor, "spec": {
                "num": "Part 1", "line1": "The Setup",
                "line2": "Basics", "side": "left", "accent": "#054BC9"}}


class OverlaySealTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.attempt = Path(self.temp.name).resolve() / "attempt-a"
        self.attempt.mkdir(mode=0o700)
        os.chmod(self.attempt, 0o700)
        self.capture = mock.patch('headless.overlay_seal.capture_overlay_source',
                                  side_effect=capture_test_metadata)
        self.resolve = mock.patch('headless.overlay_seal.resolve_overlay_source',
                                  side_effect=resolve_test_metadata)
        self.capture.start()
        self.resolve.start()
        self.addCleanup(self.capture.stop)
        self.addCleanup(self.resolve.stop)

    def _request(self, entry: dict) -> OverlayPrepareRequest:
        return OverlayPrepareRequest(
            str(self.attempt), "attempt-a", REQUEST_DIGEST, BUILD_DIGEST,
            str(REPO_ROOT), entry, "overlay-1")

    def _binding(self) -> OverlaySealBinding:
        return OverlaySealBinding(
            str(self.attempt), "attempt-a", REQUEST_DIGEST, BUILD_DIGEST,
            "overlay-1")

    def test_mutating_original_entry_after_prepare_changes_nothing(self) -> None:
        entry = _entry()
        locator = prepare_overlay(self._request(entry))
        before = load_overlay(locator, self._binding())
        entry["outEnd"] = 99
        entry["spec"]["line1"] = "MUTATED"
        after = load_overlay(locator, self._binding())
        self.assertEqual(after.intent, before.intent)
        self.assertEqual(after.key, before.key)
        self.assertEqual(after.expected_copy,
                         ("Part 1", "The Setup", "Basics"))

    def test_absolute_shift_reuses_seal_but_anchor_changes_key_and_format(self) -> None:
        first_locator = prepare_overlay(self._request(_entry(0)))
        shifted_locator = prepare_overlay(self._request(_entry(10)))
        opaque_locator = prepare_overlay(self._request(_entry(0, "own-screen")))
        first = load_overlay(first_locator, self._binding())
        shifted = load_overlay(shifted_locator, self._binding())
        opaque = load_overlay(opaque_locator, self._binding())
        self.assertEqual(first_locator, shifted_locator)
        self.assertEqual(first.key, shifted.key)
        self.assertEqual((first.fmt, opaque.fmt), ("mov", "mp4"))
        self.assertNotEqual(first.key, opaque.key)

    def test_unqualified_or_nonfinite_intent_is_rejected_before_sealing(self) -> None:
        invalid = _entry()
        invalid["kind"] = "stat-card"
        cases = (invalid, {**_entry(), "outStart": True},
                 {**_entry(), "outEnd": float("nan")},
                 {**_entry(), "outEnd": float("inf")})
        for entry in cases:
            with self.subTest(entry=entry), \
                    self.assertRaisesRegex(RuntimeError, "qualified|canonical"):
                prepare_overlay(self._request(entry))

    def test_forged_derived_receipt_is_recomputed_and_rejected(self) -> None:
        locator = prepare_overlay(self._request(_entry()))
        value = json.loads(Path(locator.path).read_bytes())
        value["expectedKey"] = "0" * 64
        raw = (json.dumps(value, ensure_ascii=True, separators=(",", ":"),
                          sort_keys=True) + "\n").encode("ascii")
        Path(locator.path).write_bytes(raw)
        os.chmod(locator.path, 0o600)
        forged = OverlaySealLocator(locator.path, hashlib.sha256(raw).hexdigest())
        with self.assertRaisesRegex(RuntimeError, "derived expectations"):
            load_overlay(forged, self._binding())

    def test_snapshot_path_replacement_is_rejected(self) -> None:
        locator = prepare_overlay(self._request(_entry()))
        snapshot = Path(locator.path).with_name("render-input.tar")
        os.chmod(snapshot, 0o600)
        snapshot.write_bytes(b"substituted")
        with self.assertRaisesRegex(RuntimeError, "digest mismatch"):
            load_overlay(locator, self._binding())

    def test_worker_loads_exact_seal_without_live_composition_read(self) -> None:
        locator = prepare_overlay(self._request(_entry()))
        cache = self.attempt / "worker-cache"
        cache.mkdir(mode=0o700)
        payload = {"attemptId": "attempt-a", "attemptRoot": str(self.attempt),
                   "buildDigest": BUILD_DIGEST, "cacheDir": str(cache),
                   "requestDigest": REQUEST_DIGEST, "sealPath": locator.path,
                   "sealSha256": locator.sha256, "selectionId": "overlay-1"}
        stdin, stdout = io.StringIO(json.dumps(payload)), io.StringIO()
        with mock.patch.object(sys, "stdin", stdin), \
                mock.patch.object(sys, "stdout", stdout), \
             mock.patch("headless.overlay_source_seal._read_composition",
                        side_effect=AssertionError("live read")), \
                mock.patch("graphics.sealed_graphics_render.render_presealed",
                           return_value={"sealed": True}):
            self.assertEqual(render_worker.main(), 0)
        self.assertEqual(json.loads(stdout.getvalue()), {"sealed": True})

    def test_real_retired_source_refuses_before_snapshot_or_worker(self) -> None:
        from headless.overlay_source_seal import capture_overlay_source
        with mock.patch('headless.overlay_seal.capture_overlay_source',
                        side_effect=capture_overlay_source), mock.patch(
                            'headless.overlay_source_seal.create_snapshot') as snapshot, mock.patch(
                                'subprocess.Popen') as process, self.assertRaisesRegex(
                                    ValueError, 'section-marker.*retired'):
            prepare_overlay(self._request(_entry()))
        snapshot.assert_not_called()
        process.assert_not_called()
        self.assertFalse(list(self.attempt.rglob('render-input.tar')))
        self.assertFalse(list(self.attempt.rglob('receipt.json')))

    def test_effective_intent_is_a_deep_canonical_copy(self) -> None:
        entry = _entry()
        intent = effective_render_intent(entry)
        frozen = deepcopy(intent)
        entry["spec"]["side"] = "right"
        self.assertEqual(intent, frozen)


if __name__ == "__main__":
    unittest.main(verbosity=2)
