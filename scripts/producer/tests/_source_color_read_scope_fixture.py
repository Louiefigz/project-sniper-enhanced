"""Isolated outer-read metadata fixture; no native/source-color approval is real.

Original source captures and all file identities/raw references are actual.
Only pipeline discovery and optional downstream media proof leaves are TEST
stubs. Every mutable file is below the inherited exact canonical allowlist;
no current interpreter, repository source, Docker socket or daemon is opened.
"""
from __future__ import annotations

import json
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from _source_color_observation_read_fixture import ColdObservationFixture
from cut_preview_io import digest
from guided_opening_claim import HeldOpeningClaim
from guided_opening_execution import OpeningExecutionClock
from guided_opening_inputs import OpeningInputs
from guided_opening_read import ReadAuthority
from guided_source_color_media_evidence import EVIDENCE_SCOPE
from guided_source_color_read_entry import capture_source_color_read_entry
from guided_source_color_read_scope import SourceColorReadScope
from guided_source_color_read_transport import SourceColorReadTransport


class ColdReadScopeFixture(ColdObservationFixture):
    """Complete inert outer controls plus the actual two-source raw metadata chain."""

    def __init__(self) -> None:
        """Publish each synthetic control before constructing any actual read scope."""
        super().__init__()
        self.output = self.execution / "media-output"
        evidence = {"schemaVersion": 1, "kind": "guided-opening-source-color-media-evidence",
            "scope": EVIDENCE_SCOPE, "observations": self.section,
            "pictureConsumption": {"TEST": "not a consumption proof"}, "fullProgram": {},
            "gamutMeasured": False, "gradeApplied": False, "colorQualified": False,
            "openingApproved": False, "deliveryApproved": False}
        evidence["receiptHash"] = digest(evidence)
        reference = self.write(self.output / "source-color-evidence.json", evidence)
        reference["receiptHash"] = evidence["receiptHash"]
        self.record = {"schemaVersion": 2, "pipeline": self.executed,
                       "sourceColorEvidence": reference, "fullProgram": {}}
        self.record["receiptHash"] = digest(self.record)
        receipt = self.write(self.output / "media-result.json", self.record)
        self.held_claim = HeldOpeningClaim(Path(self.opening["claimPath"]), self.opening["claimSha256"], self.claim)
        self.authority = ReadAuthority(self.inputs.sha256, self.held_claim.path, self.held_claim.sha256,
                                       receipt["sha256"], self.record["receiptHash"])
        self.clock = OpeningExecutionClock(1300.0)
        self.transport = SourceColorReadTransport(Path(self.references["sidecar"]["path"]),
            self.references["sidecar"]["sha256"], Path(self.references["archive"]["path"]), self.references["archive"]["sha256"])
        self.entry = capture_source_color_read_entry((self.inputs.path, self.output), self.authority,
                                                    self.transport, self.clock)

    def _pipeline(self) -> None:
        """The executed tool files are inert TEST bytes, never the installed binaries."""
        super()._pipeline()
        for role, row in self.executed["tools"].items():
            reference = self.write(Path(row["path"]), f"TEST inert {role}\n".encode())
            row["sha256"] = reference["sha256"]

    def _opening(self) -> None:
        """Complete all original document files before the staged/job chain is authored."""
        super()._opening()
        self.inputs.documents["authority"]["review"] = {"endFrameExclusive": 2}
        self.inputs.documents["frameBindings"] = {"graphics": []}
        for name, old in self.inputs.value["documents"].items():
            if name == "manifest":
                continue
            reference = self.write(Path(old["path"]), self.inputs.documents[name])
            old.update({key: reference[key] for key in ("path", "sha256")})
        value = self.inputs.value
        value["executionInputHash"] = digest({key: row for key, row in value.items() if key != "executionInputHash"})
        input_ref = self.replace(self.inputs.path, self.bytes(value))
        self.inputs = OpeningInputs(self.inputs.path, input_ref["sha256"], value,
                                    self.inputs.documents, self.inputs.verified_media)
        self.claim.update(inputSha256=self.inputs.sha256, executionInputHash=value["executionInputHash"])
        claim_ref = self.replace(Path(self.opening["claimPath"]), self.bytes(self.claim))
        self.opening.update(claimSha256=claim_ref["sha256"], inputSha256=self.inputs.sha256,
                            executionInputHash=value["executionInputHash"])

    @staticmethod
    def bytes(value: dict) -> bytes:
        """Encode only synthetic fixture metadata using the inherited raw JSON spelling."""
        return (json.dumps(value, sort_keys=True, allow_nan=False) + "\n").encode()

    def leaves(self) -> ExitStack:
        """Limit actual code pins to inert TEMP files and stub current pipeline discovery."""
        stack = ExitStack()
        stack.enter_context(patch("guided_opening_lifetime.REPOSITORY_ROOT", self.snapshot))
        stack.enter_context(patch("guided_source_color_read_scope.read_closure_refs", return_value=()))
        stack.enter_context(patch("guided_source_color_read_scope.observe_pipeline", return_value=deepcopy(self.executed)))
        return stack

    def scope(self) -> SourceColorReadScope:
        """Construct the actual outer scope; the caller owns explicit TEST leaf patches."""
        return SourceColorReadScope(self.inputs, self.record,
                                    (self.output, self.held_claim, self.clock, self.authority, self.entry), self.transport)
