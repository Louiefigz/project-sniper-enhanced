"""Synthetic held metadata with real grade publication/sealing, never media proof.

Admission and native execution authenticity are explicit existing TEST stubs.
The actual raw record reader/validator, byte/stat holds, immutable publication,
completion sealing and supplemental metadata reader are exercised unchanged.
All writes belong to this fixture's canonical temporary root only.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from unittest.mock import patch

from _grade_contract_fixture import binding, declaration
from _grade_project_owned_fixture import OwnedGradeFixture
from color import grade_observation_read as reader
from color.grade_observation_profile import V1
from color.grade_project_completion import CompletedProjectObservation, seal_completed_project_observation
from cut_preview_io import file_hash, write_new
from test_grade_frame_adapter import decoder_terminal, observed_probe, raw_frame, text_frame


def identity_records(count: int = 3, source: dict | None = None) -> tuple[dict, dict, dict, list[dict]]:
    """Supply explicit H.264, square-SAR and siting metadata, not observed pixels."""
    context = declaration(count)
    source = source or binding(context)
    probe = observed_probe(source)
    video = probe["streams"][0]
    video.update(codec_name="h264", sample_aspect_ratio="1:1", chroma_location="left")
    rows = [{**raw_frame(index, source), "sample_aspect_ratio": "1:1", "chroma_location": "left"}
            for index in range(source["frameCount"])]
    return source, context, probe, rows


def identity_lines(rows: list[dict]) -> list[str]:
    """Produce known bounded default-writer metadata lines from supplied TEST rows."""
    return [line for row in rows for line in text_frame(row)]


class Bt709IdentityFixture(OwnedGradeFixture):
    """Real held metadata files and original lifetime, with no decoder or daemon."""

    def __init__(self) -> None:
        """Keep pre-publication mutators explicit and fault file targets closed."""
        super().__init__()
        self.metadata_mutator = lambda probe, rows: None
        execution = self.job / "execution"
        self.allowed_faults = {self.job / "parents.json", execution / "execution.json",
                               execution / "result/probe.json", execution / "result/frames.ffprobe"}

    def run_stub(self, source: str, request: dict, directory: Path, deadline: float) -> dict:
        """Write synthetic worker metadata only, using the real already-bound TEST source."""
        parents = json.loads((directory.parent / "parents.json").read_bytes())
        _source, _declaration, probe, rows = identity_records(source=parents["binding"])
        self.metadata_mutator(probe, rows)
        result = directory / "result"
        result.mkdir(mode=0o700)
        write_new(result / "probe.json", probe)
        (result / "frames.ffprobe").write_text("".join(identity_lines(rows)))
        worker = {"probe": {"sha256": file_hash(result / "probe.json")},
                  "decoder": {**decoder_terminal(len(rows)), "sha256": file_hash(result / "frames.ffprobe"),
                              "bytes": (result / "frames.ffprobe").stat().st_size}}
        self.execution = {"schemaVersion": 1, "policy": V1.policy, "status": "complete", "cleanupVerified": True,
            "cleanupMs": 0, "sourceBeforeSha256": file_hash(Path(source)), "sourceAfterSha256": file_hash(Path(source)),
            "executionSources": [], "worker": worker, "syntheticTestOnly": True, "deadline": deadline}
        write_new(directory / "execution.json", self.execution)
        return self.execution

    def read_stub(self, directory: Path, parents: tuple[dict, dict], execution: dict) -> reader.BoundGradeObservation:
        """Stub ONLY worker/image provenance; run the actual byte and V1 record reader."""
        with patch.object(reader, "_held_execution", return_value=execution["worker"]), \
                patch.object(reader, "implementation_sources", return_value=[]):
            self.returned = reader.read_observation(directory, parents, execution)
        return self.returned

    def completed(self) -> CompletedProjectObservation:
        """Exercise actual immutable publication and live sealing of the TEST observation."""
        return seal_completed_project_observation(self.execute())

    def rewrite(self, path: Path) -> None:
        """Refuse external/alias targets before rewriting a named single-link TEST file."""
        root = Path(self.temporary.name).resolve(strict=True)
        if root != self.root or path not in self.allowed_faults or path != path.resolve(strict=True) \
                or not path.is_relative_to(root):
            raise RuntimeError("fault target is not an exact allowed TEST-root file")
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
            raise RuntimeError("fault target is not a single-link TEST-owned regular file")
        path.write_bytes(path.read_bytes())
