"""Durable receipt units at an inert completed-lane boundary, plus real refusal."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

from _common import pl  # noqa: F401
from _admitted_graphic_receipt_fixture import (
    OUTER_REQUEST_DIGEST,
    QUALITY_POLICY_ID,
    AdmittedGraphicReceiptFixture,
    _request,
)
from headless import admitted_graphic_receipt_controller as controller_module
from headless.render_admission_artifact import (RenderArtifactRequest, store_render_admission_artifact)
from headless.render_admission import load_admitted_render
from headless import admitted_graphic_receipt_projection as projection_module
from headless import graphic_render_receipt_store_io as store_io
from headless.admitted_graphic_receipt_controller import (
    AdmittedGraphicRenderReceiptController,
    GraphicRenderReceiptControllerAuthorityV1,
)
from headless.admitted_graphic_receipt_types import (
    AdmittedGraphicRenderReceiptError,
)
from headless.graphic_render_receipt_store_types import (
    GraphicRenderReceiptStoreError,
)


class AdmittedGraphicReceiptControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = AdmittedGraphicReceiptFixture()
        self.addCleanup(self.fixture.close)

    def test_real_public_admission_refuses_retired_source_before_writes(self) -> None:
        """No inert source seam is active at the actual public boundary."""
        target = self.fixture.root / "uncreated-authority"
        request = RenderArtifactRequest(
            str(target), "authority-mp4-v1", _request(), self.fixture.runtime)
        with mock.patch("headless.render_admission_artifact.current_render_build_manifest") as build:
            with self.assertRaisesRegex(ValueError, "section-marker.*retired"):
                store_render_admission_artifact(request)
        build.assert_not_called()
        self.assertFalse(target.exists())

    def test_inert_retained_artifact_cannot_enter_current_admission(self) -> None:
        """Historical storage fixtures remain ineligible for live rendering."""
        with mock.patch("headless.admitted_render_lane._run_worker") as run:
            with self.assertRaisesRegex(ValueError, "section-marker.*retired"):
                load_admitted_render(self.fixture.reference)
        run.assert_not_called()

    def _retained(self, name: str) -> Path:
        return (
            Path(self.fixture.admitted.attempt_root)
            / "work"
            / store_io.STORE_NAME
            / store_io.FINAL_NAME
            / name
        )

    def test_completed_result_persists_loads_and_replays_exact_receipt(
        self,
    ) -> None:
        writer = projection_module.build_graphic_render_receipt_v1
        with self.fixture.controller() as (
            controller,
            lane,
            completed,
        ), mock.patch.object(
            projection_module,
            "build_graphic_render_receipt_v1",
            wraps=writer,
        ) as receipt_writer:
            created = controller.launch(self.fixture.reference)
            with mock.patch.object(
                lane,
                "_launch_locked",
                side_effect=AssertionError("replay rerendered"),
            ):
                replayed = controller.launch(self.fixture.reference)
            loaded = controller.load(self.fixture.reference, created.locator)
        completed.assert_called_once()
        receipt_writer.assert_called_once()
        self.assertFalse(created.replayed)
        self.assertTrue(replayed.replayed)
        self.assertTrue(loaded.replayed)
        self.assertEqual(created.receipts, replayed.receipts)
        receipt = created.receipts[0]
        self.assertEqual(receipt.request_digest, OUTER_REQUEST_DIGEST)
        self.assertEqual(receipt.quality_policy_id, QUALITY_POLICY_ID)
        self.assertNotEqual(
            receipt.request_digest,
            self.fixture.admitted.artifact.request_document_digest,
        )
        self.assertEqual(
            receipt.media.artifact.relative_path, "graphics/g-00000001.mov"
        )
        self.assertTrue(created.receipt_bytes_retained)
        self.assertTrue(created.source_records_bound)
        self.assertTrue(created.media_bytes_reobserved)
        self.assertFalse(receipt.claims.media_bytes_reobserved)
        self.assertFalse(created.execution_attested)
        self.assertFalse(created.execution_authorized)
        self.assertFalse(created.publication_authorized)

    def test_response_loss_after_atomic_publish_replays_without_completed(
        self,
    ) -> None:
        with self.fixture.controller() as (controller, lane, completed):
            with mock.patch.object(
                controller_module,
                "_outcome",
                side_effect=RuntimeError("response channel lost"),
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "response channel lost"
                ):
                    controller.launch(self.fixture.reference)
            with mock.patch.object(
                lane,
                "_launch_locked",
                side_effect=AssertionError("response replay rerendered"),
            ):
                recovered = controller.launch(self.fixture.reference)
        completed.assert_called_once()
        self.assertTrue(recovered.replayed)

    def test_pre_publish_crash_stays_running_and_never_rerenders(self) -> None:
        original = store_io._write_one
        calls = 0

        def crash(directory_fd: int, name: str, raw: bytes) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("receipt persistence interrupted")
            original(directory_fd, name, raw)

        with self.fixture.controller() as (controller, _lane, completed):
            with mock.patch.object(store_io, "_write_one", side_effect=crash):
                with self.assertRaisesRegex(
                    GraphicRenderReceiptStoreError, "cannot persist"
                ):
                    controller.launch(self.fixture.reference)
            with self.assertRaisesRegex(
                GraphicRenderReceiptStoreError, "reconciliation"
            ):
                controller.launch(self.fixture.reference)
        completed.assert_called_once()
        self.assertFalse(self._retained("manifest.json").exists())

    def test_malformed_retained_bytes_block_replay_before_lane(self) -> None:
        with self.fixture.controller() as (controller, lane, completed):
            controller.launch(self.fixture.reference)
            receipt = self._retained("receipt-0000.json")
            receipt.write_bytes(b"{malformed")
            os.chmod(receipt, 0o600)
            with mock.patch.object(lane, "_launch_locked") as launch:
                with self.assertRaises(RuntimeError):
                    controller.launch(self.fixture.reference)
                launch.assert_not_called()
        completed.assert_called_once()

    def test_output_mutation_after_lane_blocks_receipt_persistence(
        self,
    ) -> None:
        reobserve = controller_module.reobserve_lane_results

        def mutate(admitted: object, runtime: object, results: tuple) -> None:
            path = Path(results[0]["result"]["path"])
            path.write_bytes(b"mutated-after-parent-validation")
            path.chmod(0o600)
            reobserve(admitted, runtime, results)

        with self.fixture.controller() as (
            controller,
            _lane,
            completed,
        ), mock.patch.object(
            controller_module,
            "reobserve_lane_results",
            side_effect=mutate,
        ), mock.patch.object(
            controller_module, "store_graphic_render_receipt_set"
        ) as store:
            with self.assertRaises(AdmittedGraphicRenderReceiptError):
                controller.launch(self.fixture.reference)
            store.assert_not_called()
        completed.assert_called_once()
        self.assertFalse(self._retained("manifest.json").exists())

    def test_output_mutation_after_store_blocks_successful_handoff(
        self,
    ) -> None:
        persist = controller_module.store_graphic_render_receipt_set

        def mutate(*args: object) -> object:
            stored = persist(*args)
            cache = (
                Path(self.fixture.admitted.attempt_root)
                / "work"
                / "graphics-cache"
            )
            output = next(
                path for path in cache.iterdir() if path.suffix == ".mov"
            )
            output.write_bytes(b"mutated-after-receipt-store")
            output.chmod(0o600)
            return stored

        with self.fixture.controller() as (
            controller,
            _lane,
            completed,
        ), mock.patch.object(
            controller_module,
            "store_graphic_render_receipt_set",
            side_effect=mutate,
        ):
            with self.assertRaises(AdmittedGraphicRenderReceiptError):
                controller.launch(self.fixture.reference)
        completed.assert_called_once()
        self.assertTrue(self._retained("manifest.json").is_file())

    def test_changed_outer_authority_cannot_reinterpret_retained_set(
        self,
    ) -> None:
        with self.fixture.controller() as (controller, lane, completed):
            controller.launch(self.fixture.reference)
            confused = GraphicRenderReceiptControllerAuthorityV1(
                self.fixture.admitted.artifact.request_document_digest,
                "a" * 64,
            )
            alternate = AdmittedGraphicRenderReceiptController(lane, confused)
            with mock.patch.object(lane, "_launch_locked") as launch:
                with self.assertRaises(RuntimeError):
                    alternate.launch(self.fixture.reference)
                launch.assert_not_called()
        completed.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
