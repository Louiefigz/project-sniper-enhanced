"""Actual opening adapter on inert owned files, never production intake/admission.

The existing admission runner/runtime socket-type/native grade/read-observation
leaves are TEST stubs. Readers, same-hash capture, job preflight, project result
publication and typed completion are real. There is no daemon, lease or decoder.
"""
from __future__ import annotations

import json
import os
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from _grade_project_owned_fixture import OwnedGradeFixture
from _source_color_batch_fixture import SourceColorBatchFixture
from _source_color_staging_fixture import planned_job, staging_fixture
from color import grade_project as project
from color import grade_project_authority as authority
from color.grade_observation_read import BoundGradeObservation
from cut_preview_io import digest, file_hash, write_new
from guided_opening_claim import HeldOpeningClaim
from guided_opening_execution import OpeningExecutionClock
from guided_opening_inputs import DOCUMENTS
from guided_source_color_opening import (
    SourceColorOpeningAuthority, SourceColorOpeningContext, observe_opening_source_colors,
)
from headless.grade_observation_phase import OwnedGradePhase


class SourceColorOpeningFixture(SourceColorBatchFixture):
    """Two sources and exact original opening/staging/job lineage in one TEST root."""

    def __init__(self, pins: list[dict]) -> None:
        """Prepare metadata only; defer actual adapter preflight until its invocation."""
        super().__init__(pins)
        self.calls, self.returned_by_source = [], {}
        self.value, self.execution, self.returned = None, None, None
        self.work_seconds = 1.0
        self._staging()
        self.clock = OpeningExecutionClock(self.context.deadline)
        self.opening = HeldOpeningClaim(self.opening_claim, file_hash(self.opening_claim), self.opening_value)
        self.authority = SourceColorOpeningAuthority(self.producer, self.resource, self.guard)
        self.opening_context = SourceColorOpeningContext(self.inputs, self.opening, self.clock, self.authority)
        self.stack.enter_context(patch.object(authority, "execution_media_authority_entries", return_value=self.entries))
        self.worker = self.stack.enter_context(patch.object(project, "run_owned_isolated_grade", side_effect=self.native_stub))
        self.stack.enter_context(patch.object(project, "read_observation", side_effect=self.read_stub))

    def _opening(self) -> Path:
        """Publish exact path lineage while labelling placeholder14-document evidence."""
        request, execution = str(uuid4()), str(uuid4())
        directory = self.producer / "guided-v2-operations" / request / "executions" / execution
        inputs_dir = directory / "media-input"
        inputs_dir.mkdir(parents=True, mode=0o700)
        refs = dict(self.inputs.value["documents"])
        for name in sorted(DOCUMENTS - set(refs)):
            path = inputs_dir / f"TEST-{name}.json"
            write_new(path, {"TEST": name, "admissionVerified": False})
            refs[name] = {"path": str(path), "sha256": file_hash(path)}
        value = {"schemaVersion": 1, "kind": "guided-opening-media-input", "executionId": execution,
                 "profile": "unity-source-float-own-screen-v1", "documents": refs,
                 "pipeline": {"snapshotRoot": str(self.snapshot), "lockPath": str(self.root / "TEST-lock.json"),
                              "lockSha256": "e" * 64, "digest": "f" * 64}}
        value["executionInputHash"] = digest(value)
        path = inputs_dir / "input.json"
        write_new(path, value)
        documents = deepcopy(self.inputs.documents)
        documents.update(authority={"clockHash": "c" * 64, "generationStartedAt": "2026-09-08T00:00:00.000Z",
                                    "review": {"endFrameExclusive": 24}}, frameBindings={"graphics": []})
        self.inputs = replace(self.inputs, path=path, sha256=file_hash(path), value=value, documents=documents)
        self.opening_value = {"schemaVersion": 1, "kind": "guided-opening-execution-claim",
            "scope": "private-opening-owned-execution-not-approval", "requestId": request, "executionId": execution,
            "beforeJournalHash": "b" * 64, "inputPath": str(path), "inputSha256": self.inputs.sha256,
            "executionInputHash": value["executionInputHash"], "outputRoot": str(directory / "media-output"),
            "clockHash": "c" * 64, "generationStartedAt": "2026-09-08T00:00:00.000Z", "budgetAdmissionHash": "d" * 64,
            "selectedGraphicOrders": [], "runtime": self.runtime_controls}
        claim = directory / "execution-claim.json"
        write_new(claim, self.opening_value)
        return claim

    @staticmethod
    def _reference(path: Path) -> dict:
        """Reference actual TEST metadata raw bytes, not a semantic object digest."""
        return {"path": str(path), "sha256": file_hash(path), "sizeBytes": path.stat().st_size}

    def _staging(self) -> None:
        """Write a complete raw-bound reservation and sidecar, but no resource lease."""
        sidecar, reservation = staging_fixture()
        opening = {"claimPath": str(self.opening_claim), "claimSha256": file_hash(self.opening_claim),
                   **{key: self.opening_value[key] for key in ("inputPath", "inputSha256", "executionId", "executionInputHash",
                       "clockHash", "generationStartedAt", "budgetAdmissionHash", "beforeJournalHash")}}
        plans = [planned_job(str(self.producer), row.source_id, self.input_values[row.source_id]["jobId"]) for row in self.refs]
        jobs = [{**row, **{key: self._reference(Path(row[field])) for key, field in
                          (("input", "inputPath"), ("implementation", "implementationPath"), ("launchClaim", "launchClaimPath"))}}
                for row in plans]
        source_color = {"schemaVersion": 1, "declarations": deepcopy(self.declarations)}
        self.sidecar_path = self.opening_claim.parent / "source-color/input.json"
        self.resource = self.root / ".sniper-color-resource"
        self.reservation_path = self.resource / "active.json"
        reservation.update(producerDir=str(self.producer), opening=deepcopy(opening), sourceColorHash=digest(source_color),
                           sidecarPath=str(self.sidecar_path), ownerPid=os.getppid(), runtime=self.runtime_controls, jobs=plans)
        self.resource.mkdir(mode=0o700)
        write_new(self.reservation_path, reservation)
        sidecar.update(producerDir=str(self.producer), opening=opening, sourceColor=source_color,
                       expected=deepcopy(self.context.parents.expected), reservation=self._reference(self.reservation_path), jobs=jobs)
        self.sidecar_path.parent.mkdir(mode=0o700)
        write_new(self.sidecar_path, sidecar)
        self.sidecar, self.reservation = sidecar, reservation
        self.allowed_faults.update((self.reservation_path, self.sidecar_path))
        self.reference = (self.sidecar_path, file_hash(self.sidecar_path))

    def native_stub(self, source: str, request: dict, directory: Path, phase: OwnedGradePhase) -> dict:
        """Exercise actual dispatch/launch guard but substitute the native work only."""
        phase.check()
        phase.owner.guard()
        source_id = next(row["id"] for row in self.rows if row["path"] == source)
        self.value = self.input_values[source_id]
        if directory != self.input_paths[source_id].parent / "execution":
            raise AssertionError("TEST native dispatch changed its exact execution directory")
        self.calls.append((source, request, directory, phase))
        self.now += self.work_seconds
        return OwnedGradeFixture.run_stub(self, source, request, directory, phase.deadline)

    def read_stub(self, directory: Path, parents: tuple[dict, dict], execution: dict) -> BoundGradeObservation:
        """Use actual typed synthetic-frame validation, not decoded-source evidence."""
        result = OwnedGradeFixture.read_stub(self, directory, parents, execution)
        self.returned_by_source[parents[0]["sourceId"]] = result
        return result

    def execute(self) -> object:
        """Run the real adapter without public intake, renderer, daemon or approval."""
        return observe_opening_source_colors(self.reference, self.opening_context)

    def republish_sidecar(self) -> None:
        """Refresh explicitly owned TEST sidecar only before an independent call."""
        self.change(self.sidecar_path, self.sidecar)
        self.reference = (self.sidecar_path, file_hash(self.sidecar_path))

    def retired_reservation(self) -> None:
        """Simulate released claim metadata; not an actual lease or cleanup operation."""
        self.change(self.reservation_path, json.dumps({"TEST": "retired reservation"}).encode())
