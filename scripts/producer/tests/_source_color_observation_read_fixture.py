"""Actual bounded TEST files and source captures, fabricated native provenance.

The admission runner and all worker/isolation/network records are explicit
synthetic TEST data. Original hashes, stat holds, parents and complete metadata
replay are actual. No source decoder, daemon, owner factory or timer is used.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

from _source_color_preparation_fixture import SourceColorPreparationFixture
from _source_color_staging_fixture import planned_job
from _source_color_observation_read_records import execution_record, observation_record, raw_records
from color.grade_observation_profile import V1
from cut_preview_io import digest
from guided_opening_inputs import DOCUMENTS, OpeningInputs
from guided_source_color_observation_files import ColdSourceColorObservationContext
from guided_source_color_observation_pins import APPROVAL, STAGED_ROOTS, WORKER
from guided_source_color_observation_read import read_source_color_observations
from guided_source_color_preparation import prepare_source_color_jobs

REQUEST = "a8b9ce05-29ec-4bba-93cf-982d811ed137"
EXECUTION = "f612f0c0-bd72-4adf-96b9-50fbb55ef777"
JOBS = ("79c7d2a8-f1ae-4c74-8bfc-6b959b888211", "f9167c04-6047-4e0d-8979-ae08455e66bc")


class ColdObservationFixture(SourceColorPreparationFixture):
    """Two-source actual metadata reader fixture; literal records carry no native proof."""

    def __init__(self) -> None:
        """Build only named files below the exact canonical temporary root."""
        super().__init__()
        self.allowed: set[Path] = set()
        self.plan["target"] = {"mode": "longform"}
        self.refresh()
        self.execution = self.producer / "guided-v2-operations" / REQUEST / "executions" / EXECUTION
        self.snapshot = self.root / "pipeline/files"
        self.worker_text = "// TEST inert recorded worker bytes; never executed\n"
        self._pipeline()
        self._opening()
        prepared = prepare_source_color_jobs(self.inputs, self.declarations, self.context)
        self.jobs, self.sections = [], []
        for index, value in enumerate(prepared):
            self._job(index, value.record())
        self._stage()
        self.read_context = ColdSourceColorObservationContext(self.inputs, self.references, 1300.0, self.guard)

    def write(self, path: Path, value: object) -> dict:
        """Create a new exact TEST file, retaining its path on a closed mutation allowlist."""
        if not path.is_relative_to(self.root):
            raise RuntimeError("TEST publication escaped fixture root")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        raw = value if type(value) is bytes else (json.dumps(value, sort_keys=True, allow_nan=False) + "\n").encode()
        with path.open("xb") as stream:
            stream.write(raw)
        path.chmod(0o600)
        self.allowed.add(path)
        return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "sizeBytes": len(raw)}

    def _pipeline(self) -> None:
        """Fake pinned inventory is inside TEST root, never today's code/tool closure."""
        self.inventory = []
        approval = {"schemaVersion": 1, "imageId": "sha256:" + "3" * 64,
                    "probedClosure": {"sha256": {"/usr/bin/ffprobe": "6" * 64}}}
        for name in sorted({*STAGED_ROOTS, "scripts/producer/guided_opening_media.py"}):
            value = approval if name == APPROVAL else (self.worker_text if name == WORKER else "TEST inert code\n").encode()
            ref = self.write(self.snapshot / name, value)
            self.inventory.append({"path": ref["path"], "sha256": ref["sha256"]})
        self.worker_ref = next(row for row in self.inventory if row["path"] == str(self.snapshot / WORKER))
        self.approval_ref = {**next(row for row in self.inventory if row["path"] == str(self.snapshot / APPROVAL)),
                             "sizeBytes": (self.snapshot / APPROVAL).stat().st_size}
        rows = [{"path": str(Path(row["path"]).relative_to(self.snapshot)), "hash": row["sha256"]} for row in self.inventory]
        self.lock = {"schemaVersion": 1, "state": "pinned", "runId": "TEST", "files": rows, "digest": digest(rows)}
        lock_ref = self.write(self.snapshot.parent / "pipeline-lock.json", self.lock)
        self.pipeline = {"snapshotRoot": str(self.snapshot), "lockPath": lock_ref["path"],
                         "lockSha256": lock_ref["sha256"], "digest": self.lock["digest"]}
        self.executed = {"schemaVersion": 1, "kind": "guided-opening-executed-pipeline", "pipelineDigest": self.lock["digest"],
            "lockSha256": lock_ref["sha256"], "pinnedFileCount": len(rows),
            "executionClosure": [{"path": row["path"], "sha256": row["hash"]} for row in rows],
            "tools": {key: {"path": str(self.root / f"TEST-tools/{key}"), "sha256": "2" * 64} for key in ("python", "ffmpeg", "ffprobe")}}
        self.runtime = {"dockerPath": str(self.root / "TEST-tools/docker"), "dockerSha256": "2" * 64,
            "dockerSocketPath": str(self.root / "TEST-tools/docker.sock"), "dockerSocketDevice": "1", "dockerSocketInode": "2",
            "imageId": approval["imageId"], "userId": "501:20", "imageApprovalPath": self.approval_ref["path"],
            "imageApprovalSha256": self.approval_ref["sha256"], "runtimeRepoRoot": str(self.snapshot)}

    def _opening(self) -> None:
        """Full fourteen-slot data and original claim shape; admission provenance remains TEST."""
        refs = {name: {"path": str(self.producer / f"TEST-{name}.json"), "sha256": "5" * 64} for name in DOCUMENTS}
        refs["manifest"] = {"path": str(self.producer / "asset_manifest.json"), "sha256": self.context.parents.expected["manifestSha256"]}
        documents = {name: {"TEST": "not document approval"} for name in DOCUMENTS}
        documents.update(self.inputs.documents)
        documents["authority"] = {"runId": "TEST", "clockHash": "a" * 64, "generationStartedAt": "2026-09-08T00:00:00.000Z"}
        value = {"schemaVersion": 1, "kind": "guided-opening-media-input", "executionId": EXECUTION,
            "profile": "unity-source-float-own-screen-v1", "documents": refs, "pipeline": self.pipeline}
        value["executionInputHash"] = digest(value)
        input_ref = self.write(self.execution / "media-input/input.json", value)
        self.inputs = OpeningInputs(Path(input_ref["path"]), input_ref["sha256"], value, documents, self.inputs.verified_media)
        self.claim = {"schemaVersion": 1, "kind": "guided-opening-execution-claim",
            "scope": "private-opening-owned-execution-not-approval", "requestId": REQUEST, "executionId": EXECUTION,
            "beforeJournalHash": "1" * 64, "inputPath": input_ref["path"], "inputSha256": input_ref["sha256"],
            "executionInputHash": value["executionInputHash"], "outputRoot": str(self.execution / "media-output"),
            "clockHash": "a" * 64, "generationStartedAt": "2026-09-08T00:00:00.000Z", "budgetAdmissionHash": "b" * 64,
            "selectedGraphicOrders": [], "runtime": self.runtime}
        claim_ref = self.write(self.execution / "execution-claim.json", self.claim)
        self.opening = {"claimPath": claim_ref["path"], "claimSha256": claim_ref["sha256"], **{key: self.claim[key] for key in
            ("inputPath", "inputSha256", "executionId", "executionInputHash", "clockHash", "generationStartedAt",
             "budgetAdmissionHash", "beforeJournalHash")}}

    def _job(self, index: int, prepared: dict) -> None:
        """Publish an original immutable TEST job and its complete synthetic raw record chain."""
        source_id, job_id = prepared["sourceId"], JOBS[index]
        job = planned_job(str(self.producer), source_id, job_id)
        directory = Path(job["directory"])
        job["implementation"] = self.write(directory / "implementation.json", {"files": self.inventory})
        value = {"schemaVersion": 1, "policy": V1.project_policy, "jobId": job_id, "producerDir": str(self.producer),
            "sourceId": source_id, "declaration": prepared["declaration"], "expected": self.context.parents.expected,
            "ownerPid": 1234, "implementationSha256": job["implementation"]["sha256"]}
        job["input"] = self.write(directory / "input.json", value)
        claim = {"schemaVersion": 1, "kind": "owned-grade-launch-claim", "scope": "preclaimed-source-observation-not-recovery-or-approval",
            "jobId": job_id, "inputPath": job["inputPath"], "inputSha256": job["input"]["sha256"], "executionDir": job["executionDir"],
            "sourcePath": prepared["sourcePath"], "sourceSha256": prepared["binding"]["sourceSha256"],
            "frameCount": prepared["binding"]["frameCount"], "profile": None, "containerName": job["containerName"],
            "openingClaimPath": self.opening["claimPath"], "openingClaimSha256": self.opening["claimSha256"], "runtime": self.runtime}
        job["launchClaim"] = self.write(directory / "launch-claim.json", claim)
        source = next(row for row in self.rows if row["id"] == source_id)
        parents = {"binding": prepared["binding"], "declaration": prepared["declaration"], "sourcePath": prepared["sourcePath"],
            "sourceManifestRow": source, "sourceSetAdmission": self.manifest["sourceSetAdmission"], "expectedParents": self.context.parents.expected,
            "projectHistory": {"projectSha256": self.context.parents.expected["projectSha256"], "history": self.project["history"]},
            "clockCaveat": "Ingest declaredFrames/exact manifest frameRate are candidates until full original EOF/metadata/cadence replay matches."}
        artifacts = {key: job[key] for key in ("input", "implementation", "launchClaim")}
        artifacts["parents"] = self.write(directory / "parents.json", parents)
        raw = raw_records(self, prepared, directory)
        artifacts.update(probe=raw[0], frames=raw[1])
        artifacts["execution"] = self.write(directory / "execution/execution.json", execution_record(self, job, claim, raw))
        row = {"sourceId": source_id, "jobId": job_id, "selection": self.declarations[source_id],
            "source": {"path": source["path"], "sha256": source["sourceSha256"], "sizeBytes": source["sourceSizeBytes"]},
            "binding": prepared["binding"], "artifacts": artifacts, "records": raw[3], "bt709Identity": raw[4],
            "timing": {"sourceId": source_id, "startedMs": index * 10, "elapsedMs": 10, "status": "complete", "cleanupVerified": True}}
        artifacts["observation"] = self.write(directory / "observation.json", observation_record(self, row))
        self.jobs.append(job)
        self.sections.append(row)

    def _stage(self) -> None:
        """Archive literal reservation bytes; deliberately never create active.json."""
        source_color = {"schemaVersion": 1, "declarations": self.declarations}
        plans = [{key: value for key, value in row.items() if key not in ("input", "implementation", "launchClaim")} for row in self.jobs]
        reservation = {"schemaVersion": 2, "kind": "guided-source-color-reservation",
            "scope": "reserved-grade-container-names-not-process-settlement-or-cleanup", "producerDir": str(self.producer),
            "opening": self.opening, "sourceColorHash": digest(source_color), "sidecarPath": str(self.execution / "source-color/input.json"),
            "ownerPid": 1234, "runtime": self.runtime, "jobs": plans}
        archive = self.write(self.execution / "cleanup-attempts" / JOBS[0] / "reservation.json", reservation)
        active = {**archive, "path": str(self.root / "workspace/.sniper-color-resource/active.json")}
        self.staged = {"schemaVersion": 1, "kind": "guided-source-color-input", "scope": "private-source-observation-not-transform-or-approval",
            "opening": self.opening, "producerDir": str(self.producer), "sourceColor": source_color,
            "expected": self.context.parents.expected, "reservation": active, "jobs": self.jobs,
            "executable": False, "gradeApplicable": False, "deliveryApproved": False}
        sidecar = self.write(Path(reservation["sidecarPath"]), self.staged)
        self.references = {"sidecar": sidecar, "reservation": active, "archive": archive, "producerDir": str(self.producer),
            "openingClaim": self.claim, "implementation": {"pipelineLock": self.lock, "executedPipeline": self.executed, "imageApproval": self.approval_ref}}
        self.section = {"schemaVersion": 1, "kind": "guided-opening-source-color-observation-section",
            "scope": "actual-live-observations-not-base-consumption-or-media-approval", "processInput": {"schemaVersion": 1,
            "kind": "guided-opening-source-color-process-input", "scope": "explicit-staged-input-not-observation-cleanup-or-approval",
            "input": sidecar, "reservation": active, "sourceColorHash": digest(source_color)}, "opening": self.opening,
            "parents": self.context.parents.expected, "sources": self.sections, "elapsedMs": 20,
            "gamutMeasured": False, "gradeApplied": False, "basePictureObserved": False, "openingApproved": False, "deliveryApproved": False}

    def replace(self, path: Path, raw: bytes | None = None) -> dict:
        """Fault only original allowlisted canonical single-link TEST files, never dependencies."""
        if path not in self.allowed or not path.is_relative_to(self.root) or path.resolve(strict=True) != path:
            raise RuntimeError("fault target is not an exact TEST-owned file")
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
            raise RuntimeError("fault target is not a TEST-owned regular single-link file")
        payload = path.read_bytes() if raw is None else raw
        path.write_bytes(payload)
        return {"path": str(path), "sha256": hashlib.sha256(payload).hexdigest(), "sizeBytes": len(payload)}

    def change_record(self, role: str, update: object, index: int = 0) -> None:
        """Rebind one supplied TEST artifact to exercise semantic, not just raw-hash rejection."""
        row = self.sections[index]
        path = Path(row["artifacts"][role]["path"])
        value = json.loads(path.read_bytes())
        update(value)
        if "artifactHash" in value:
            value["artifactHash"] = digest({key: item for key, item in value.items() if key != "artifactHash"})
        row["artifacts"][role] = self.replace(path, (json.dumps(value, sort_keys=True) + "\n").encode())
        if role in ("execution", "parents", "frames"):
            report = observation_record(self, row)
            target = Path(row["artifacts"]["observation"]["path"])
            row["artifacts"]["observation"] = self.replace(target, (json.dumps(report, sort_keys=True) + "\n").encode())

    def read(self) -> dict:
        """Call the actual cold reader with original TEST raw refs and captured sources."""
        return read_source_color_observations(self.section, self.read_context)
