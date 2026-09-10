"""Four actual TEST metadata files; intake/admission/runtime provenance is NOT qualified."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

from _source_color_staging_fixture import staging_fixture
from cut_preview_io import digest
from guided_opening_claim import HeldOpeningClaim
from guided_opening_inputs import DOCUMENTS, OpeningInputs, PROFILE
from guided_source_color_staging_read import SourceColorStagingReadContext, read_source_color_staging


def _relocate(value: object, root: Path) -> object:
    """Move inert fixture paths only into a newly allocated canonical TEST tree."""
    if type(value) is str:
        return value.replace("/TEST/source-color-project", str(root / "project")).replace("/TEST/workspace", str(root))
    if type(value) is dict:
        return {key: _relocate(row, root) for key, row in value.items()}
    if type(value) is list:
        return [_relocate(row, root) for row in value]
    return value


def _raw(value: dict) -> bytes:
    """Use literal UTF-8 JSON/newline, not a semantic digest or real TS publication."""
    return (json.dumps(value, ensure_ascii=False, indent=1, allow_nan=False) + "\n").encode()


class SourceColorStagingReadFixture:
    """Original typed TEST metadata, exact raw refs and virtual original clock."""

    def __init__(self) -> None:
        """Create only four allowed metadata artifacts, with no source or job files."""
        self.temporary = tempfile.TemporaryDirectory(prefix="source-color-staging-read-TEST-")
        self.root = Path(self.temporary.name).resolve()
        sidecar, reservation = staging_fixture()
        self.sidecar, self.reservation = _relocate(sidecar, self.root), _relocate(reservation, self.root)
        self.sidecar_path = Path(self.reservation["sidecarPath"])
        self.reservation_path = Path(self.sidecar["reservation"]["path"])
        self.claim_path = Path(self.sidecar["opening"]["claimPath"])
        self.input_path = Path(self.sidecar["opening"]["inputPath"])
        self.allowed = frozenset((self.sidecar_path, self.reservation_path, self.claim_path, self.input_path))
        self.guard, self.now = Mock(), 1000.0
        self.documents = self._documents()
        self.input = {"schemaVersion": 1, "kind": "guided-opening-media-input", "executionId": self.sidecar["opening"]["executionId"],
                      "profile": PROFILE, "documents": {key: {"path": str(self.root / f"TEST-{key}.json"), "sha256": "7" * 64}
                                                         for key in DOCUMENTS}, "pipeline": {"snapshotRoot": "/TEST/inert-snapshot"}}
        self.input["executionInputHash"] = digest(self.input)
        opening = self.sidecar["opening"]
        self.claim = {"schemaVersion": 1, "kind": "guided-opening-execution-claim", "scope": "private-opening-owned-execution-not-approval",
                      "requestId": self.claim_path.parts[-4], "executionId": opening["executionId"], "selectedGraphicOrders": [],
                      "runtime": deepcopy(self.reservation["runtime"]), "outputRoot": str(self.claim_path.parent / "media-output"),
                      **{key: opening[key] for key in ("inputPath", "inputSha256", "executionInputHash", "clockHash",
                                                       "generationStartedAt", "beforeJournalHash", "budgetAdmissionHash")}}
        self.refresh()

    def _documents(self) -> dict:
        """Keep original clock/cut shape only; this is not a real14-document intake."""
        result = {key: {"TEST": "not validated intake or source evidence"} for key in DOCUMENTS}
        result["authority"] = {"clockHash": self.sidecar["opening"]["clockHash"],
                               "generationStartedAt": self.sidecar["opening"]["generationStartedAt"], "review": {"endFrameExclusive": 24}}
        result["frameBindings"] = {"graphics": []}
        result["acceptedPlan"] = {"cutTrack": [{"sourceId": name, "start": 0, "end": 1} for name in ("raw-b", "raw-a", "raw-b")]}
        result["candidatePlan"] = deepcopy(result["acceptedPlan"])
        return result

    def write(self, path: Path, raw: bytes) -> str:
        """Write only named canonical TEST-root regular single-link owned files."""
        if path not in self.allowed or not path.is_relative_to(self.root):
            raise AssertionError("TEST write target is outside explicit owned metadata")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.parent.resolve(strict=True) != path.parent:
            raise AssertionError("TEST write parent is aliased")
        flags = os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        if path.exists() or path.is_symlink():
            before = path.lstat()
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_uid != os.geteuid():
                raise AssertionError("TEST write target is not owned regular single-link")
            path.chmod(0o600)
        else:
            flags |= os.O_CREAT | os.O_EXCL
        descriptor = os.open(path, flags, 0o600)
        try:
            current = os.fstat(descriptor)
            if (current.st_dev, current.st_ino) != (path.lstat().st_dev, path.lstat().st_ino):
                raise AssertionError("TEST write target changed before truncation")
            os.ftruncate(descriptor, 0)
            with os.fdopen(descriptor, "wb", closefd=False) as handle:
                handle.write(raw)
            os.fchmod(descriptor, 0o400)
        finally:
            os.close(descriptor)
        return hashlib.sha256(raw).hexdigest()

    def refresh(self) -> None:
        """Publish fresh exact TEST refs before an invocation; never during a held read."""
        input_sha = self.write(self.input_path, _raw(self.input))
        self.claim.update(inputSha256=input_sha, executionInputHash=self.input["executionInputHash"])
        claim_sha = self.write(self.claim_path, _raw(self.claim))
        self.sidecar["opening"].update(claimSha256=claim_sha, inputSha256=input_sha, executionInputHash=self.input["executionInputHash"])
        self.reservation["opening"] = deepcopy(self.sidecar["opening"])
        self.reservation["ownerPid"] = os.getppid()
        self.republish_staging()
        self.inputs = OpeningInputs(self.input_path, input_sha, deepcopy(self.input), deepcopy(self.documents))
        self.opening = HeldOpeningClaim(self.claim_path, claim_sha, deepcopy(self.claim))
        self.context = SourceColorStagingReadContext(self.inputs, self.opening, Path(self.sidecar["producerDir"]),
                                                   self.reservation_path.parent, 1300.0, self.guard)

    def republish_staging(self) -> None:
        """Refresh only explicit TEST staging bytes before an independent invocation."""
        raw = _raw(self.reservation)
        reservation_sha = self.write(self.reservation_path, raw)
        self.sidecar["reservation"] = {"path": str(self.reservation_path), "sha256": reservation_sha, "sizeBytes": len(raw)}
        self.republish_sidecar()

    def republish_sidecar(self) -> None:
        """Change the externally supplied TEST sidecar digest without touching other refs."""
        self.reference = (self.sidecar_path, self.write(self.sidecar_path, _raw(self.sidecar)))

    def run(self) -> object:
        """Use actual raw readers and pure contract; no process or admission seams."""
        return read_source_color_staging(self.reference, self.context)

    def close(self) -> None:
        """Remove only this exact allocated TEST metadata tree."""
        self.temporary.cleanup()
