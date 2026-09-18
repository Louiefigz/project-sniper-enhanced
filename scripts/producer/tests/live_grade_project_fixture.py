"""Opt-in new truly admitted synthetic project for full-source service tests.

This creates no final/render approval. Host FFmpeg only constructs tiny test
media; actual admission and observation use the existing attested OCI image.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cut_preview_io import write_new
from ingest_admission import IngressCandidate, admit_ingest_candidates
from live_color_diagnostic_acceptance import _admit, _synthetic_source


def create_fixture() -> Path:
    """Retain a fresh small full-source candidate; never alter earlier fixtures."""
    workspace = Path(tempfile.mkdtemp(prefix="sniper-grade-project-live-", dir="/private/tmp"))
    project = workspace / "synthetic"
    project.mkdir(mode=0o700)
    producer = project / "producer"
    producer.mkdir(mode=0o700)
    original = project / "synthetic-dark-then-light.mp4"
    _synthetic_source(original)
    admitted = admit_ingest_candidates([IngressCandidate(original, "source")], producer, _admit)
    media = admitted.media_by_original[str(original)]
    source = {"id": "raw-1", "path": media.snapshot_path, "originalPath": media.original_path,
        "sourceSha256": media.sha256, "sourceSizeBytes": media.size_bytes,
        "admissionReceiptPath": media.receipt_path, "admissionReceiptSha256": media.receipt_sha256,
        "duration": 90, "fps": 2, "frameRate": "2/1", "vfr": False,
        "resolution": [160, 90], "audio": {"present": True}}
    write_new(producer / "asset_manifest.json", {"sources": [source], "broll": [], "music": [], "sourceSetAdmission": admitted.binding})
    write_new(producer / "edit_plan.json", {"planVersion": 1, "target": {"mode": "short", "scope": "light"},
        "cutTrack": [{"sourceId": "raw-1", "start": 55, "end": 73}], "graphicsTrack": []})
    write_new(project / "project.json", {"origin": "raw", "history": [], "syntheticTestOnly": True})
    return producer


if __name__ == "__main__":
    started = time.monotonic()
    producer = create_fixture()
    print(json.dumps({"producerDir": str(producer), "setupAndAdmissionMs": round((time.monotonic() - started) * 1000),
                      "syntheticOnly": True, "noFinal": not (producer / "final.mp4").exists()}))
