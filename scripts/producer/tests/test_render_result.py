"""Controller-side render-result closure and race regressions."""
from __future__ import annotations

import hashlib
import os
import unittest
from pathlib import Path
from unittest import mock

from _render_result_fixture import HistoricalResultFixture


class RenderResultTests(HistoricalResultFixture):
    """Strict retained metadata checks; no executable R0 admission occurs."""

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
