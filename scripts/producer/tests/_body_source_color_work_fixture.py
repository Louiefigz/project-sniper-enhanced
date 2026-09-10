"""Actual raw source/consumption replay over inert TEST files, never body qualification.

The initial source capture is the actual inherited hash-pass result. Current
input admission and current body/pipeline discovery are explicit TEST leaves;
only ffprobe's subprocess leaf is fabricated for the real packet/copy reader.
No live opening owner, old socket, renderer or actual human approval is used.
"""
from __future__ import annotations

from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from unittest.mock import patch

from _body_source_color_control_fixture import _controls, _publish
from _source_color_consumption_read_fixture import ConsumptionReadFixture
from _source_color_observation_read_fixture import ColdObservationFixture
from _source_color_read_scope_fixture import ColdReadScopeFixture
from compile_timeline import compile_plan
from cut_preview_io import digest, file_hash
from guided_body_budget import bind_body_budget
from guided_body_execution import body_clock
from guided_body_inputs import read_body_control
from guided_body_source_color_replay import SCOPE
from guided_opening_inputs import OpeningInputs
from guided_opening_read import SCOPE as OPENING_SCOPE
import guided_body_work as work


class BodyConsumptionFiles(ConsumptionReadFixture):
    """Use the existing real consumption builders with the original raw observation chain."""

    def __init__(self, original: BodySourceColorWorkFixture) -> None:
        """Publish generated TEST artifacts before any body entry or scope is captured."""
        self.directory, self.root = original.root, original.execution / "media-output"
        self.base, self.tools = self.root / "full-program-base", original.root / "TEST-tools"
        self.bus = self.base / ".source-float-v2-TEST"
        self.bus.mkdir(parents=True, mode=0o700)
        self.paths = {"evidence": self.root / "source-color-evidence.json", "base": self.base / "final.mp4",
            "timelineMap": self.base / "timeline_map.json", "cutManifestation": self.base / "cut_manifestation.json",
            "sourceBus": self.bus / "bus-receipt.json", "sourceFloatMaster": self.bus / "master-receipt.json",
            "pictureMaster": self.bus / "picture-master.mp4", "ffprobe": self.tools / "ffprobe"}
        from cut_manifestation_authority import MANIFESTATION_NAME
        self.paths["cutManifestation"] = self.base / MANIFESTATION_NAME
        self.allowed = frozenset(self.paths.values())
        self._new(self.paths["base"], b"TEST final inert video")
        self._new(self.paths["pictureMaster"], b"TEST original inert picture")
        self.inputs, self.observations = original.inputs, original.section
        self.plan = self.inputs.documents["candidatePlan"]
        self.timeline = compile_plan(self.plan).to_dict()
        self._new(self.paths["timelineMap"], json.dumps(self.timeline, indent=2).encode())
        self.manifestation, self.cuts = self._cuts()
        self.consumed = self._consumption()
        self._records()
        self.native_calls = []


