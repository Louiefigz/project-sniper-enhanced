"""Approval-time byte revalidation for Desktop Palmier QC."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from _common import *  # noqa: F401,F403
from fingerprints import file_sha256
from palmier.desktop_authority import approve
from palmier.desktop_quality import qc_authority
from palmier.desktop_state import now, save_state
from palmier.editable_parity_contract import receipt_path as parity_path
from palmier.mcp_client import PalmierError
from palmier.native_qc_contract import audit_path, export_path, stable_hash


class DesktopQcClosureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.out = os.path.join(self.temp.name, "out")
        self.repo = os.path.join(self.temp.name, "repo")
        os.makedirs(self.out)
        os.makedirs(self.repo)
        self.fingerprint = "f" * 64
        audio = {
            "schemaVersion": 1, "kind": "palmier-audio-authority",
            "mode": "mastered-stereo", "status": "pass",
            "candidateFingerprint": self.fingerprint, "routes": [],
        }
        self.audio = {**audio, "digest": stable_hash(audio)}
        self.state = self._state()
        self.reviews = self._write("reviews.json", {})

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write(self, name: str, value: object) -> str:
        path = os.path.join(self.out, name)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(value, handle)
        return path

    def _ref(self, name: str, value: object) -> dict:
        path = self._write(name, value)
        return {"path": path, "hash": file_sha256(path)}

    def _state(self) -> dict:
        return {
            "schemaVersion": 1, "kind": "palmier-desktop-authority",
            "status": "review-required", "outDir": self.out,
            "expectedFingerprint": self.fingerprint,
            "plan": self._ref("plan.json", {"planVersion": 2}),
            "manifest": self._ref("manifest.json", {"sources": []}),
            "gates": self._ref("gates.json", {"ok": True}),
            "operations": self._ref("operations.json", {
                "steps": [], "capability": {"audioAuthority": {
                    "schemaVersion": 1, "mode": "mastered-stereo",
                    "status": "ready", "blockerCode": None,
                }},
            }),
            "journalPath": self._write("journal.json", {}),
            "updatedAt": now(),
        }

    def _export(self, present: bool = True) -> dict:
        path = export_path(self.out)
        if present:
            with open(path, "wb") as handle:
                handle.write(b"candidate-export")
        digest = file_sha256(path) if present else "e" * 64
        return {
            "path": path, "hash": digest, "audioPresent": True,
            "audioStreamCount": 1, "videoStreamCount": 1,
            "fullDecode": "ffmpeg-xerror-av-v1",
            "audioRouteAuthority": self.audio,
        }

    def _audit(self, authority: dict, export: dict,
               parity: bool = False) -> dict:
        checks = []
        if parity:
            checks.append({
                "name": "editable_master_parity", "status": "pass",
                "measured": "p" * 64,
                "evidence": {
                    "path": parity_path(self.out), "hash": "p" * 64,
                },
            })
        content = {
            "schemaVersion": 1, "stage": "palmier-native-audit",
            "candidateFingerprint": self.fingerprint,
            "exportHash": export["hash"],
            "inputAuthorityDigest": authority["inputDigest"],
            "checks": checks, "frames": [],
        }
        artifact = {
            **content, "status": "pass", "digest": stable_hash(content),
        }
        path = audit_path(self.out)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(artifact, handle)
        return {
            **artifact, "auditPath": path, "auditHash": file_sha256(path),
            "auditedAt": now(),
        }

    def _approve(self) -> None:
        save_state(self.repo, self.state)
        found = SimpleNamespace(fingerprint=self.fingerprint)
        with patch("palmier.desktop_authority._assert_head",
                   return_value=found), patch(
                       "palmier.desktop_quality.require_audio_authority",
                       return_value=self.audio):
            approve(None, self.repo, self.reviews)

    def test_missing_export_cannot_be_approved_from_state_hashes(self) -> None:
        authority = qc_authority(self.state)
        self.state["qc"] = {
            "authority": authority, "export": self._export(False), "audit": {},
            "audioRouteAuthority": self.audio,
        }
        with self.assertRaisesRegex(PalmierError, "export bytes changed"):
            self._approve()

    def test_mutated_audit_file_cannot_be_approved(self) -> None:
        authority = qc_authority(self.state)
        export = self._export()
        audit = self._audit(authority, export)
        self.state["qc"] = {
            "authority": authority, "export": export, "audit": audit,
            "audioRouteAuthority": self.audio,
        }
        with open(audit["auditPath"], "a", encoding="utf-8") as handle:
            handle.write(" ")
        with self.assertRaisesRegex(PalmierError, "audit artifact changed"):
            self._approve()

    def test_missing_parity_receipt_blocks_desktop_approval(self) -> None:
        authority = qc_authority(self.state)
        export = self._export()
        audit = self._audit(authority, export, parity=True)
        self.state["qc"] = {
            "authority": authority, "export": export, "audit": audit,
            "audioRouteAuthority": self.audio,
        }
        with patch("palmier.native_qc.master_authority_hash",
                   return_value="m" * 64), self.assertRaisesRegex(
                       PalmierError, "cannot read Palmier editable parity"):
            self._approve()

    def test_missing_audio_route_receipt_blocks_desktop_approval(self) -> None:
        authority = qc_authority(self.state)
        export = self._export()
        export.pop("audioRouteAuthority")
        audit = self._audit(authority, export)
        self.state["qc"] = {
            "authority": authority, "export": export, "audit": audit,
            "audioRouteAuthority": self.audio,
        }
        with self.assertRaisesRegex(
                PalmierError, "no audio-route authority receipt"):
            self._approve()


if __name__ == "__main__":
    unittest.main(verbosity=2)
