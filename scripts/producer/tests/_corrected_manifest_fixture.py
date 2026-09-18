"""TEST ONLY simulated boundary reviews; fake decoded media, real file authority."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from _timing_correction_fixture import TimingCorrectionFixture
from publish_corrected_transcript_manifest import execute as publish
from transcript_timing_correction import execute
from transcript_timing_correction_authority import CorrectionInput


class CorrectedManifestFixture(TimingCorrectionFixture):
    """Small admitted byte fixture; never evidence of speech or actual listening."""

    def __init__(self) -> None:
        """Reuse the honest16second TEST admission and propose two boundaries."""
        super().__init__()
        self.inputs = CorrectionInput(self.plan, self.manifest, self.transcript)
        self.proposed = {
            "schemaVersion": 1, "operation": "propose-source-word-timing-correction",
            "requestId": str(uuid4()), "sourceId": "raw-1",
            "expectedPlanSha256": self.sha(self.plan),
            "expectedManifestSha256": self.sha(self.manifest),
            "expectedTranscriptSha256": self.sha(self.transcript),
            "corrections": [{"sourceWordIndex": 0, "newStart": 8.4, "newEnd": 8.64},
                            {"sourceWordIndex": 1, "newStart": 13.4, "newEnd": 13.62}],
        }
        self.originals = {path: path.read_bytes() for path in (self.plan, self.manifest, self.transcript, self.media)}
        self.target = self.manifest.parent / f"asset_manifest.timing-{self.proposed['requestId']}.json"

    @staticmethod
    def sha(path: Path) -> str:
        """Hash tiny test bytes only; production source observation is separate."""
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def commit(self) -> dict:
        """Submit conspicuously simulated test-only boundary attestations."""
        prepared = execute("prepare", self.inputs, self.proposed)
        request = prepared["request"]
        text_review = self.proposed["schemaVersion"] == 2
        compared = ({"comparedOriginalAndProposedText": True, "confirmsSourceFaithfulTranscription": True}
                    if text_review else {"comparedOriginalAndProposedBounds": True})
        reviews = [{"correctionHash": row["correctionHash"],
                    "listenedToSourceWindows": [{"windowHash": window["windowHash"], "listened": True}
                                               for window in row["sourceWindows"]],
                    **compared,
                    "rationale": "TEST ONLY simulated boundary decision; no person listened."}
                   for row in request["corrections"]]
        operation = "record-source-word-text-correction" if text_review else "record-source-word-timing-correction"
        sent = {"schemaVersion": self.proposed["schemaVersion"], "operation": operation,
                "requestHash": request["requestHash"], "idempotencyKey": str(uuid4()),
                "expectedRecordHash": None, "reviews": reviews}
        self.committed = execute("record", self.inputs, self.proposed, sent)
        revision = self.committed["revision"]
        self.publication = {"schemaVersion": 1, "operation": "publish-corrected-transcript-manifest",
                            "expectedRequestHash": request["requestHash"],
                            "expectedRecordHash": revision["recordHash"],
                            "expectedCorrectedTranscriptSha256": revision["sha256"]}
        return self.committed

    def publish(self, command: str = "publish") -> dict:
        """Invoke the real publisher with TEST-only committed review data."""
        return publish(command, self.inputs, self.proposed, self.publication)

    def revised(self) -> dict:
        """Read the new small manifest without replacing its original."""
        return json.loads(self.target.read_text())
