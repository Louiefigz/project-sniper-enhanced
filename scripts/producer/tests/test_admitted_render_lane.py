"""Production attempt-only facade regressions for admitted overlay rendering."""

from __future__ import annotations

import dataclasses
import inspect
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from _common import pl  # noqa: F401
from headless import admitted_render_lane as lane_module
from headless import render_admission_artifact as artifact_module
from headless.admitted_render_lane import (
    AdmittedRenderLane,
    AdmittedRenderLaneError,
)
from headless.admission_registry import AdmissionError
from headless.controller_ownership import controller_ownership
from headless.render_admission import (
    AdmittedRenderRef,
    RenderAdmissionMetadata,
    admit_render_artifact,
)
from headless.render_admission_artifact import (
    RenderArtifactRequest,
    store_render_admission_artifact,
)
from headless.render_lane import RENDERER_MODE, RenderExecutionPolicy
from headless.render_runtime import RendererRuntime

PRODUCER_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = PRODUCER_DIR.parents[1]
ATTEMPT = "22222222-2222-4222-8222-222222222222"
BUILD_A = {"schemaVersion": 1, "policy": "lane-a", "implementation": []}
BUILD_B = {"schemaVersion": 1, "policy": "lane-b", "implementation": []}


def _entry(label: str, duration: float) -> dict:
    return {
        "kind": "section-marker",
        "outStart": 0,
        "outEnd": duration,
        "anchor": "free-band",
        "spec": {
            "num": "System No.1",
            "line1": label,
            "line2": "Rule",
            "side": "left",
            "accent": "#054BC9",
        },
    }


def _request() -> dict:
    return {
        "schemaVersion": 1,
        "operation": "render-overlays",
        "overlays": [
            {"overlayId": "overlay-1", "entry": _entry("First", 2.5)},
            {"overlayId": "overlay-2", "entry": _entry("Second", 3.0)},
        ],
    }


class AdmittedRenderLaneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.authority = self.root / "authority"
        self.authority.mkdir(mode=0o700)
        os.chmod(self.authority, 0o700)
        self.runtime = RendererRuntime(
            str(REPO_ROOT),
            str(REPO_ROOT),
            "/test/python",
            "/test/docker",
            "/test/docker.sock",
            "sha256:" + "1" * 64,
            "501:20",
            "/test/ffmpeg",
            "/test/ffprobe",
            30,
        )
        with mock.patch.object(
            artifact_module,
            "current_render_build_manifest",
            return_value=BUILD_A,
        ):
            self.artifact = store_render_admission_artifact(
                RenderArtifactRequest(
                    str(self.authority),
                    "authority-mp4-v1",
                    _request(),
                    self.runtime,
                )
            )
        metadata = RenderAdmissionMetadata(
            str(self.authority),
            "authority-mp4-v1",
            "11111111-1111-4111-8111-111111111111",
            ATTEMPT,
            "33333333-3333-4333-8333-333333333333",
            "2026-07-19T12:00:00+00:00",
            "release-test",
            "policy-test",
            None,
        )
        self.admitted = admit_render_artifact(
            metadata, self.artifact, "boot-a"
        )
        self.reference = self.admitted.reference
        self.boot = mock.patch(
            "headless.controller_ownership.read_boot_id", return_value="boot-a"
        )
        self.durability_boot = mock.patch(
            "headless.durability_controller.read_boot_id",
            return_value="boot-a",
        )
        self.lane_boot = mock.patch.object(
            lane_module, "read_boot_id", return_value="boot-a"
        )
        self.boot.start()
        self.durability_boot.start()
        self.lane_boot.start()
        self.addCleanup(self.boot.stop)
        self.addCleanup(self.durability_boot.stop)
        self.addCleanup(self.lane_boot.stop)

    def _lane(self, lease) -> AdmittedRenderLane:
        return AdmittedRenderLane(
            self.runtime, RenderExecutionPolicy(RENDERER_MODE), lease
        )

    def test_prepare_imports_all_retained_overlays_without_live_source(
        self,
    ) -> None:
        with controller_ownership(
            str(self.authority)
        ) as lease, mock.patch.object(
            lane_module, "current_render_build_manifest", return_value=BUILD_A
        ), mock.patch(
            "headless.overlay_source_seal._read_composition",
            side_effect=AssertionError("live source read"),
        ):
            lane = self._lane(lease)
            first = lane.prepare(self.reference)
            second = lane.prepare(self.reference)
        self.assertEqual(first, second)
        self.assertEqual(first.overlay_count, 2)
        self.assertEqual(first.artifact_digest, self.artifact.artifact_digest)
        seals = (
            self.authority / "attempts" / ATTEMPT / "work" / "overlay-seals"
        )
        self.assertEqual(
            len(
                [
                    path
                    for path in seals.iterdir()
                    if not path.name.startswith(".pending-")
                ]
            ),
            2,
        )
        for directory in seals.iterdir():
            self.assertTrue((directory / "render-input.tar").is_file())

    def test_launch_executes_every_overlay_once_and_blocks_relaunch(
        self,
    ) -> None:
        rendered = []
        simultaneous = threading.Barrier(2)

        def fake_launch(prepared, _launch):
            simultaneous.wait(timeout=2)
            rendered.append(prepared.artifact.overlay_id)
            return {"selectionId": prepared.artifact.overlay_id}

        with controller_ownership(
            str(self.authority)
        ) as lease, mock.patch.object(
            lane_module, "current_render_build_manifest", return_value=BUILD_A
        ), mock.patch(
            "headless.render_lane.current_render_build_manifest",
            return_value=BUILD_A,
        ):
            lane = self._lane(lease)
            with mock.patch.object(
                lane, "_launch_one", side_effect=fake_launch
            ):
                results = lane.launch(self.reference)
                with self.assertRaisesRegex(
                    AdmittedRenderLaneError, "ADMITTED phase"
                ):
                    lane.launch(self.reference)
        self.assertCountEqual(rendered, ["overlay-1", "overlay-2"])
        self.assertEqual(
            [row["selectionId"] for row in results], ["overlay-1", "overlay-2"]
        )

    def test_parallel_failure_does_not_start_the_next_batch(self) -> None:
        lane = self._lane(mock.Mock())
        started = []
        simultaneous = threading.Barrier(2)
        items = tuple(
            SimpleNamespace(
                name=name,
                artifact=SimpleNamespace(resolved=SimpleNamespace(key=key)),
            )
            for name, key in (
                ("first", "a"),
                ("second", "b"),
                ("never-started", "c"),
            )
        )

        def fake_launch(item, _launch):
            started.append(item.name)
            simultaneous.wait(timeout=2)
            if item.name == "first":
                raise RuntimeError("first batch failed")
            return {"selectionId": item.name}

        with mock.patch.object(lane, "_launch_one", side_effect=fake_launch):
            with self.assertRaisesRegex(RuntimeError, "first batch failed"):
                lane._render_overlays(items, mock.Mock())
        self.assertCountEqual(started, ["first", "second"])

    def test_identical_cache_keys_are_split_across_batches(self) -> None:
        lane = self._lane(mock.Mock())
        items = tuple(
            SimpleNamespace(
                name=name,
                artifact=SimpleNamespace(resolved=SimpleNamespace(key=key)),
            )
            for name, key in (
                ("first", "same"),
                ("second", "same"),
                ("other", "other"),
            )
        )
        first = lane._next_batch(items)
        second = lane._next_batch(items[len(first) :])
        self.assertEqual([item.name for item in first], ["first"])
        self.assertEqual([item.name for item in second], ["second", "other"])

    def test_real_launch_one_accepts_the_bound_build_context(self) -> None:
        with controller_ownership(
            str(self.authority)
        ) as lease, mock.patch.object(
            lane_module, "current_render_build_manifest", return_value=BUILD_A
        ), mock.patch(
            "headless.render_lane.current_render_build_manifest",
            return_value=BUILD_A,
        ):
            lane = self._lane(lease)
            admitted = lane_module.load_admitted_render(self.reference)
            prepared = lane._prepare(admitted)
            identity = (
                ATTEMPT,
                self.artifact.artifact_digest,
                prepared.build.build_digest,
                self.runtime.image_id,
            )
            binding = lane_module.prepare_attempt_cache(
                admitted.attempt_root, identity
            )
            launch = lane_module._LaunchContext(
                admitted.attempt_root,
                ATTEMPT,
                self.artifact.artifact_digest,
                prepared.build,
                binding,
            )
            with mock.patch.object(
                lane_module, "container_lease"
            ) as resource, mock.patch.object(
                lane,
                "_invoke_worker",
                return_value=SimpleNamespace(stdout="{}"),
            ), mock.patch.object(
                lane, "_finish_worker", return_value={"ok": True}
            ):
                resource.return_value.__enter__.return_value = (
                    "sniper-render-" + "a" * 32
                )
                result = lane._launch_one(prepared.overlays[0], launch)
        self.assertEqual(result, {"ok": True})

    def test_live_build_drift_rejects_before_attempt_seals_or_spawn(
        self,
    ) -> None:
        with controller_ownership(
            str(self.authority)
        ) as lease, mock.patch.object(
            lane_module, "current_render_build_manifest", return_value=BUILD_B
        ):
            lane = self._lane(lease)
            with self.assertRaisesRegex(AdmittedRenderLaneError, "build"):
                lane.prepare(self.reference)
        seals = (
            self.authority / "attempts" / ATTEMPT / "work" / "overlay-seals"
        )
        self.assertFalse(seals.exists())

    def test_cache_preflight_failure_leaves_attempt_admitted(self) -> None:
        cache = (
            self.authority / "attempts" / ATTEMPT / "work" / "graphics-cache"
        )
        cache.mkdir(parents=True, mode=0o700)
        os.chmod(cache.parent, 0o700)
        os.chmod(cache, 0o700)
        owner = cache / ".owner.json"
        owner.write_text("{}", encoding="ascii")
        os.chmod(owner, 0o600)
        with controller_ownership(
            str(self.authority)
        ) as lease, mock.patch.object(
            lane_module, "current_render_build_manifest", return_value=BUILD_A
        ):
            with self.assertRaisesRegex(RuntimeError, "owner receipt"):
                self._lane(lease).launch(self.reference)
        admitted = lane_module.load_admitted_render(self.reference)
        self.assertEqual(admitted.admission.trace_state.phase, "ADMITTED")

    def test_attempt_path_replacement_during_render_rejects_handoff(
        self,
    ) -> None:
        attempt = self.authority / "attempts" / ATTEMPT
        displaced = self.authority / "attempts" / "displaced-attempt"

        def replace_attempt(_overlays, _launch):
            attempt.rename(displaced)
            attempt.mkdir(mode=0o700)
            os.chmod(attempt, 0o700)
            return ({"selectionId": "overlay-1"},)

        with controller_ownership(
            str(self.authority)
        ) as lease, mock.patch.object(
            lane_module, "current_render_build_manifest", return_value=BUILD_A
        ), mock.patch(
            "headless.render_lane.current_render_build_manifest",
            return_value=BUILD_A,
        ):
            lane = self._lane(lease)
            with mock.patch.object(
                lane, "_render_overlays", side_effect=replace_attempt
            ), self.assertRaisesRegex(RuntimeError, "identity changed"):
                lane.launch(self.reference)
        self.assertTrue((displaced / "trace.jsonl").is_file())
        self.assertFalse((attempt / "trace.jsonl").exists())

    def test_manual_unadmitted_attempt_never_reaches_renderer(self) -> None:
        manual = "44444444-4444-4444-8444-444444444444"
        attempts = self.authority / "attempts"
        path = attempts / manual
        path.mkdir(mode=0o700)
        os.chmod(path, 0o700)
        with controller_ownership(str(self.authority)) as lease:
            lane = self._lane(lease)
            with self.assertRaises(AdmissionError), mock.patch.object(
                lane, "_launch_one"
            ) as spawn:
                lane.launch(AdmittedRenderRef(str(self.authority), manual))
        spawn.assert_not_called()

    def test_wrong_boot_and_expired_controller_lease_reject(self) -> None:
        with controller_ownership(
            str(self.authority)
        ) as lease, mock.patch.object(
            lane_module, "current_render_build_manifest", return_value=BUILD_A
        ):
            lane = self._lane(lease)
            with mock.patch.object(
                lane_module, "read_boot_id", return_value="boot-b"
            ), self.assertRaisesRegex(AdmittedRenderLaneError, "boot"):
                lane.prepare(self.reference)
        with self.assertRaisesRegex(RuntimeError, "expired"):
            lane.prepare(self.reference)

    def test_public_surface_has_no_loose_render_selection(self) -> None:
        fields = {
            field.name for field in dataclasses.fields(AdmittedRenderRef)
        }
        self.assertEqual(fields, {"authority_root", "attempt_id"})
        prepare = tuple(
            inspect.signature(AdmittedRenderLane.prepare).parameters
        )
        launch = tuple(inspect.signature(AdmittedRenderLane.launch).parameters)
        self.assertEqual(prepare, ("self", "reference"))
        self.assertEqual(launch, ("self", "reference"))
        source = inspect.getsource(lane_module)
        for forbidden in (
            "store_request_artifact",
            "select_overlay(",
            "prepare_overlay(",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
