"""TEST ONLY fake decoded authority, real local byte/hash/store cut-gate fixture."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
from uuid import uuid4

from _ingest_admission_fixture import runner
from ingest_admission import admit_ingest_candidates, collect_ingest_candidates
from transcript_source_authority import bind_result, observe_source
from transcript_cut_contract import check
from transcript_timing_review import execute
from test_transcript_cut_timing_review import _plan, _transcript


class TimingReviewFixture:
    """Never claims a decoder, real speech, or a human actually ran."""

    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="sniper-timing-review-test-")
        self.root = Path(self.tmp.name).resolve()
        producer = self.root / "producer"
        producer.mkdir()
        media = self.root / "TEST-NOT-REAL-MEDIA.mp4"
        media.write_bytes(b"TEST ONLY fake media authority; no actual decoder.\n" * 1024)
        source = self.root / "source"
        admission = admit_ingest_candidates(collect_ingest_candidates([media], None, None), source, runner)
        row = admission.media_by_original[str(media)]
        self.media = Path(row.snapshot_path)
        self.transcript = source / "raw.transcript.json"
        observed = observe_source(self.media, (row.sha256, row.size_bytes))
        self.transcript.write_text(json.dumps(bind_result(_transcript(), observed)))
        self.manifest = source / "asset_manifest.json"
        self.manifest.write_text(json.dumps({"sourceSetAdmission": admission.binding,
            "sources": [{"id": "raw-1", "duration": 16, "path": row.snapshot_path,
                         "originalPath": str(media), "sourceSha256": row.sha256,
                         "sourceSizeBytes": row.size_bytes, "transcriptPath": self.transcript.name,
                         "admissionReceiptPath": row.receipt_path,
                         "admissionReceiptSha256": row.receipt_sha256}]}))
        self.plan = producer / "edit_plan.json"
        self.plan.write_text(json.dumps(_plan(13.62)))
        self.paths = (str(self.plan), str(source), str(self.manifest))

    def close(self) -> None:
        self.tmp.cleanup()

    def check(self) -> dict:
        return check(*self.paths)

    def prepare(self) -> dict:
        return execute("prepare", self.paths)

    def record(self, sent: dict) -> dict:
        return execute("record", self.paths, sent)

    def submission(self, prepared: dict, resolved: bool = True) -> dict:
        request = prepared["request"]
        reviews = []
        for row in request["anomalies"]:
            disposition = "kept-audited" if row["finding"]["position"] == "kept_opening" \
                else "excluded-abandoned-start-audited"
            reviews.append({"anomalyHash": row["anomalyHash"], "sourceWindows": row["sourceWindows"],
                            "disposition": disposition if resolved else "unresolved",
                            "listenedToSourceWindows": [{"windowHash": window["windowHash"], "listened": resolved}
                                                        for window in row["sourceWindows"]],
                            "comparedExactCutBoundary": resolved,
                            "rationale": "TEST ONLY simulated operator submission, not actual human review."})
        return {"schemaVersion": 1, "operation": "record-source-timing-review",
                "requestHash": request["requestHash"], "idempotencyKey": str(uuid4()),
                "expectedPreviousDecisionHash": prepared["review"]["decisionHash"], "reviews": reviews}
