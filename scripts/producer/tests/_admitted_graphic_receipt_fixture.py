"""Inert completed-lane boundary for durable receipt/controller unit tests.

Retired source metadata is never sent through prepare or live launch. Real
current source admission is tested separately without this private fixture.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from _current_build_release_fixture import current_manifest
from _render_lane_proof import ProofInputs, build_full_proof
from _retired_r0_artifact_fixture import inert_artifact_sources, store_test_artifact
from headless.render_build_receipt import store_render_build
from headless.render_lane_cache import prepare_attempt_cache
from headless.resource_ledger import ResourceRequest
from headless.durability_controller import _trace
from headless import admitted_render_lane as lane_module
from headless import render_admission_artifact as artifact_module
from headless.admitted_graphic_receipt_controller import (
    AdmittedGraphicRenderReceiptController,
    GraphicRenderReceiptControllerAuthorityV1,
)
from headless.admitted_render_lane import AdmittedRenderLane
from headless.controller_ownership import controller_ownership
from headless.render_admission import (
    RenderAdmissionMetadata,
    admit_render_artifact,
)
from headless.render_admission_artifact import (
    RenderArtifactRequest,
)
from headless.render_lane import RENDERER_MODE, RenderExecutionPolicy
from headless.render_runtime import RendererRuntime

PRODUCER_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = PRODUCER_DIR.parents[1]
ATTEMPT = "22222222-2222-4222-8222-222222222222"
CONTAINER_NAME = "sniper-render-" + "d" * 32
OUTER_REQUEST_DIGEST = "c" * 64
QUALITY_POLICY_ID = "d" * 64


def _entry() -> dict:
    return {
        "id": "g-00000001",
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


def _request() -> dict:
    return {
        "schemaVersion": 1,
        "operation": "render-overlays",
        "overlays": [{"overlayId": "g-00000001", "entry": _entry()}],
    }


class AdmittedGraphicReceiptFixture:
    """Historical storage/ledger unit with strict completed-result validation."""

    def __init__(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.authority_root = self.root / "authority"
        self.authority_root.mkdir(mode=0o700)
        os.chmod(self.authority_root, 0o700)
        self.manifest = current_manifest("admitted-graphic-receipt")
        self.runtime = self._runtime()
        self._boot_patches = self._start_boot_patches()
        with inert_artifact_sources():
            self.artifact = self._store_artifact()
            self.admitted = self._admit()
        self.reference = self.admitted.reference

    def _runtime(self) -> RendererRuntime:
        return RendererRuntime(
            str(REPO_ROOT),
            str(REPO_ROOT),
            "/test/python",
            "/test/docker",
            "/test/docker.sock",
            self.manifest["imageId"],
            "501:20",
            "/test/ffmpeg",
            "/test/ffprobe",
            30,
        )

    @staticmethod
    def _start_boot_patches() -> tuple[mock._patch, ...]:
        patches = (
            mock.patch(
                "headless.controller_ownership.read_boot_id",
                return_value="boot-a",
            ),
            mock.patch(
                "headless.durability_controller.read_boot_id",
                return_value="boot-a",
            ),
            mock.patch.object(
                lane_module, "read_boot_id", return_value="boot-a"
            ),
        )
        for patch in patches:
            patch.start()
        return patches

    def _store_artifact(self):
        with mock.patch.object(
            artifact_module,
            "current_render_build_manifest",
            return_value=self.manifest,
        ):
            return store_test_artifact(
                RenderArtifactRequest(
                    str(self.authority_root),
                    "authority-mp4-v1",
                    _request(),
                    self.runtime,
                )
            )

    def _admit(self):
        metadata = RenderAdmissionMetadata(
            str(self.authority_root),
            "authority-mp4-v1",
            "11111111-1111-4111-8111-111111111111",
            ATTEMPT,
            "33333333-3333-4333-8333-333333333333",
            "2026-07-19T12:00:00+00:00",
            "release-test",
            "render-execution-policy",
            None,
        )
        return admit_render_artifact(metadata, self.artifact, "boot-a")

    def _synthetic_result(self, context: object) -> SimpleNamespace:
        seal = context.seal
        path = Path(context.binding.cache_dir) / f"{seal.key}.mov"
        path.write_bytes(b"synthetic-parent-validated-prores-bytes")
        path.chmod(0o600)
        proof = build_full_proof(
            path,
            seal.key,
            self.runtime.image_id,
            ProofInputs(seal.expected_copy, seal.snapshot),
        )
        proof["asset"]["width"], proof["asset"]["height"] = seal.dimensions
        proof["occupancy"]["canvasPx"] = list(seal.dimensions)
        # TEST metadata names the current image/quota contract;
        # the shared historical proof factory remains unchanged.
        runtime = proof["runtimeAttestation"]
        version_label = "io.project-sniper.hyperframes-version"
        runtime["imageAttestation"]["Config"]["Labels"] = {version_label: "0.8.31"}
        for key in ("containerBeforeOutput", "containerAfterOutput"):
            runtime[key]["Config"]["Labels"][version_label] = "0.8.31"
            runtime[key]["HostConfig"]["Tmpfs"]["/output"] = (
                "rw,nosuid,nodev,noexec,size=2g,uid=501,gid=20,mode=0700")
        disk = {key: value for key, value in proof.items() if key != "sidecar"}
        Path(proof["sidecar"]).write_text(json.dumps(disk), encoding="utf-8")
        result = {
            "cached": False,
            "fps": "30",
            "fmt": seal.fmt,
            "key": seal.key,
            "kind": seal.entry["kind"],
            "path": str(path),
            "proof": proof,
        }
        return SimpleNamespace(stdout=json.dumps(result))

    def _completed_boundary(self, lane: AdmittedRenderLane) -> tuple[dict, ...]:
        """Supply a synthetic completed result; exercise real proof/ledger checks."""
        admitted = self.admitted
        record = admitted.admission.record
        _trace(str(self.authority_root), record, "boot-a").append(
            "WORKER_START", {"operation": "render-overlays", "overlayCount": 1})
        build = store_render_build(admitted.attempt_root, self.manifest)
        identity = (record["attemptId"], admitted.artifact.artifact_digest,
                    build.build_digest, self.runtime.image_id)
        binding = prepare_attempt_cache(admitted.attempt_root, identity)
        launch = lane_module._LaunchContext(
            admitted.attempt_root, record["attemptId"],
            admitted.artifact.artifact_digest, build, binding)
        artifact = admitted.artifact.overlays[0]
        resources = ResourceRequest(admitted.attempt_root, record["attemptId"],
            self.runtime.docker, self.runtime.docker_socket, self.runtime.image_id,
            self.runtime.user_id)
        context = lane_module._WorkerContext(
            launch, SimpleNamespace(artifact=artifact), artifact.resolved,
            binding, CONTAINER_NAME, resources)
        return (lane._finish_worker(context, self._synthetic_result(context).stdout),)

    @contextlib.contextmanager
    def controller(self) -> Iterator[tuple[
            AdmittedGraphicRenderReceiptController, AdmittedRenderLane, mock.Mock]]:
        """Keep storage semantics real while replacing the completed-lane seam."""
        authority = GraphicRenderReceiptControllerAuthorityV1(
            OUTER_REQUEST_DIGEST, QUALITY_POLICY_ID)
        with inert_artifact_sources(), controller_ownership(str(self.authority_root)) as lease:
            lane = AdmittedRenderLane(self.runtime, RenderExecutionPolicy(RENDERER_MODE), lease)
            with mock.patch(
                "headless.render_lane.current_render_build_manifest", return_value=self.manifest
            ), mock.patch.object(
                lane, "_invoke_worker", side_effect=AssertionError("TEST cannot execute R0")
            ), mock.patch.object(
                lane, "_launch_locked", side_effect=lambda *_: self._completed_boundary(lane)
            ) as completed:
                yield AdmittedGraphicRenderReceiptController(lane, authority), lane, completed

    def close(self) -> None:
        """Release only this fixture's test patches and temporary files."""
        for patch in reversed(self._boot_patches):
            patch.stop()
        self.temp.cleanup()
