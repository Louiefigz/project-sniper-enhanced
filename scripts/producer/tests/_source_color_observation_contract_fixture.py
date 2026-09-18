"""Fabricated data-only section/input records; no file, admission or worker claim.

Even the OpeningInputs/capture dataclasses below are synthetic parser inputs.
Their SHA/stat spellings authenticate nothing. No live observation owner is
created and no bytes, native tool, source, receipt or clock are accessed.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path

from _source_color_staging_fixture import reference, selection, staging_fixture
from color.grade_bt709_identity import Bt709IdentityMetadata
from cut_preview_io import digest
from guided_opening_inputs import DOCUMENTS, OpeningInputs
from headless.external_media_verification import VerifiedSnapshotIdentity
from ingest_media_observation import VerifiedExecutionMedia


class ObservationContractFixture:
    """Independent literal TEST data for the pure section validation boundary."""

    def __init__(self) -> None:
        """Build two sources in first-kept order, deliberately different from map order."""
        self.sidecar, self.reservation = staging_fixture()
        self.sidecar["sourceColor"]["declarations"]["raw-b"] = selection("raw-b", False)
        self.reservation["sourceColorHash"] = digest(self.sidecar["sourceColor"])
        self.manifest, self.entries, self.snapshots = {"sources": []}, [], []
        for index, job in enumerate(self.sidecar["jobs"], 2):
            self._source(job["sourceId"], str(index) * 64)
        self.inputs = self._inputs()
        self.section = self._section()

    def _source(self, source_id: str, sha: str) -> None:
        """Use impossible TEST paths and explicitly invented metadata identities."""
        path = f"{self.sidecar['producerDir']}/.sniper-external-media/{sha}.media"
        original = f"/TEST/ingress/{source_id}.mp4"
        receipt_sha = "6" * 64
        receipt = f".sniper-external-media/receipts/{receipt_sha}.json"
        self.entries.append({"lane": "source", "originalPath": original, "snapshotPath": path,
            "sha256": sha, "sizeBytes": 4096, "mediaKind": "timed-media",
            "admissionReceiptPath": receipt, "admissionReceiptSha256": receipt_sha})
        self.manifest["sources"].append({"id": source_id, "originalPath": original, "path": path,
            "sourceSha256": sha, "sourceSizeBytes": 4096, "frameRate": "24/1", "vfr": False,
            "admissionReceiptPath": receipt, "admissionReceiptSha256": receipt_sha})
        self.snapshots.append(VerifiedSnapshotIdentity(path, sha, 4096, (1, 2, 0o100400, 501, 20, 1, 4096, 3, 4)))

    def _inputs(self) -> OpeningInputs:
        """Populate the original fourteen document slots without claiming their approval."""
        refs = {name: {"path": f"{self.sidecar['producerDir']}/{name}.json", "sha256": "5" * 64} for name in DOCUMENTS}
        opening = self.sidecar["opening"]
        value = {"schemaVersion": 1, "kind": "guided-opening-media-input", "executionId": opening["executionId"],
                 "profile": "unity-source-float-own-screen-v1", "documents": refs, "pipeline": {"TEST": "data only"}}
        value["executionInputHash"] = digest(value)
        opening["executionInputHash"] = value["executionInputHash"]
        self.reservation["opening"] = deepcopy(opening)
        cuts = [{"sourceId": name} for name in ("raw-b", "raw-a", "raw-b")]
        documents = {name: {"TEST": "not independently admitted documents"} for name in DOCUMENTS}
        documents.update(acceptedPlan={"cutTrack": cuts}, candidatePlan={"cutTrack": deepcopy(cuts),
            "target": {"mode": "longform"}, "reframe": {"strategy": "none"}}, manifest=self.manifest,
            authority={key: opening[key] for key in ("clockHash", "generationStartedAt")})
        capture = VerifiedExecutionMedia(json.dumps(self.entries).encode(), tuple(self.snapshots))
        return OpeningInputs(Path(opening["inputPath"]), opening["inputSha256"], value, documents, capture)

    def _row(self, index: int, job: dict) -> dict:
        """Invent normalized record assertions; none are outputs from an actual decoder."""
        entry = self.entries[index]
        selected = deepcopy(self.sidecar["sourceColor"]["declarations"][job["sourceId"]])
        artifacts = {key: deepcopy(job[key]) for key in ("input", "implementation", "launchClaim")}
        artifacts.update({key: reference(f"{job['directory']}/{path}") for key, path in
            (("parents", "parents.json"), ("execution", "execution/execution.json"),
             ("probe", "execution/result/probe.json"), ("frames", "execution/result/frames.ffprobe"),
             ("observation", "observation.json"))})
        return {"sourceId": job["sourceId"], "jobId": job["jobId"], "selection": selected,
            "source": {"path": entry["snapshotPath"], "sha256": entry["sha256"], "sizeBytes": entry["sizeBytes"]},
            "binding": {"sourceId": job["sourceId"], "sourceSha256": entry["sha256"],
                "admissionReceiptSha256": entry["admissionReceiptSha256"], "declarationSha256": digest(selected["declaration"]),
                "projectHistorySha256": "7" * 64, "fps": "24", "frameCount": 48}, "artifacts": artifacts,
            "records": {"policy": "sniper-private-grade-frame-records-v2", "sha256": "8" * 64, "decodedFrames": 48,
                "firstPts": 0, "timeBase": "1/24000", "stepTicks": 1000, "width": 32, "height": 18},
            "bt709Identity": asdict(Bt709IdentityMetadata("h264", "left", "1:1", 48)),
            "timing": {"sourceId": job["sourceId"], "startedMs": index * 100, "elapsedMs": 100,
                       "status": "complete", "cleanupVerified": True}}

    def _section(self) -> dict:
        """Mirror only the live projector's JSON shape and honest false flags."""
        return {"schemaVersion": 1, "kind": "guided-opening-source-color-observation-section",
            "scope": "actual-live-observations-not-base-consumption-or-media-approval",
            "processInput": {"schemaVersion": 1, "kind": "guided-opening-source-color-process-input",
                "scope": "explicit-staged-input-not-observation-cleanup-or-approval",
                "input": reference(self.reservation["sidecarPath"]), "reservation": deepcopy(self.sidecar["reservation"]),
                "sourceColorHash": digest(self.sidecar["sourceColor"])}, "opening": deepcopy(self.sidecar["opening"]),
            "parents": deepcopy(self.sidecar["expected"]), "sources": [self._row(i, job) for i, job in enumerate(self.sidecar["jobs"])],
            "elapsedMs": 200, "gamutMeasured": False, "gradeApplied": False, "basePictureObserved": False,
            "openingApproved": False, "deliveryApproved": False}