class BodySourceColorWorkFixture(ColdReadScopeFixture):
    """Prepare original metadata before the FIRST body seed; never repair a sealed entry."""

    def __init__(self) -> None:
        """Do not construct the inherited outer entry/result with placeholder consumption."""
        ColdObservationFixture.__init__(self)
        self.picture = BodyConsumptionFiles(self)
        self.output = self.picture.root
        self.record = self._result()
        self.result_ref = self.write(self.output / "media-result.json", self.record)
        self.control = self._control()
        self.clock = body_clock(300)
        bind_body_budget(self.control, self.clock)
        self.original_inputs = self.inputs

    def refresh(self) -> None:
        """Choose the fixture plan BEFORE original parent/input/staging publication."""
        self.plan["target"] = {"mode": "longform", "fps": 24, "width": 1920, "height": 1080}
        for row in self.plan["cutTrack"]:
            row["speed"] = 1
        super().refresh()

    def _pipeline(self) -> None:
        """Only inert TEST tool files exist; make the recorded ffprobe role executable-shaped."""
        super()._pipeline()
        Path(self.executed["tools"]["ffprobe"]["path"]).chmod(0o500)

    def _opening(self) -> None:
        """Finish ordinary plan/clock metadata BEFORE staging and raw worker history."""
        ColdObservationFixture._opening(self)
        self.inputs.documents["authority"].update(frameRate="24", totalFrames=18,
            target={"width": 1920, "height": 1080}, review={"endFrameExclusive": 18})
        self.inputs.documents["frameBindings"] = {"graphics": []}
        for name, old in self.inputs.value["documents"].items():
            if name != "manifest":
                old.update({key: value for key, value in self.write(Path(old["path"]), self.inputs.documents[name]).items() if key != "sizeBytes"})
        value = self.inputs.value
        value["executionInputHash"] = digest({key: row for key, row in value.items() if key != "executionInputHash"})
        ref = self.replace(self.inputs.path, self.bytes(value))
        self.inputs = OpeningInputs(self.inputs.path, ref["sha256"], value, self.inputs.documents, self.inputs.verified_media)
        self.claim.update(inputSha256=ref["sha256"], executionInputHash=value["executionInputHash"])
        claim_ref = self.replace(Path(self.opening["claimPath"]), self.bytes(self.claim))
        self.opening.update(claimSha256=claim_ref["sha256"], inputSha256=ref["sha256"], executionInputHash=value["executionInputHash"])

    def _result(self) -> dict:
        """Complete source2 identity with generated TEST base refs, not a whole audio proof."""
        record = {"schemaVersion": 2, "kind": "guided-opening-media-result", "scope": OPENING_SCOPE,
            "status": "complete", "profile": self.inputs.value["profile"],
            **{key: self.claim[key] for key in ("inputPath", "inputSha256", "executionId", "executionInputHash")},
            "executionClaim": {"path": self.opening["claimPath"], "sha256": self.opening["claimSha256"]},
            "authority": self.inputs.documents["authority"], "documents": self.inputs.value["documents"],
            "openingApproved": False, "deliveryApproved": False, "bodyGraphicsPrepared": False,
            "creativeVisualReview": "not-run", "subjectiveListening": "not-run",
            "qualificationScope": "private-mechanical-frame-audio-and-runtime-evidence-only",
            "processGroupCleanup": "requires-owned-server-observation", "pipeline": self.executed,
            "fullProgram": deepcopy(self.picture.bindings["fullProgram"]), "sourceColorEvidence": self.picture.bindings["evidenceRef"],
            "audio": {}, "graphics": {}, "pictures": {}, "media": {}, "stages": []}
        record["fullProgram"].update(fullMasterSelectionEventPath=str(self.picture.bus / "TEST-selection-event.json"),
                                    fullMasterSelectionEventSha256="d" * 64)
        record["receiptHash"] = digest(record)
        return record

    def _control(self) -> object:
        """Use the actual body control reader; only current runtime admission is TEST-stubbed."""
        old = {key: self.opening[key] for key in ("claimPath", "claimSha256", "inputPath", "inputSha256", "executionInputHash")}
        old.update(outputRoot=str(self.output), resultPath=self.result_ref["path"], resultSha256=self.result_ref["sha256"])
        replay = {"schemaVersion": 2, "kind": "guided-body-source-color-replay-references", "scope": SCOPE,
            "opening": {"selectionHash": "2" * 64, "cleanupHash": "6" * 64, "claimHash": digest(self.claim),
                "executionId": self.claim["executionId"], "inputSha256": self.inputs.sha256,
                "executionInputHash": self.inputs.value["executionInputHash"], "mediaResultSha256": self.result_ref["sha256"],
                "receiptHash": self.record["receiptHash"]}, "sourceColorHash": self.section["processInput"]["sourceColorHash"],
            "input": self.references["sidecar"], "reservationArchive": self.references["archive"],
            "executable": False, "bodyApproved": False, "deliveryApproved": False}
        held = self._held(replay)
        snapshot = {"ctx": {"dir": str(self.producer)}, "status": "treatment_admitted", "guidedHandoffV2": {
            "openingCleanupHash": "6" * 64, "openingApprovalHash": "1" * 64, "openingMediaSelectionHash": "2" * 64,
            "proposalReadinessHash": "3" * 64, "treatmentDraftRevisionHash": "4" * 64}}
        temporary = self.producer / "human-cut-job-snapshots/TEST-snapshot.json"
        ref = _publish(temporary, snapshot)
        target = temporary.with_name(ref["sha256"] + ".json")
        temporary.rename(target)
        ref["path"], held["journalHash"] = str(target), ref["sha256"]
        origin = int(datetime(2026, 9, 8, tzinfo=timezone.utc).timestamp() * 1000)
        invocation, output = _controls(self.producer, (held, old), ref, origin)
        with patch("guided_body_inputs.verify_runtime_controls"):
            return read_body_control(invocation, output)

    def _held(self, replay: dict) -> dict:
        """Data-only body admission mirrors exact original base and master references."""
        full = self.record["fullProgram"]
        return {"schemaVersion": 2, "scope": "held-body-input-not-launch-body-readiness-or-delivery-approval",
            "submission": {}, "bindings": {}, "verification": {}, "sourceColorReplay": replay,
            "authority": self.inputs.documents["authority"], "approvalHash": "1" * 64, "selectionHash": "2" * 64,
            "readinessHash": "3" * 64, "draftRevisionHash": "4" * 64,
            "origin": {"clockHash": self.claim["clockHash"], "startedAt": self.claim["generationStartedAt"]},
            "references": {"base": {key: full["base"][key] for key in ("path", "sha256")},
                "masterSelection": {"path": full["fullMasterSelectionEventPath"], "sha256": full["fullMasterSelectionEventSha256"]},
                **{key: self.inputs.value["documents"][key] for key in ("candidatePlan", "manifest")}},
            "executable": False, "bodyReadiness": "not-qualified", "bodyGenerated": False, "deliveryApproved": False}

    def leaves(self) -> ExitStack:
        """Keep actual replay/file holders; initial admission/pipeline and native leaves are TEST."""
        stack = super().leaves()
        stack.enter_context(patch.dict(os.environ, {"PATH": str(self.picture.tools)}))
        stack.enter_context(patch("guided_body_work.read_current_inputs", side_effect=lambda *_args: self.original_inputs))
        pipeline = {"schemaVersion": 1, "kind": "guided-body-executed-pipeline", "opening": self.executed, "bodyExecutionClosure": []}
        stack.enter_context(patch("guided_body_work.observe_body_pipeline", side_effect=lambda *_args: deepcopy(pipeline)))
        stack.enter_context(patch("guided_body_pipeline.__file__", str(self.snapshot / "scripts/producer/guided_body_pipeline.py")))
        stack.enter_context(patch("audio.audio_mix_picture._run", side_effect=self.picture.native))
        return stack

    def work(self) -> object:
        """Run actual entry/read handoff and actual scope construction with declared TEST leaves."""
        read = work.read_body_inputs(self.control, self.clock)
        return work.prepare_body_work(self.control, read.inputs, self.clock, read.source_color_entry)
