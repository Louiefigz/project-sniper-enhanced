"""Controller-side render-result closure and race regressions."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _common import pl  # noqa: F401
from _render_lane_proof import ProofInputs, build_full_proof
from headless import render_lane
from headless.render_lane import OverlayLaunchRequest
from headless.overlay_seal import (OverlayPrepareRequest, OverlaySealBinding,
                                   load_overlay, prepare_overlay)
from headless.render_lane_cache import prepare_attempt_cache
from headless.render_build_receipt import store_render_build
from headless.request_artifact import store_request_artifact
from headless.resource_ledger import ResourceRequest

PRODUCER_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = PRODUCER_DIR.parents[1]
IMAGE_ID = "sha256:bc56d3860d2ec1c843f7184bcecd21137aa79fe9fe19c90a67136d3052222ba8"
CONTAINER_NAME = "sniper-render-" + "d" * 32


class RenderResultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.authority = Path(self.temp.name).resolve() / "authority"
        self.authority.mkdir(mode=0o700)
        (self.authority / "attempts").mkdir(mode=0o700)
        self.attempt = self.authority / "attempts" / "attempt"
        self.attempt.mkdir(mode=0o700)
        entry = {"kind": "section-marker", "outStart": 0, "outEnd": 2.5,
                 "anchor": "free-band", "spec": {
                     "num": "System No.1", "line1": "Familiarity",
                     "line2": "Rule", "side": "left", "accent": "#054BC9"}}
        artifact = store_request_artifact(str(self.authority), {
            "schemaVersion": 1, "operation": "render-overlays",
            "overlays": [{"overlayId": "overlay-1", "entry": entry}],
        })
        request_digest = artifact.request_digest
        build = store_render_build(str(self.attempt), {"testBuild": True})
        build_digest = build.build_digest
        prepared = OverlayPrepareRequest(
            str(self.attempt), "attempt", request_digest, build_digest,
            str(REPO_ROOT), entry, "overlay-1")
        locator = prepare_overlay(prepared)
        self.request = OverlayLaunchRequest(
            str(self.authority), str(self.attempt), "attempt", build,
            artifact, "overlay-1", locator)
        self.seal = load_overlay(locator, OverlaySealBinding(
            str(self.attempt), "attempt", request_digest, build_digest,
            "overlay-1"))
        identity = (self.request.attempt_id, self.request.request.request_digest,
                    self.request.build_digest, IMAGE_ID)
        self.binding = prepare_attempt_cache(str(self.attempt), identity)
        self.resources = ResourceRequest(
            str(self.attempt), "attempt", "/docker", "/docker.sock",
            IMAGE_ID, "501:20")

    def _value(self, key: str | None = None, image_id: str = IMAGE_ID) -> dict:
        key = key or self.seal.key
        path = Path(self.binding.cache_dir) / f"{key}.mov"
        path.write_bytes(b"rendered")
        path.chmod(0o600)
        return {"cached": False, "fmt": "mov", "key": key,
                "kind": "section-marker", "path": str(path),
                "proof": build_full_proof(
                    path, key, image_id,
                    ProofInputs(self.seal.expected_copy, self.seal.snapshot))}

    @staticmethod
    def _stdout(value: dict) -> str:
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"),
                          sort_keys=True)

    @staticmethod
    def _rewrite_sidecar(value: dict) -> None:
        proof = value["proof"]
        disk = {key: nested for key, nested in proof.items() if key != "sidecar"}
        Path(proof["sidecar"]).write_text(json.dumps(disk), encoding="utf-8")
        Path(proof["sidecar"]).chmod(0o600)

    def _validate(self, value: dict) -> tuple[dict, dict]:
        return render_lane._validated_result(
            self._stdout(value), self.binding, self.seal,
            (IMAGE_ID, CONTAINER_NAME, self.resources))

    def test_complete_strict_result_is_accepted(self) -> None:
        value, output = self._validate(self._value())
        self.assertEqual(value["key"], self.seal.key)
        self.assertEqual(output["sha256"], hashlib.sha256(b"rendered").hexdigest())

    def test_self_consistent_worker_chosen_key_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "result values"):
            self._validate(self._value("f" * 64))

    def test_self_consistent_unapproved_image_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "controller-approved"):
            self._validate(self._value(image_id="sha256:" + "1" * 64))

    def test_worker_snapshot_digest_mismatch_is_rejected(self) -> None:
        value = self._value()
        value["proof"]["runtimeAttestation"]["snapshotSha256"] = "0" * 64
        self._rewrite_sidecar(value)
        with self.assertRaisesRegex(RuntimeError, "controller intent"):
            self._validate(value)

    def test_worker_proof_must_match_registered_container_name(self) -> None:
        value = self._value()
        runtime = value["proof"]["runtimeAttestation"]
        for key in ("containerBeforeOutput", "containerAfterOutput"):
            runtime[key]["Config"]["Labels"][
                "io.project-sniper.render-name"] = "sniper-render-" + "e" * 32
        self._rewrite_sidecar(value)
        with self.assertRaisesRegex(RuntimeError, "registered resource"):
            self._validate(value)

    def test_nested_worker_assertion_contradictions_are_rejected(self) -> None:
        def impossible_occupancy(value: dict) -> None:
            value["proof"]["occupancy"]["measured"]["meaningfulFrames"] = 999

        def malformed_asset(value: dict) -> None:
            value["proof"]["assetInputs"] = [{
                "field": None, "selector": {}, "path": "motion/icon.svg",
                "sha256": "0" * 64}]

        def unexpected_valid_asset(value: dict) -> None:
            value["proof"]["assetInputs"] = [{
                "field": "iconFile", "selector": "icon.svg",
                "path": "motion/icon.svg", "sha256": "0" * 64}]

        def fake_image(value: dict) -> None:
            value["proof"]["runtimeAttestation"]["imageId"] = "sha256:" + "1" * 64

        def empty_runtime(value: dict) -> None:
            value["proof"]["runtimeAttestation"]["containerBeforeOutput"] = {}

        cases = (impossible_occupancy, malformed_asset, unexpected_valid_asset,
                 fake_image, empty_runtime)
        for mutate in cases:
            value = self._value()
            mutate(value)
            self._rewrite_sidecar(value)
            with self.subTest(case=mutate.__name__), self.assertRaises(RuntimeError):
                self._validate(value)

    def test_same_inode_overwrite_after_hash_is_rejected(self) -> None:
        value = self._value()
        media = value["path"]
        real_stat = os.stat
        mutated = False

        def raced(path, *args, **kwargs):
            nonlocal mutated
            if not mutated and kwargs.get("dir_fd") is not None \
                    and path == os.path.basename(media):
                with open(media, "wb") as handle:
                    handle.write(b"WRONG-BYTES")
                os.chmod(media, 0o600)
                mutated = True
            return real_stat(path, *args, **kwargs)

        with mock.patch("headless.render_lane.os.stat", side_effect=raced), \
                self.assertRaisesRegex(RuntimeError, "changed during validation"):
            self._validate(value)
        self.assertEqual(Path(media).read_bytes(), b"WRONG-BYTES")


if __name__ == "__main__":
    unittest.main(verbosity=2)
