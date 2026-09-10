"""Inert project-authority fixture; mocked ingest is NEVER a real media proof."""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace
from fractions import Fraction

from cut_preview_io import file_hash, write_new


class GradeProjectFixture:
    """Real private files with explicit fake admission for unit-only fault tests."""

    def __init__(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="grade-project-unit-")
        self.root = Path(self.temporary.name).resolve()
        self.producer = self.root / "producer"
        self.producer.mkdir(mode=0o700)
        store = self.producer / ".sniper-external-media"
        store.mkdir(mode=0o700)
        (store / "receipts").mkdir(mode=0o700)
        source = store / "source.media"
        source.write_bytes(b"inert-unit-test-media")
        receipt = store / "receipts/receipt.json"
        write_new(receipt, {"decoded": {"facts": {"mediaKind": "timed-media", "videoStreams": 1, "declaredFrames": 180}}})
        self.entry = {"lane": "source", "originalPath": str(self.root / "original.mp4"),
            "snapshotPath": str(source), "sha256": file_hash(source),
            "admissionReceiptPath": str(receipt.relative_to(self.producer)), "admissionReceiptSha256": file_hash(receipt)}
        self.source = {"id": "raw-1", "originalPath": self.entry["originalPath"], "path": str(source),
                       "vfr": False, "frameRate": "2/1", "fps": 2.0}
        write_new(self.root / "project.json", {"history": [], "syntheticTestOnly": True})
        write_new(self.producer / "edit_plan.json", {"cutTrack": [{"sourceId": "raw-1", "start": 60, "end": 70}]})
        write_new(self.producer / "asset_manifest.json", {"sources": [self.source], "sourceSetAdmission": {"inertTestOnly": True}})
        self.job = self.producer / ".sniper-grade-observations" / str(uuid.uuid4())
        self.job.mkdir(parents=True, mode=0o700)
        declaration = {"schemaVersion": 1, "sourceId": "raw-1", "sourceProfile": "bt709-sdr", "cameraProfile": None,
            "historyState": "known", "transformHistory": [], "lightingGroups": [{"id": "whole", "startFrame": 0,
                "endFrame": 180, "intent": "unknown", "description": "Unit test only; no grading"}]}
        self.value = {"schemaVersion": 1, "policy": "sniper-private-project-source-observation-v1",
            "jobId": self.job.name, "producerDir": str(self.producer), "sourceId": "raw-1", "declaration": declaration,
            "ownerPid": os.getppid(), "implementationSha256": "a" * 64,
            "expected": {"planSha256": file_hash(self.producer / "edit_plan.json"),
                "manifestSha256": file_hash(self.producer / "asset_manifest.json"), "projectSha256": file_hash(self.root / "project.json")}}
        write_new(self.job / "input.json", self.value)

    def manifest(self, changes: dict) -> None:
        """Mutate only this owned inert fixture and refresh its expected hash."""
        self.source.update(changes)
        path = self.producer / "asset_manifest.json"
        path.write_text(json.dumps({"sources": [self.source], "sourceSetAdmission": {"inertTestOnly": True}}))
        self.value["expected"]["manifestSha256"] = file_hash(path)

    def observation(self):
        """Fake return solely for adapter fault tests; never retained as real proof."""
        stream = SimpleNamespace(first_pts=0, time_base=Fraction(1, 2), step_ticks=1, width=160, height=90)
        records = SimpleNamespace(stream=stream, decoded_record_count=180, records_sha256="c" * 64)
        return SimpleNamespace(records=records, raw_frames_sha256="d" * 64, execution_sha256="e" * 64)

    def cleanup(self) -> None:
        self.temporary.cleanup()
