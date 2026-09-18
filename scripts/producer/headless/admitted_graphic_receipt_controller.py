"""Controller integration for admitted rendering and durable R0 receipts."""

from __future__ import annotations

import os

from .admitted_graphic_receipt_projection import (
    build_admitted_graphic_receipts,
    project_receipt_expectation,
)
from .admitted_graphic_receipt_types import (
    AdmittedGraphicRenderReceiptError,
    GraphicRenderReceiptControllerAuthorityV1,
    validate_controller_authority,
)
from .admitted_render_lane import AdmittedRenderLane
from .attempt_initialization import validate_attempt_binding
from .controller_ownership import assert_controller_ownership
from .durability_controller import resolve_attempt
from .durable_files import locked_private_dir
from .graphic_render_media_reobservation import (
    reobserve_lane_results,
    reobserve_retained_receipts,
)
from .graphic_render_receipt_store import (
    load_graphic_render_receipt_set,
    store_graphic_render_receipt_set,
    try_load_graphic_render_receipt_set,
)
from .graphic_render_receipt_store_types import (
    GRAPHIC_RECEIPT_SET_STATUS,
    AdmittedGraphicRenderReceiptOutcomeV1,
    GraphicRenderReceiptSetExpectationV1,
    GraphicRenderReceiptSetLocatorV1,
    StoredGraphicRenderReceiptSetV1,
)
from .render_admission import (
    AdmittedRenderRef,
    ResolvedAdmittedRender,
    load_admitted_render,
)

_RENDER_LOCK = ".admitted-render.lock"


def _outcome(
    stored: StoredGraphicRenderReceiptSetV1,
) -> AdmittedGraphicRenderReceiptOutcomeV1:
    return AdmittedGraphicRenderReceiptOutcomeV1(
        GRAPHIC_RECEIPT_SET_STATUS,
        stored.locator,
        stored.receipts,
        stored.replayed,
        True,
        True,
        True,
        True,
        True,
        False,
        False,
        False,
    )


class AdmittedGraphicRenderReceiptController:
    """Render admitted graphics and retain evidence without granting authority."""

    def __init__(self, lane: object, authority: object) -> None:
        if type(lane) is not AdmittedRenderLane:
            raise AdmittedGraphicRenderReceiptError(
                "graphic receipt lane is invalid"
            )
        self.lane = lane
        self.authority = validate_controller_authority(authority)

    def _attempt(
        self, reference: object
    ) -> tuple[AdmittedRenderRef, dict, str]:
        if type(reference) is not AdmittedRenderRef:
            raise AdmittedGraphicRenderReceiptError(
                "admitted graphic reference is invalid"
            )
        assert_controller_ownership(self.lane.lease, reference.authority_root)
        admission = resolve_attempt(
            reference.authority_root, reference.attempt_id
        )
        attempt_root = os.path.join(
            reference.authority_root, "attempts", admission.record["attemptId"]
        )
        return reference, admission.record, attempt_root

    def _expectation(
        self, reference: AdmittedRenderRef
    ) -> tuple[ResolvedAdmittedRender, GraphicRenderReceiptSetExpectationV1]:
        admitted = load_admitted_render(reference)
        expectation = project_receipt_expectation(
            admitted, self.authority, self.lane.runtime
        )
        return admitted, expectation

    def _launch_locked(
        self, reference: AdmittedRenderRef, record: dict, attempt_fd: int
    ) -> AdmittedGraphicRenderReceiptOutcomeV1:
        admitted, expected = self._expectation(reference)
        stored = try_load_graphic_render_receipt_set(
            admitted.attempt_root, expected
        )
        if stored is not None:
            reobserve_retained_receipts(
                admitted, self.lane.runtime, stored.receipts
            )
            return _outcome(stored)
        results = self.lane._launch_locked(reference, attempt_fd)
        refreshed, current = self._expectation(reference)
        if current != expected:
            raise AdmittedGraphicRenderReceiptError(
                "graphic receipt authority changed during render"
            )
        reobserve_lane_results(refreshed, self.lane.runtime, results)
        receipts = build_admitted_graphic_receipts(refreshed, current, results)
        stored = store_graphic_render_receipt_set(
            refreshed.attempt_root, current, receipts
        )
        reobserve_retained_receipts(
            refreshed, self.lane.runtime, stored.receipts
        )
        validate_attempt_binding(reference.authority_root, record, attempt_fd)
        assert_controller_ownership(self.lane.lease, reference.authority_root)
        return _outcome(stored)

    def launch(
        self, reference: object
    ) -> AdmittedGraphicRenderReceiptOutcomeV1:
        """Render once, atomically retain all receipts, and replay exact bytes."""
        checked, record, attempt_root = self._attempt(reference)
        with locked_private_dir(attempt_root, _RENDER_LOCK) as attempt_fd:
            validate_attempt_binding(
                checked.authority_root, record, attempt_fd
            )
            result = self._launch_locked(checked, record, attempt_fd)
            validate_attempt_binding(
                checked.authority_root, record, attempt_fd
            )
        return result

    def load(
        self, reference: object, locator: GraphicRenderReceiptSetLocatorV1
    ) -> AdmittedGraphicRenderReceiptOutcomeV1:
        """Reopen retained evidence under the same controller and attempt lock."""
        checked, record, attempt_root = self._attempt(reference)
        with locked_private_dir(attempt_root, _RENDER_LOCK) as attempt_fd:
            validate_attempt_binding(
                checked.authority_root, record, attempt_fd
            )
            admitted, expected = self._expectation(checked)
            stored = load_graphic_render_receipt_set(
                admitted.attempt_root, expected, locator
            )
            reobserve_retained_receipts(
                admitted, self.lane.runtime, stored.receipts
            )
            assert_controller_ownership(
                self.lane.lease, checked.authority_root
            )
            validate_attempt_binding(
                checked.authority_root, record, attempt_fd
            )
        return _outcome(stored)


__all__ = (
    "AdmittedGraphicRenderReceiptController",
    "AdmittedGraphicRenderReceiptError",
    "GraphicRenderReceiptControllerAuthorityV1",
)
