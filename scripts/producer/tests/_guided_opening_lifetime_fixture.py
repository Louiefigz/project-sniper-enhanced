"""Tiny TEMP input/code/tool/source bytes; no real media, daemon or admission.

Only the configured implementation-root leaf is replaced with an owned TEMP
tree. All hash/stat/capture/lifetime functions are real. Mutation targets never
come from actual repository/tool inventories or the user's footage.
"""
from __future__ import annotations

import json
import socket
import stat
import tempfile
from pathlib import Path
from unittest.mock import patch

import guided_opening_lifetime
from cut_preview_io import digest, file_hash
from guided_opening_claim import HeldOpeningClaim
from guided_opening_execution import opening_clock
from guided_opening_inputs import OpeningInputs
from headless.external_media_verification import SourceVerificationRuntime, VerifiedSnapshotIdentity, snapshot_stat_identity
from ingest_media_observation import SourceVerificationCapture


class OpeningLifetimeFixture:
    """Explicit TEST admission documents and real initial hash-pass identities."""

    def __init__(self, case: object) -> None:
        """Register fixture cleanup before creating only owned single-link files."""
        directory = tempfile.TemporaryDirectory(prefix="sniper-opening-lifetime-TEST-", dir="/private/tmp")
        case.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.socket = socket.socket(socket.AF_UNIX)
        case.addCleanup(self.socket.close)
        self.socket.bind(str(self.root / "docker.sock"))
        self.clock = opening_clock(60)
        self.paths = {}
        self.patch = patch.object(guided_opening_lifetime, "REPOSITORY_ROOT", self.root / "repo")
        self.patch.start()
        case.addCleanup(self.patch.stop)
        self._prepare()

    def put(self, name: str, raw: bytes) -> Path:
        """New-only tiny test data; never accept a discovered external mutation path."""
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as output:
            output.write(raw)
        self.paths[name] = path
        return path

    def json(self, name: str, value: dict) -> Path:
        """Write explicit TEST metadata without representing it as admitted media."""
        return self.put(name, json.dumps(value).encode())

    @staticmethod
    def ref(path: Path) -> dict:
        """Reference real tiny TEST bytes with an independently observed SHA."""
        return {"path": str(path), "sha256": file_hash(path)}

    def _pipeline(self) -> tuple[dict, dict]:
        """One actual mirrored source, an asset, and three tiny non-executable tools."""
        live = self.put("repo/scripts/TEST.py", b"TEST implementation\n")
        copied = self.put("pipeline/files/scripts/TEST.py", live.read_bytes())
        asset = self.put("pipeline/files/templates/TEST.html", b"TEST template\n")
        rows = [{"path": str(path.relative_to(copied.parents[1])), "hash": file_hash(path)}
                for path in (copied, asset)]
        lock = self.json("pipeline/pipeline-lock.json", {"schemaVersion": 1, "state": "pinned",
            "runId": "TEST", "files": rows, "digest": digest(rows)})
        expected = {"snapshotRoot": str(copied.parents[1]), "lockPath": str(lock),
                    "lockSha256": file_hash(lock), "digest": digest(rows)}
        observed = {"schemaVersion": 1, "kind": "guided-opening-executed-pipeline",
            "pipelineDigest": digest(rows), "lockSha256": file_hash(lock), "pinnedFileCount": len(rows),
            "executionClosure": [{"path": "scripts/TEST.py", "sha256": file_hash(live)}],
            "tools": {name: self.ref(self.put("tools/" + name, b"TEST tool " + name.encode()))
                      for name in ("python", "ffmpeg", "ffprobe")}}
        return expected, observed

    def _prepare(self) -> None:
        """Finish genuine source capture, then hold explicit TEST claim/control bytes."""
        source = self.put("media/TEST-source.bin", b"TEST source bytes\n")
        sha = file_hash(source)
        identity = VerifiedSnapshotIdentity(str(source), sha, source.stat().st_size, snapshot_stat_identity(source.lstat()))
        capture = SourceVerificationCapture(SourceVerificationRuntime(self.clock.remaining))
        capture.add(identity)
        verified = capture.finish([{"snapshotPath": str(source), "sha256": sha, "sizeBytes": identity.size_bytes}])
        expected, self.pipeline = self._pipeline()
        document = self.json("docs/TEST-plan.json", {"TEST": "original"})
        value = {"pipeline": expected, "documents": {"candidatePlan": self.ref(document)}}
        input_path = self.json("input.json", value)
        self.inputs = OpeningInputs(input_path, file_hash(input_path), value, {"candidatePlan": {"TEST": "original"}}, verified)
        docker = self.put("tools/docker", b"TEST docker, never executable")
        approval = self.json("pipeline/files/TEST-approval.json", {"TEST": True})
        socket_info = (self.root / "docker.sock").lstat()
        runtime = {"dockerPath": str(docker), "dockerSha256": file_hash(docker),
            "imageApprovalPath": str(approval), "imageApprovalSha256": file_hash(approval),
            "dockerSocketPath": str(self.root / "docker.sock"), "dockerSocketDevice": str(socket_info.st_dev),
            "dockerSocketInode": str(socket_info.st_ino)}
        claim_path = self.json("claim.json", {"runtime": runtime, "TEST": "claim"})
        self.claim = HeldOpeningClaim(claim_path, file_hash(claim_path), {"runtime": runtime, "TEST": "claim"})

    def hold(self) -> guided_opening_lifetime.OpeningSourceLifetime:
        """Run the actual production holder; no entire admission/guard mock exists."""
        return guided_opening_lifetime.OpeningSourceLifetime(self.inputs, self.claim, self.pipeline, self.clock)

    def change(self, name: str) -> None:
        """Mutate only a named file this fixture created, never inventory-selected paths."""
        path = self.paths[name]
        info = path.lstat()
        if path.parent.is_relative_to(self.root) and path.resolve(strict=True) == path \
                and stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
            path.write_bytes(b"TEST changed bytes\n")
            return
        raise RuntimeError("TEST refuses mutation outside original owned regular fixture file")
