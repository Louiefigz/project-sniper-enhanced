"""Shared sealed render-lane test authority and worker fixtures."""

from __future__ import annotations

import contextlib
import json
import os
import stat
import subprocess
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

from _render_lane_proof import IMAGE_ID, ProofInputs, build_full_proof
from headless.overlay_seal import OverlaySealBinding, load_overlay
from headless.overlay_seal_store import OverlaySealLocator
from headless.overlay_source_seal import ResolvedOverlaySeal
from headless.process_runner import ProcessRequest
from headless.render_lane import (
    OverlayLaunchRequest,
    OverlayPreparationRequest,
    RendererRuntime,
    prepare_overlay_launch,
)
from headless.request_artifact import store_request_artifact

PRODUCER_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = PRODUCER_DIR.parents[1]

CONTAINER_NAME = "sniper-render-" + "d" * 32
NEXT_CONTAINER_NAME = "sniper-render-" + "e" * 32


@contextlib.contextmanager
def fake_container_lease(_request: object) -> Iterator[str]:
    """Yield the deterministic fixture container name."""
    yield CONTAINER_NAME


class RenderLaneFixture(unittest.TestCase):
    """Private authority, attempt, tools, and successful worker response."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.authority = self.root / "authority"
        self.authority.mkdir(mode=0o700)
        os.chmod(self.authority, 0o700)
        attempts = self.authority / "attempts"
        attempts.mkdir(mode=0o700)
        os.chmod(attempts, 0o700)
        self.attempt = attempts / "attempt-a"
        self.attempt.mkdir(mode=0o700)
        os.chmod(self.attempt, 0o700)
        self.artifact = store_request_artifact(
            str(self.authority),
            {
                "schemaVersion": 1,
                "operation": "render-overlays",
                "overlays": [{"overlayId": "overlay-1", "entry": self._entry()}],
            },
        )
        self.executables: dict[str, str] = {}
        for name in ("python", "docker", "ffmpeg", "ffprobe"):
            path = self.root / name
            path.write_text(f"#!/bin/sh\n# {name}\nexit 0\n", encoding="utf-8")
            path.chmod(0o700)
            self.executables[name] = str(path)
        self.socket_path = str(self.root / "docker.sock")
        Path(self.socket_path).write_bytes(b"test socket placeholder")
        socket_check = mock.patch(
            "headless.render_lane.stat.S_ISSOCK", return_value=True
        )
        socket_check.start()
        self.addCleanup(socket_check.stop)
        socket_row = mock.patch(
            "headless.render_build._socket_row", side_effect=self._socket_metadata)
        socket_row.start()
        self.addCleanup(socket_row.stop)
        lease = mock.patch(
            "headless.render_lane.container_lease", side_effect=fake_container_lease
        )
        lease.start()
        self.addCleanup(lease.stop)

    @staticmethod
    def _socket_metadata(path: str) -> dict:
        """Describe a synthetic socket; this fixture performs no Docker I/O."""
        info = Path(path).stat()
        return {"path": path, "device": info.st_dev, "inode": info.st_ino,
                "mode": stat.S_IFSOCK, "ownerUid": info.st_uid}

    def _runtime(self, image_id: str = IMAGE_ID) -> RendererRuntime:
        return RendererRuntime(
            pipeline_root=str(REPO_ROOT),
            runtime_root=str(REPO_ROOT),
            python=self.executables["python"],
            docker=self.executables["docker"],
            docker_socket=self.socket_path,
            image_id=image_id,
            user_id="501:20",
            proof_ffmpeg=self.executables["ffmpeg"],
            proof_ffprobe=self.executables["ffprobe"],
            timeout_seconds=30,
        )

    @staticmethod
    def _entry() -> dict:
        return {
            "kind": "section-marker",
            "outStart": 0,
            "outEnd": 2.5,
            "anchor": "free-band",
            "spec": {
                "num": "Part 1",
                "line1": "The Setup",
                "line2": "Basics",
                "side": "left",
                "accent": "#054BC9",
            },
        }

    def _request(self) -> OverlayLaunchRequest:
        runtime = self._runtime()
        preparation = OverlayPreparationRequest(
            str(self.authority),
            str(self.attempt),
            "attempt-a",
            self.artifact,
            "overlay-1",
        )
        return prepare_overlay_launch(preparation, runtime)

    @staticmethod
    def _sealed(worker: dict) -> ResolvedOverlaySeal:
        locator = OverlaySealLocator(worker["sealPath"], worker["sealSha256"])
        binding = OverlaySealBinding(
            worker["attemptRoot"],
            worker["attemptId"],
            worker["requestDigest"],
            worker["buildDigest"],
            worker["selectionId"],
        )
        return load_overlay(locator, binding)

    @staticmethod
    def _fake_success(request: ProcessRequest) -> subprocess.CompletedProcess[str]:
        worker = json.loads(request.stdin_text)
        seal = RenderLaneFixture._sealed(worker)
        path = Path(worker["cacheDir"]) / (seal.key + ".mov")
        path.write_bytes(b"rendered")
        path.chmod(0o600)
        result = {
            "cached": False,
            "fmt": "mov",
            "fps": "30",
            "key": seal.key,
            "kind": "section-marker",
            "path": str(path),
            "proof": build_full_proof(
                path,
                seal.key,
                IMAGE_ID,
                ProofInputs(seal.expected_copy, seal.snapshot),
            ),
        }
        return subprocess.CompletedProcess(request.command, 0, json.dumps(result), "")
