"""Tiny real metadata fixture; socket-type is TEST-stubbed, no Docker/admission.

Only the preclaim/runtime metadata and fixed argv builder are exercised. The
executable is inert TEST text and opening document contents are not admitted.
Fault writes require exact fixture-owned canonical single-link regular files.
"""
from __future__ import annotations

import json
import os
import stat
import tempfile
import time
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import Mock, patch
from uuid import uuid4

from color.grade_observation_profile import V1_PROJECT_POLICY, V2
from cut_preview_io import digest, file_hash, write_new
from headless.container_policy import DockerRuntime
from headless.grade_launch_intent import HeldGradeLaunch, OwnedGradeLaunch, hold_grade_launch
from guided_opening_claim import verify_runtime_controls
from guided_opening_inputs import DOCUMENTS


class GradeLaunchFixture:
    """Build fresh prelaunch records before any original callback is invoked."""

    def __init__(self) -> None:
        """Keep every writable resource beneath one canonical TEST directory."""
        self.temporary = tempfile.TemporaryDirectory(prefix="sniper-grade-launch-")
        self.root = Path(self.temporary.name).resolve()
        self.producer = self.root / "producer"
        self.job_id = str(uuid4())
        self.directory = self.producer / ".sniper-grade-observations" / self.job_id / "execution"
        self.directory.mkdir(parents=True, mode=0o700)
        self.source = self.root / "test-source.bytes"
        self.source.write_bytes(b"TEST metadata source, not executable media")
        self.source.chmod(0o400)
        self.request = {"sourceSha256": file_hash(self.source), "frameCount": 24, "timeoutSeconds": 120}
        self.guard = Mock()
        self.stack = ExitStack()
        self.stack.enter_context(patch("headless.grade_launch_intent.verify_runtime_controls", side_effect=self._verify_runtime))
        self.runtime_controls = self._runtime()
        self.input_path = self.directory.parent / "input.json"
        write_new(self.input_path, {"schemaVersion": 1, "policy": V1_PROJECT_POLICY,
            "jobId": self.job_id, "producerDir": str(self.producer), "sourceId": "TEST",
            "declaration": {}, "expected": {"planSha256": "a" * 64, "manifestSha256": "b" * 64,
            "projectSha256": "c" * 64}, "ownerPid": os.getpid(), "implementationSha256": "d" * 64})
        self.opening_claim = self._opening()
        self.claim = self._claim()
        self.claim_path = self.directory.parent / "launch-claim.json"
        write_new(self.claim_path, self.claim)
        self.claim_path.chmod(0o400)
        self.owner = self.owner_for_current_claim()

    def _runtime(self) -> dict:
        """Use real bytes/inodes with only the socket file-type TEST-stubbed."""
        executable = self.root / "test-docker"
        executable.write_bytes(b"TEST inert executable, must never run")
        executable.chmod(0o700)
        endpoint = self.root / "docker.sock"
        endpoint.write_bytes(b"TEST socket sentinel, never a daemon")
        info = endpoint.stat()
        self.snapshot = self.root / "pinned"
        approval = self.snapshot / "scripts/producer/headless/render_image_approval.json"
        approval.parent.mkdir(parents=True)
        self.approval = {"schemaVersion": 1, "imageId": "sha256:" + "a" * 64, "testOnly": True}
        write_new(approval, self.approval)
        approval.chmod(0o644)  # Match the actual repository approval writer.
        self.runtime = DockerRuntime(str(executable), str(endpoint), self.approval["imageId"], "501:20", self.approval)
        return {"dockerPath": str(executable), "dockerSha256": file_hash(executable),
            "dockerSocketPath": str(endpoint), "dockerSocketDevice": str(info.st_dev),
            "dockerSocketInode": str(info.st_ino), "imageId": self.runtime.image_id, "userId": self.runtime.user_id,
            "imageApprovalPath": str(approval), "imageApprovalSha256": file_hash(approval), "runtimeRepoRoot": str(self.root)}

    def _opening(self) -> Path:
        """Keep original schema/clock refs without claiming full source admission."""
        execution_id = str(uuid4())
        opening = self.root / "opening"
        opening.mkdir(mode=0o700)
        input_path = opening / "input.json"
        value = {"schemaVersion": 1, "kind": "guided-opening-media-input", "executionId": execution_id,
            "profile": "unity-source-float-own-screen-v1", "documents": self._documents(opening),
            "pipeline": {"snapshotRoot": str(self.snapshot), "lockPath": str(self.root / "TEST-pipeline-lock.json"),
                         "lockSha256": "e" * 64, "digest": "f" * 64}}
        value["executionInputHash"] = digest(value)
        write_new(input_path, value)
        path = opening / "execution-claim.json"
        write_new(path, {"schemaVersion": 1, "kind": "guided-opening-execution-claim",
            "scope": "private-opening-owned-execution-not-approval", "requestId": str(uuid4()),
            "executionId": execution_id, "beforeJournalHash": "b" * 64,
            "inputPath": str(input_path), "inputSha256": file_hash(input_path),
            "executionInputHash": value["executionInputHash"], "outputRoot": str(opening),
            "clockHash": "c" * 64, "generationStartedAt": "2026-09-08T00:00:00.000Z",
            "budgetAdmissionHash": "d" * 64, "selectedGraphicOrders": [], "runtime": self.runtime_controls})
        return path

    def _documents(self, directory: Path) -> dict:
        """Use all actual reference roles, with explicitly unadmitted TEST bytes."""
        result = {}
        for name in sorted(DOCUMENTS):
            path = directory / f"{name}.json"
            write_new(path, {"testOnly": True, "role": name, "sourceAdmissionVerified": False})
            result[name] = {"path": str(path), "sha256": file_hash(path)}
        return result

    def _verify_runtime(self, runtime: dict, snapshot: str) -> None:
        """Retain real control checks except the explicitly synthetic socket type."""
        with patch("guided_opening_claim.stat.S_ISSOCK", return_value=True):
            verify_runtime_controls(runtime, snapshot)

    def _claim(self) -> dict:
        """Use the exact closed proposed production preclaim keys."""
        return {"schemaVersion": 1, "kind": "owned-grade-launch-claim",
            "scope": "preclaimed-source-observation-not-recovery-or-approval", "jobId": self.job_id,
            "inputPath": str(self.input_path), "inputSha256": file_hash(self.input_path),
            "executionDir": str(self.directory), "sourcePath": str(self.source),
            "sourceSha256": self.request["sourceSha256"], "frameCount": 24, "profile": None,
            "containerName": "sniper-grade-observation-" + self.job_id.replace("-", ""),
            "openingClaimPath": str(self.opening_claim), "openingClaimSha256": file_hash(self.opening_claim),
            "runtime": self.runtime_controls}

    def owner_for_current_claim(self) -> OwnedGradeLaunch:
        """Capture raw current TEST claim explicitly, never resume a held object."""
        return OwnedGradeLaunch(self.claim_path, file_hash(self.claim_path), time.monotonic() + 120, self.guard)

    def hold(self) -> HeldGradeLaunch:
        """Run the production metadata helper with its real runtime checker."""
        return hold_grade_launch(self.owner, str(self.source), self.request, self.directory)

    def enable_v2(self) -> None:
        """Author a distinct TEST v2 expectation before any held launch exists."""
        self.request.update(schemaVersion=2, profile=V2.token, timeoutSeconds=1200)
        value = json.loads(self.input_path.read_text())
        value.update(schemaVersion=2, policy=V2.project_policy, profile=V2.token)
        self.change(self.input_path, value)
        self.claim.update(profile=V2.token, inputSha256=file_hash(self.input_path))
        self.change(self.claim_path, self.claim)
        self.owner = self.owner_for_current_claim()

    def command(self) -> list[str]:
        """Use the unchanged pure command builder; no subprocess is started."""
        from headless.grade_observation_policy import _launch_command

        return _launch_command(self.runtime, (self.directory, self.claim["containerName"], str(self.source)), self.request)[0]

    def change(self, path: Path, value: dict | bytes) -> None:
        """Fault only an existing exact TEST-root-owned regular single-link file."""
        if path.resolve(strict=True) != path or not path.is_relative_to(self.root):
            raise RuntimeError("fault target is not the exact TEST root")
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
            raise RuntimeError("fault target is not one TEST-owned regular file")
        raw = json.dumps(value).encode() if type(value) is dict else value
        path.chmod(0o600)
        descriptor = os.open(path, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW)
        try:
            if (os.fstat(descriptor).st_dev, os.fstat(descriptor).st_ino) != (info.st_dev, info.st_ino):
                raise RuntimeError("TEST fault target changed during open")
            os.write(descriptor, raw)
        finally:
            os.close(descriptor)

    def close(self) -> None:
        """Close TEST patches and only the exact temporary metadata directory."""
        self.stack.close()
        self.temporary.cleanup()
