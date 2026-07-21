"""Trusted request-artifact identity and selection regressions."""
from __future__ import annotations

import dataclasses
import os
import tempfile
import unittest
from pathlib import Path

from _common import pl  # noqa: F401
from headless.request_artifact import (
    RequestArtifactLocator,
    load_request_artifact,
    select_overlay,
    store_request_artifact,
)


def _entry(label: str = "A") -> dict:
    return {"kind": "section-marker", "outStart": 0, "outEnd": 2.5,
            "anchor": "free-band", "spec": {
                "num": "System No.1", "line1": label,
                "line2": "Rule", "side": "left", "accent": "#054BC9"}}


def _request(label: str = "A") -> dict:
    return {"schemaVersion": 1, "operation": "render-overlays",
            "overlays": [{"overlayId": "overlay-1", "entry": _entry(label)}]}


class RequestArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.authority = Path(self.temp.name).resolve() / "authority"
        self.authority.mkdir(mode=0o700)
        os.chmod(self.authority, 0o700)

    def test_content_addressed_round_trip_and_caller_mutation(self) -> None:
        request = _request()
        first = store_request_artifact(str(self.authority), request)
        request["overlays"][0]["entry"]["spec"]["line1"] = "MUTATED"
        second = store_request_artifact(str(self.authority), _request())
        self.assertEqual(first, second)
        selected = select_overlay(str(self.authority), first, "overlay-1")
        self.assertEqual(selected.entry["spec"]["line1"], "A")

    def test_different_selected_entry_changes_request_digest(self) -> None:
        first = store_request_artifact(str(self.authority), _request("A"))
        second = store_request_artifact(str(self.authority), _request("B"))
        self.assertNotEqual(first.request_digest, second.request_digest)

    def test_unknown_fields_duplicate_ids_and_nonfinite_values_reject(self) -> None:
        unknown = {**_request(), "ambient": True}
        duplicate = _request()
        duplicate["overlays"].append(duplicate["overlays"][0])
        nonfinite = _request()
        nonfinite["overlays"][0]["entry"]["outEnd"] = float("nan")
        for value in (unknown, duplicate, nonfinite):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                store_request_artifact(str(self.authority), value)

    def test_tamper_symlink_hardlink_and_wrong_mode_fail_closed(self) -> None:
        locator = store_request_artifact(str(self.authority), _request())
        path = Path(locator.path)
        path.chmod(0o600)
        path.write_bytes(b"{}\n")
        with self.assertRaisesRegex(RuntimeError, "digest mismatch"):
            load_request_artifact(str(self.authority), locator)

        other = store_request_artifact(str(self.authority), _request("B"))
        other_path = Path(other.path)
        alias = other_path.with_name("alias.json")
        os.link(other_path, alias)
        with self.assertRaises(RuntimeError):
            load_request_artifact(str(self.authority), other)
        alias.unlink()
        other_path.chmod(0o644)
        with self.assertRaises(RuntimeError):
            load_request_artifact(str(self.authority), other)

    def test_locator_path_and_selection_are_not_caller_substitutable(self) -> None:
        locator = store_request_artifact(str(self.authority), _request())
        forged = RequestArtifactLocator(
            str(self.authority / "requests" / "elsewhere.json"),
            locator.request_digest)
        with self.assertRaisesRegex(RuntimeError, "locator"):
            load_request_artifact(str(self.authority), forged)
        with self.assertRaisesRegex(RuntimeError, "absent"):
            select_overlay(str(self.authority), locator, "overlay-2")

    def test_public_locator_has_no_entry_or_free_digest_fields(self) -> None:
        names = {field.name for field in dataclasses.fields(RequestArtifactLocator)}
        self.assertEqual(names, {"path", "request_digest"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
