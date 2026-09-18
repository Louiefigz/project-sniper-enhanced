"""TEST-only fake-media admission with real byte/lineage correction transactions."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

from _ingest_admission_fixture import runner as admission_runner
from _timing_review_fixture import TimingReviewFixture
from transcript_source_authority import bind_result, observe_source
from transcript_timing_correction import execute
from transcript_timing_correction_authority import CorrectionInput


def correction_admission_runner(source: str, store: str) -> dict:
    """Fake 16-second decode facts matching this TEST transcript, not real media."""
    receipt = admission_runner(source, store)
    receipt["decoded"]["facts"].update(durationSeconds=16, declaredFrames=384)
    return receipt


class TimingCorrectionFixture(TimingReviewFixture):
    """Only synthetic metadata and tiny TEST bytes; never real human listening."""

    def __init__(self) -> None:
        with patch("_timing_review_fixture.runner", correction_admission_runner):
            super().__init__()
        self.inputs = CorrectionInput(self.plan, self.manifest, self.transcript)
        self.proposed = self.proposal()

    def proposal(self) -> dict:
        """Create explicit TEST boundary intent with separately held raw parent hashes."""
        return {"schemaVersion": 1, "operation": "propose-source-word-timing-correction",
                "requestId": str(uuid4()), "sourceId": "raw-1",
                "expectedPlanSha256": hashlib.sha256(self.plan.read_bytes()).hexdigest(),
                "expectedManifestSha256": hashlib.sha256(self.manifest.read_bytes()).hexdigest(),
                "expectedTranscriptSha256": hashlib.sha256(self.transcript.read_bytes()).hexdigest(),
                "corrections": [{"sourceWordIndex": 1, "newStart": 13.50, "newEnd": 13.62}]}

    def correct(self, command: str = "prepare", sent: dict | None = None) -> dict:
        """Invoke actual production transaction; no successful dependency stubs."""
        return execute(command, self.inputs, self.proposed, sent)

    def submission(self, prepared: dict) -> dict:
        """Explicitly simulated human attestations, never a creator consent record."""
        reviews = [{"correctionHash": row["correctionHash"],
                    "listenedToSourceWindows": [{"windowHash": window["windowHash"], "listened": True}
                                                for window in row["sourceWindows"]],
                    "comparedOriginalAndProposedBounds": True,
                    "rationale": "TEST ONLY simulated boundary decision, not actual human audition."}
                   for row in prepared["request"]["corrections"]]
        return {"schemaVersion": 1, "operation": "record-source-word-timing-correction",
                "requestHash": prepared["request"]["requestHash"], "idempotencyKey": str(uuid4()),
                "expectedRecordHash": None, "reviews": reviews}

    @property
    def correction_root(self) -> Path:
        """Read deterministic TEST artifact path without selecting any revision."""
        return self.manifest.parent / ".sniper-timing-corrections" / self.proposed["requestId"]

    def parent_inventory(self) -> dict[Path, bytes]:
        """Capture exact original documents and tiny admitted TEST source bytes."""
        return {path: path.read_bytes() for path in (self.plan, self.manifest, self.transcript, self.media)}

    def rebind_test_payload(self, payload: dict) -> None:
        """Set up a TEST parent class; never called against creator data."""
        source = json.loads(self.manifest.read_text())["sources"][0]
        payload.pop("sourceMediaAuthority", None)
        observed = observe_source(self.media, (source["sourceSha256"], source["sourceSizeBytes"]))
        self.transcript.write_text(json.dumps(bind_result(payload, observed)))
        self.proposed = self.proposal()
