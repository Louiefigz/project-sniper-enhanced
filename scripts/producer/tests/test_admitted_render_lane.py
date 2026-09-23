"""Retired execution refusal plus independent state/batching/identity units."""

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
from _current_build_release_fixture import current_manifest
from _retired_r0_artifact_fixture import inert_artifact_sources, store_test_artifact
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
BUILD_A = current_manifest("lane-a")
BUILD_B = current_manifest("lane-b")


def _entry(label: str, duration: float) -> dict:
    return {
        "kind": "section-marker",
        "outStart": 0,
        "outEnd": duration,
        "anchor": "free-band",
        "spec": {
            "num": "Part 1",
            "line1": label,
            "line2": "Basics",
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
        with inert_artifact_sources():
            with mock.patch.object(
                artifact_module,
                "current_render_build_manifest",
                return_value=BUILD_A,
            ):
                self.artifact = store_test_artifact(
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

    def test_retired_sources_cannot_prepare_or_launch(self) -> None:
        """A retained TEST ledger never grants present execution authority."""
        with controller_ownership(str(self.authority)) as lease:
            lane = self._lane(lease)
            for operation in (lane.prepare, lane.launch):
                with self.subTest(operation=operation.__name__), mock.patch.object(
                        lane, "_invoke_worker", side_effect=AssertionError("renderer forbidden")) as worker:
                    with self.assertRaisesRegex((ValueError, RuntimeError), "retired"):
                        operation(self.reference)
                    worker.assert_not_called()
        self.assertFalse((Path(self.admitted.attempt_root) / "work" / "overlay-seals").exists())
        self.assertFalse((Path(self.admitted.attempt_root) / "work" / "graphics-cache").exists())

    def test_live_build_drift_refuses_before_persistence(self) -> None:
        """Exercise build comparison directly, without loading retired source."""
        lane = self._lane(mock.Mock())
        with mock.patch.object(lane_module, "current_render_build_manifest", return_value=BUILD_B), \
                mock.patch.object(lane_module, "store_render_build") as store:
            with self.assertRaisesRegex(AdmittedRenderLaneError, "build"):
                lane._validated_build(self.admitted)
        store.assert_not_called()

    def test_terminal_started_and_wrong_boot_metadata_reject(self) -> None:
        """State guards remain testable on non-executable historical DTOs."""
        state = self.admitted.admission.trace_state
        lane_module._validate_admitted(self.admitted, "boot-a")
        with self.assertRaisesRegex(AdmittedRenderLaneError, "boot"):
            lane_module._validate_admitted(self.admitted, "boot-b")
        for phase in ("RUNNING", "COMPLETED"):
            admission = dataclasses.replace(self.admitted.admission,
                                            trace_state=dataclasses.replace(state, phase=phase))
            with self.assertRaisesRegex(AdmittedRenderLaneError, "ADMITTED"):
                lane_module._validate_admitted(dataclasses.replace(self.admitted, admission=admission), "boot-a")
        admission = dataclasses.replace(self.admitted.admission, terminal_manifest={"TEST": True})
        with self.assertRaisesRegex(AdmittedRenderLaneError, "terminal"):
            lane_module._validate_admitted(dataclasses.replace(self.admitted, admission=admission), "boot-a")

    def test_unadmitted_attempt_never_reaches_worker(self) -> None:
        """A manually created directory cannot substitute for admission."""
        manual = "44444444-4444-4444-8444-444444444444"
        (self.authority / "attempts" / manual).mkdir(mode=0o700)
        with controller_ownership(str(self.authority)) as lease:
            lane = self._lane(lease)
            with mock.patch.object(lane, "_invoke_worker") as worker, self.assertRaises(AdmissionError):
                lane.launch(AdmittedRenderRef(str(self.authority), manual))
        worker.assert_not_called()

    def test_expired_lease_refuses_before_artifact_read(self) -> None:
        """An expired controller cannot dispatch even with an existing ledger."""
        with controller_ownership(str(self.authority)) as lease:
            lane = self._lane(lease)
        with mock.patch.object(lane_module, "load_admitted_render") as load, \
                self.assertRaisesRegex(RuntimeError, "expired"):
            lane.launch(self.reference)
        load.assert_not_called()

    def test_attempt_path_replacement_refuses_identity(self) -> None:
        """Keep inode-bound handoff rejection independent of retired rendering."""
        from headless.durable_files import open_private_dir
        root = Path(self.admitted.attempt_root)
        fd = open_private_dir(str(root))
        self.addCleanup(os.close, fd)
        root.rename(root.with_name("displaced-attempt"))
        root.mkdir(mode=0o700)
        with self.assertRaisesRegex(RuntimeError, "identity changed"):
            lane_module.validate_attempt_binding(str(self.authority), self.admitted.admission.record, fd)

    def test_synthetic_batches_preserve_exactly_once_and_result_order(self) -> None:
        """Scheduling success stays covered without any source or render admission."""
        lane = self._lane(mock.Mock())
        items = tuple(SimpleNamespace(name=name, artifact=SimpleNamespace(
            resolved=SimpleNamespace(key=name))) for name in ("first", "second", "third"))
        simultaneous = threading.Barrier(2)
        started = []

        def completed(item: object, _context: object) -> dict:
            started.append(item.name)
            if item.name != "third":
                simultaneous.wait(timeout=2)
            return {"selectionId": item.name}

        with mock.patch.object(lane, "_launch_one", side_effect=completed) as worker:
            results = lane._render_overlays(items, mock.Mock())
        self.assertEqual(worker.call_count, 3)
        self.assertCountEqual(started, ["first", "second", "third"])
        self.assertEqual([row["selectionId"] for row in results], ["first", "second", "third"])

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
