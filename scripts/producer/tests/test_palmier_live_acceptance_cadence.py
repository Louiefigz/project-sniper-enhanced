"""Fail-closed long-form normalized cadence authority tests."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from _common import *  # noqa: F401,F403
from fingerprints import file_sha256
from palmier.live_acceptance_cadence import verify_longform_cadence
from palmier.mcp_client import PalmierError


class CadenceFixture:
    """Small byte-real fixture with mocked trusted stream evidence."""

    def __init__(self, root: str):
        self.root = Path(root)
        self.normalized = self.root / "normalized.mp4"
        self.admitted = self.root / "admitted.media"
        self.approval = self.root / "cadence.json"
        self.plan_path = self.root / "plan.json"
        self.manifest_path = self.root / "manifest.json"
        self.normalized.write_bytes(b"normalized-edit-time-media")
        self.admitted.write_bytes(self.normalized.read_bytes())
        self.approval.write_bytes(b"approval")
        self.digest = file_sha256(str(self.normalized))
        self.approval_digest = "a" * 64
        self.plan = {"cutTrack": [{
            "sourceId": "raw-1", "start": 0.0, "end": 1.0,
            "rationale": "keep one complete normalized phrase",
        }], "cutDecisions": {"schemaVersion": 1, "removals": []}}
        self.manifest = {"sources": [{
            "id": "raw-1", "path": str(self.admitted),
            "sourceSha256": self.digest, "duration": 1.0,
            "transcriptPath": "raw-1.transcript.json",
        }]}
        self.plan_path.write_text(json.dumps(self.plan))
        self.manifest_path.write_text(json.dumps(self.manifest))
        self.paths = {
            "plan": str(self.plan_path),
            "manifest": str(self.manifest_path),
        }
        self.config = SimpleNamespace(
            format="long", fps=24, out_dir=root, transcripts_dir=root,
            cadence_approval_path=str(self.approval),
            cadence_approval_digest=self.approval_digest,
        )

    def document(self) -> dict:
        size = self.normalized.stat().st_size
        return {
            "approvalDigest": self.approval_digest,
            "media": {
                "source": {"sha256": "b" * 64},
                "normalized": {
                    "path": str(self.normalized), "sha256": self.digest,
                    "sizeBytes": size, "video": {"rate": "24/1"},
                    "audio": {"sampleRate": 48000},
                },
            },
            "downstreamTimeAuthority": {
                "mediaPath": str(self.normalized),
                "mediaSha256": self.digest,
                "transcriptAndCutsMustBindThisAsset": True,
                "rawSourceIsNotEditTimeAuthority": True,
            },
        }

    def transcript_receipt(self) -> dict:
        return {
            "planHash": "1" * 64, "manifestHash": "2" * 64,
            "transcriptDigest": "3" * 64, "cutTrackDigest": "4" * 64,
            "cutDecisionsDigest": "5" * 64,
        }

    def manifestation(self) -> dict:
        return {
            "receiptHash": "6" * 64, "timelineMapSha256": "7" * 64,
            "planCutTrackHash": "4" * 64,
            "parts": [{"sourceId": "raw-1"}],
        }


class LongCadenceAuthorityTests(unittest.TestCase):
    def _verify(self, fixture: CadenceFixture) -> dict:
        patches = (
            patch(
                "palmier.live_acceptance_cadence.verify_cadence_approval",
                return_value=fixture.document()),
            patch(
                "palmier.live_acceptance_cadence."
                "verify_execution_media_authority", return_value=True),
            patch(
                "palmier.live_acceptance_cadence.check_transcript_cuts",
                return_value={"ok": True, "errors": [], "metrics": {
                    "receipt": fixture.transcript_receipt()}}),
            patch(
                "palmier.live_acceptance_cadence.verify_manifestation",
                return_value=fixture.manifestation()),
        )
        with patches[0], patches[1], patches[2], patches[3]:
            return verify_longform_cadence(
                fixture.config, fixture.paths,
                fixture.plan, fixture.manifest)

    def test_exact_normalized_asset_binds_manifest_transcript_plan_and_cut(self):
        with tempfile.TemporaryDirectory() as root:
            fixture = CadenceFixture(root)
            result = self._verify(fixture)
        self.assertEqual(
            result["manifest"]["sourceSha256"], fixture.digest)
        self.assertEqual(
            result["normalizedMedia"]["sha256"], fixture.digest)
        self.assertEqual(result["cut"]["sourceIds"], ["raw-1"])

    def test_missing_or_tampered_approval_fails_before_chain_validation(self):
        cases = ("missing", "digest")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as root:
                fixture = CadenceFixture(root)
                if case == "missing":
                    fixture.config.cadence_approval_path = None
                else:
                    fixture.config.cadence_approval_digest = "c" * 64
                with self.assertRaisesRegex(PalmierError, "cadence approval"):
                    self._verify(fixture)

    def test_wrong_or_raw_manifest_media_cannot_enter_long_edit_chain(self):
        for value in ("0" * 64, "b" * 64):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as root:
                fixture = CadenceFixture(root)
                fixture.manifest["sources"][0]["sourceSha256"] = value
                with self.assertRaisesRegex(
                        PalmierError, "does not admit normalized"):
                    self._verify(fixture)

    def test_changed_normalized_media_fails_reobservation(self):
        with tempfile.TemporaryDirectory() as root:
            fixture = CadenceFixture(root)
            fixture.normalized.write_bytes(b"changed-after-approval")
            with self.assertRaisesRegex(
                    PalmierError, "normalized cadence media bytes changed"):
                self._verify(fixture)

    def test_short_rejects_accidental_long_authority(self):
        config = SimpleNamespace(
            format="short", cadence_approval_path="/tmp/cadence.json",
            cadence_approval_digest="a" * 64)
        with self.assertRaisesRegex(PalmierError, "short acceptance"):
            verify_longform_cadence(config, {}, {}, {})


if __name__ == "__main__":
    unittest.main()
