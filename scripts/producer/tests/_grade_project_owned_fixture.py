"""Real tiny metadata files with STUBBED admission/decoder, never media authority.

The SourceFrameValidator consumes synthetic supplied records. Only the Python
handoff and publication paths are real; no Docker, ffprobe or source grade runs.
"""
from __future__ import annotations

import time
import json
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

from _grade_contract_fixture import frame, stream, terminal
from _grade_observation_v2_fixture import v2_project
from _grade_project_fixture import GradeProjectFixture
from color import grade_project as project
from color import grade_project_authority as authority
from color.grade_observation_read import BoundGradeObservation
from color.grade_observation_geometry import SourceObservationMetadata
from color.grade_observation_profile import V2, project_profile
from color.grade_project_owned import GradeProjectOwnedContext, OwnedProjectObservation
from color.grade_source_class import SourceFrameValidator
from cut_preview_io import file_hash, write_new
from headless.external_media_verification import VerifiedSnapshotIdentity, snapshot_stat_identity


class OwnedGradeFixture(GradeProjectFixture):
    """Supply actual typed reader objects through a clearly stubbed worker seam."""

    def __init__(self) -> None:
        """Capture the tiny initial source identity before starting the adapter."""
        super().__init__()
        source = Path(self.entry["snapshotPath"])
        before = source.stat()
        self.identity = VerifiedSnapshotIdentity(str(source), file_hash(source), before.st_size,
                                                 snapshot_stat_identity(before))
        self.guard = Mock()
        self.context = GradeProjectOwnedContext(time.monotonic() + 120, self.guard, self.identity)
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(authority, "execution_media_authority_entries", return_value=[self.entry]))
        self.code = self.stack.enter_context(patch.object(project, "implementation", return_value=[]))
        self.worker = self.stack.enter_context(patch.object(project, "run_isolated_grade", side_effect=self.run_stub))
        self.reader = self.stack.enter_context(patch.object(project, "read_observation", side_effect=self.read_stub))
        self.returned: BoundGradeObservation | None = None
        self.execution: dict | None = None

    def run_stub(self, source: str, request: dict, directory: Path, deadline: float) -> dict:
        """Write fake worker records solely to exercise exact byte holding."""
        result = directory / "result"
        result.mkdir(mode=0o700)
        write_new(result / "probe.json", {"syntheticTestOnly": True})
        (result / "frames.ffprobe").write_bytes(b"SYNTHETIC UNIT RECORDS; NO DECODER\n")
        self.execution = {"status": "complete", "cleanupVerified": True, "cleanupMs": 7,
            "sourceBeforeSha256": file_hash(Path(source)), "sourceAfterSha256": file_hash(Path(source)),
            "syntheticTestOnly": True, "request": request, "deadline": deadline}
        write_new(directory / "execution.json", self.execution)
        return self.execution

    def read_stub(self, directory: Path, parents: tuple[dict, dict], execution: dict) -> BoundGradeObservation:
        """Use the real record validator, but do not claim actual decoder provenance."""
        binding, declaration = parents
        observed = stream(binding, origin=0)
        observed.update(width=160, height=90)
        profile = project_profile(self.value)
        if profile is V2:
            observed.update(transfer=profile.transfer,
                sourceMetadata=SourceObservationMetadata("h264", "left", "left", "1:1", "1:1").record())
        validator = SourceFrameValidator(binding, declaration, observed, profile.token)
        for index in range(binding["frameCount"]):
            row = frame(index, observed)
            if profile is V2:
                row.update(transfer=profile.transfer, chromaLocation="left", sampleAspectRatio="1:1")
            validator.add_frame(row)
        self.returned = BoundGradeObservation(validator.finish(terminal(binding)),
            file_hash(directory / "execution.json"), file_hash(directory / "result/frames.ffprobe"),
            file_hash(directory / "result/probe.json"))
        return self.returned

    def enable_v2(self) -> None:
        """Declare TEST-only xvYCC records explicitly, without large fake source size."""
        v2_project(self)
        receipt = self.producer / self.entry["admissionReceiptPath"]
        value = json.loads(receipt.read_text())
        value["decoded"]["facts"].update(sizeBytes=self.identity.size_bytes, width=160, height=90)
        receipt.write_text(json.dumps(value))
        self.entry["admissionReceiptSha256"] = file_hash(receipt)
        self.manifest({"sourceSizeBytes": self.identity.size_bytes,
                       "admissionReceiptSha256": self.entry["admissionReceiptSha256"]})
        (self.job / "input.json").write_text(json.dumps(self.value))

    def execute(self) -> OwnedProjectObservation:
        """Invoke the production typed adapter; all subprocess seams stay stubbed."""
        return project.run_project_observation_owned(self.value, self.job, self.context)

    def cleanup(self) -> None:
        """Close patched seams and delete only this fixture's temporary metadata."""
        self.stack.close()
        super().cleanup()
