"""Inert original files + actual hash-pass capture; admission decoder is TEST-stubbed.

The reused ingest runner fabricates admission metadata for parser tests only.
No isolated admission, original-source color observation, lease or media runs.
"""
from __future__ import annotations

import hashlib
import tempfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

from _ingest_admission_fixture import runner
from cut_preview_io import file_hash, write_new
from guided_opening_inputs import OpeningInputs
from guided_source_color_preparation import SourceColorParentRefs, SourceColorPreparationContext
from headless.external_media_snapshot import ExternalMediaSnapshot, observe_external_media_snapshot
from headless.external_media_verification import SourceVerificationRuntime
from ingest_admission_io import canonical_bytes
from ingest_media_observation import SourceVerificationCapture


class SourceColorPreparationFixture:
    """Two inert sources, repeated cuts, real private metadata and original source identities."""

    def __init__(self) -> None:
        """Create only this canonical temporary tree; callbacks never touch dependencies."""
        self.temporary = tempfile.TemporaryDirectory(prefix="source-color-preparation-TEST-")
        self.root = Path(self.temporary.name).resolve()
        self.producer = self.root / "producer"
        self.producer.mkdir(mode=0o700)
        self.store = self.producer / ".sniper-external-media"
        (self.store / "receipts").mkdir(parents=True, mode=0o700)
        self.rows, self.entries, self.receipts = [], [], {}
        for source_id in ("raw-a", "raw-b"):
            self._add(source_id)
        self.plan = {"cutTrack": [{"sourceId": name, "start": 0, "end": 0.25} for name in ("raw-b", "raw-a", "raw-b")]}
        self.manifest = {"sources": self.rows, "sourceSetAdmission": {"TEST": "stubbed admission; not real decoder authority"}}
        self.project = {"history": [{"action": "TEST explicit project history"}]}
        self.declarations = {name: self.declaration(name) for name in ("raw-a", "raw-b")}
        self.guard = Mock()
        self.inputs = None
        self.context = None
        self.refresh()

    def _add(self, source_id: str) -> None:
        """Use the existing metadata-only TEST admission runner, never a media tool."""
        original = self.root / f"{source_id}.mp4"
        original.write_bytes(f"TEST inert source {source_id}".encode())
        receipt = runner(str(original), str(self.store))
        self.receipts[source_id] = receipt
        source = receipt["snapshot"]
        entry = {"lane": "source", "originalPath": str(original), "snapshotPath": source["path"],
            "sha256": source["sha256"], "sizeBytes": source["sizeBytes"], "mediaKind": "timed-media"}
        row = {"id": source_id, "originalPath": str(original), "path": source["path"],
            "sourceSha256": source["sha256"], "sourceSizeBytes": source["sizeBytes"],
            "frameRate": "24/1", "fps": 24, "vfr": False, "duration": 1, "resolution": [32, 18]}
        self.entries.append(entry)
        self.rows.append(row)

    @staticmethod
    def declaration(source_id: str) -> dict:
        """Explicit TEST context; no inferred camera, transform history or lighting."""
        return {"profile": None, "declaration": {"schemaVersion": 1, "sourceId": source_id,
            "sourceProfile": "bt709-sdr", "cameraProfile": None, "historyState": "known",
            "transformHistory": [], "lightingGroups": [{"id": "whole", "startFrame": 0,
                "endFrame": 24, "intent": "unknown", "description": "TEST explicit full-source declaration"}]}}

    def refresh(self) -> None:
        """Publish fresh TEST parent/receipt bytes and perform actual tiny same-hash capture."""
        for row, entry in zip(self.rows, self.entries):
            raw = canonical_bytes(self.receipts[row["id"]])
            sha = hashlib.sha256(raw).hexdigest()
            relative = f".sniper-external-media/receipts/{sha}.json"
            (self.producer / relative).write_bytes(raw)
            row.update(admissionReceiptPath=relative, admissionReceiptSha256=sha)
            entry.update(admissionReceiptPath=relative, admissionReceiptSha256=sha)
        paths = {"planSha256": self.producer / "edit_plan.json", "manifestSha256": self.producer / "asset_manifest.json",
                 "projectSha256": self.root / "project.json"}
        for key, value in zip(paths, (self.plan, self.manifest, self.project)):
            raw = canonical_bytes(value)
            paths[key].write_bytes(raw)
        expected = {key: file_hash(path) for key, path in paths.items()}
        self.context = SourceColorPreparationContext(SourceColorParentRefs(self.producer, expected), 1300.0, self.guard)
        runtime = SourceVerificationRuntime(lambda: 300.0)
        capture = SourceVerificationCapture(runtime)
        for entry in self.entries:
            capture.add(observe_external_media_snapshot(ExternalMediaSnapshot(
                entry["snapshotPath"], entry["sha256"], entry["sizeBytes"], 0, 0), runtime))
        captured = capture.finish(self.entries)
        value = {"TEST": "not a 14-document admission", "documents": {"manifest": {
            "path": str(paths["manifestSha256"]), "sha256": expected["manifestSha256"]}},
            "pipeline": {"TEST": "tool identity is held by original caller guard"}}
        documents = {"acceptedPlan": deepcopy(self.plan), "candidatePlan": deepcopy(self.plan), "manifest": deepcopy(self.manifest)}
        input_path = self.root / "TEST-opening-input.json"
        if input_path.exists():
            input_path.unlink()
        write_new(input_path, value)
        self.inputs = OpeningInputs(input_path, file_hash(input_path), value, documents, captured)

    def cleanup(self) -> None:
        """Remove only this fixture's own temporary directory."""
        self.temporary.cleanup()
