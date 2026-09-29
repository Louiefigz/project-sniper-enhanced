"""Operational external origin bridge through ingest and native requests."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ingest
from _ingest_admission_fixture import probe as _probe
from _ingest_admission_fixture import runner as _runner
from ingest_admission import verify_source_set_binding


class ExternalOriginIngestTests(unittest.TestCase):
    def native_command(self, *arguments: str) -> dict:
        """Run the supported controller CLI and return its one JSON result."""
        repo = Path(ingest.__file__).resolve().parents[2]
        command = [shutil.which("node") or "node", "--import", "tsx",
                   str(repo / "scripts/producer/native-short.ts"), *arguments]
        result = subprocess.run(command, cwd=repo, capture_output=True,
                                text=True, check=False, timeout=60)
        if result.returncode != 0:
            raise RuntimeError(result.stderr)
        return json.loads(result.stdout)

    def origin_asset(self, directory: Path, disposition: str) -> Path:
        """Create a real controller origin and its standard sibling ASSET.json."""
        directory.mkdir(parents=True)
        media = directory / "capture.mp4"
        media.write_bytes(f"TEST {disposition} external media".encode())
        digest = hashlib.sha256(media.read_bytes()).hexdigest()
        asset = {"file": f"assets/{digest}.mp4", "path": str(media),
                 "sha256": digest, "role": "supporting-video"}
        record = {"schemaVersion": 1, "assetId": f"test-{disposition}",
                  "sha256": digest, "sizeBytes": media.stat().st_size,
                  "mime": "video/mp4", "origin": "operator-upload",
                  "acquiredAt": "2026-09-26T00:00:00Z",
                  "rights": {"license": "TEST controller-held local review",
                             "allowedUses": ["editorial"],
                             "allowedPlatforms": ["local-review"],
                             "consent": "unknown", "attributionRequired": False},
                  "media": {"width": 32, "height": 18, "durationFrames": 24},
                  "provenance": {"source": str(media)},
                  "publicationDisposition": disposition}
        request = directory / "origin-input.json"
        request.write_text(json.dumps({"asset": asset, "record": record,
          "acquisition": {"kind": "provided", "accessScope": "operator-private",
                          "evidence": [], "sourceFrameRate": "24/1"}}))
        bound = self.native_command(
            "origin", str(request), str(directory / "ASSET-ORIGIN.json"))
        (directory / "ASSET.json").write_text(json.dumps(bound))
        return media

    def build_manifest(self, root: Path, output: Path) -> dict:
        """Use real build_manifest orchestration with deterministic media probes."""
        with patch("ingest_admission.admit_external_media", side_effect=_runner), \
                patch("ingest_admitted_sources.probe_media", side_effect=_probe), \
                patch("ingest_admitted_scan.probe_media", side_effect=_probe), \
                patch("ingest.scan_builtin_music", return_value=[]):
            return ingest.build_manifest(root, output, no_transcribe=True)

    def request_external(self, root: Path, mode: str) -> list[dict]:
        """Prepare the supported Short or Long packet and return external rows."""
        intent = {"mode": mode, "scope": "produced", "lanes": {}}
        (root / "project.json").write_text(json.dumps({
            "origin": "raw", "history": [], "intent": intent,
            "visualPlanPolicy": {"schemaVersion": 1,
                                 "ordinaryAutoEdit": "required"}}))
        operation = "prepare" if mode == "short" else "prepare-longform"
        result = self.native_command(operation, str(root / "producer"))
        name = "SHORT-REQUEST.json" if mode == "short" else "LONG-REQUEST.json"
        packet = json.loads((Path(result["directory"]) / name).read_text())
        return packet["availableExternalMedia"]

    def assert_request_rows(self, rows: list[dict], paths: tuple[Path, ...]) -> None:
        """Both reviewed origin states are local-edit eligible; plain stays gated."""
        approved, pending, plain = paths
        inventory = {row["originalPath"]: row for row in rows}
        for source in [approved, pending]:
            self.assertEqual(inventory[str(source)]["availability"],
                             "controller-authorized-for-local-review")
        self.assertEqual(inventory[str(plain)]["availability"],
                         "prerequisite-awaiting-controller-authorization")

    def test_bridge_seals_origin_and_serves_short_and_long(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            output, external = root / "source", root / "external-media"
            (root / "take.mp4").write_bytes(b"video")
            approved = self.origin_asset(external / "approved", "approved")
            pending = self.origin_asset(external / "pending", "needs-review")
            plain = external / "plain" / "clip.mp4"
            plain.parent.mkdir(); plain.write_bytes(b"TEST plain prerequisite")
            manifest = self.build_manifest(root, output)
            by_original = {row["originalPath"]: row
                           for row in manifest["externalMedia"]}
            self.assertIsNotNone(by_original[str(approved)]["authorizationEvidence"])
            self.assertIsNotNone(by_original[str(pending)]["authorizationEvidence"])
            self.assertIsNone(by_original[str(plain)]["authorizationEvidence"])
            verify_source_set_binding(manifest, output)
            (output / "asset_manifest.json").write_text(json.dumps(manifest))
            (root / "producer").mkdir()
            paths = (approved, pending, plain)
            for mode in ["short", "longform"]:
                self.assert_request_rows(self.request_external(root, mode), paths)

            forged = json.loads(json.dumps(manifest))
            forged_row = next(row for row in forged["externalMedia"]
                              if row["originalPath"] == str(plain))
            forged_row["authorizationEvidence"] = \
                by_original[str(approved)]["authorizationEvidence"]
            (output / "asset_manifest.json").write_text(json.dumps(forged))
            with self.assertRaisesRegex(RuntimeError, "not controller-derived"):
                self.request_external(root, "short")

            (output / "asset_manifest.json").write_text(json.dumps(manifest))
            (external / "approved" / "ASSET-ORIGIN.json").write_text("{}")
            with self.assertRaisesRegex(RuntimeError, "origin inspection failed"):
                self.build_manifest(root, root / "tampered-output")


if __name__ == "__main__":
    unittest.main()
