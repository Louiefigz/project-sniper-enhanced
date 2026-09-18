"""Actual byte-holding faults with TEST-only mocked runtime/archive authority."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from headless.render_layout_contract import canonical, encoded_request
from headless.render_layout_read import LayoutReadExpectation, _media, read_observation, screening_envelopes
from test_render_layout_contract import documents, fixture


class LayoutReadTests(unittest.TestCase):
    """These fixtures do not claim genuine browser/OCI/media qualification."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="TEST-layout-read-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name).resolve() / "TEST-not-real-media.mp4"
        self.path.write_bytes(b"TEST opaque non-media bytes")
        request, expected, value = fixture()
        media = {"sha256": hashlib.sha256(self.path.read_bytes()).hexdigest(),
                 "sizeBytes": self.path.stat().st_size}
        value["media"] = media
        self.raw = canonical(value)
        self.observation = self.path.with_suffix(".mp4.layout.json")
        self.observation.write_bytes(self.raw)
        runtime = {"snapshotSha256": request["snapshotSha256"], "snapshotManifest": [],
                   "layoutObservation": {"sha256": hashlib.sha256(self.raw).hexdigest()}}
        for key in ("containerBeforeOutput", "containerAfterOutput"):
            runtime[key] = {"Config": {"Env": ["SNIPER_LAYOUT_REQUEST=" + encoded_request(request)]}}
        self.proof = self.path.with_suffix(".mp4.proof.json")
        self.proof.write_bytes(canonical({"runtimeAttestation": runtime}))
        self.expected = LayoutReadExpectation(request, media["sha256"],
            hashlib.sha256(self.raw).hexdigest(), hashlib.sha256(self.proof.read_bytes()).hexdigest(),
            "sha256:" + "f" * 64, expected["observerSources"])
        self.addCleanup(patch.stopall)
        self.runtime = patch("headless.render_layout_read.validate_runtime_attestation").start()
        patch("headless.render_layout_read.sealed_documents", return_value=documents()).start()

    def test_original_raw_hash_is_returned_after_actual_file_rechecks(self) -> None:
        ref, value = read_observation(str(self.path), self.expected, lambda: None)
        self.assertEqual(ref["sha256"], self.expected.observation_sha256)
        self.assertEqual(value["framesObserved"], 2)
        self.assertTrue(self.runtime.called)

    def test_receipt_mutation_during_late_work_rejects(self) -> None:
        calls = 0
        def guard() -> None:
            nonlocal calls
            calls += 1
            if calls == 4:
                self.observation.write_bytes(self.raw + b" ")
        with self.assertRaisesRegex(ValueError, "observation changed"):
            read_observation(str(self.path), self.expected, guard)

    def test_actual_media_mutation_after_initial_read_rejects(self) -> None:
        def replace(*_args) -> dict:
            self.path.write_bytes(b"changed TEST bytes")
            return documents()
        with patch("headless.render_layout_read.sealed_documents", side_effect=replace):
            with self.assertRaisesRegex(ValueError, "media/proof changed"):
                read_observation(str(self.path), self.expected, lambda: None)

    def test_missing_independently_held_hash_and_symlink_reject(self) -> None:
        self.observation.unlink()
        other = Path(self.temp.name) / "other.json"
        other.write_bytes(self.raw)
        self.observation.symlink_to(other)
        with self.assertRaises(OSError):
            read_observation(str(self.path), self.expected, lambda: None)

    def test_legacy_runtime_without_actual_observer_admission_rejects(self) -> None:
        proof = json.loads(self.proof.read_bytes())
        proof["runtimeAttestation"]["containerBeforeOutput"]["Config"]["Env"] = []
        self.proof.write_bytes(canonical(proof))
        held = LayoutReadExpectation(self.expected.request, self.expected.media_sha256,
            self.expected.observation_sha256, hashlib.sha256(self.proof.read_bytes()).hexdigest(),
            self.expected.image_id, self.expected.observer_sources)
        with self.assertRaisesRegex(ValueError, "omitted/changed"):
            read_observation(str(self.path), held, lambda: None)

    def test_unqualified_cannot_project_into_a_layout_screen(self) -> None:
        _, _, value = fixture()
        value["status"] = "unqualified"
        with self.assertRaisesRegex(ValueError, "unqualified"):
            screening_envelopes(value)

    def test_growing_file_rejects_on_first_over_limit_chunk_without_waiting_for_eof(self) -> None:
        original_read, calls = os.read, 0
        def growing_read(fd: int, size: int) -> bytes:
            nonlocal calls
            calls += 1
            with self.path.open("ab") as handle:
                handle.write(b"GROWING TEST BYTES")
            if calls > 1:
                raise AssertionError("reader waited beyond first over-limit chunk")
            return original_read(fd, size)
        with patch("headless.render_layout_read.os.read", side_effect=growing_read):
            with self.assertRaisesRegex(ValueError, "exceeded held byte limit"):
                _media(str(self.path), lambda: None)
        self.assertEqual(calls, 1)


if __name__ == "__main__":
    unittest.main()
