"""Descriptor-safe cache-byte reobservation for graphic receipt handoff."""

from __future__ import annotations

import os

from .admitted_graphic_receipt_types import AdmittedGraphicRenderReceiptError
from .graphic_render_receipt_semantics import (
    GraphicRenderReceiptV1,
    validate_graphic_render_receipt_v1,
)
from .render_admission import ResolvedAdmittedRender
from .render_lane import _output_binding
from .render_lane_cache import CacheBinding, prepare_attempt_cache
from .render_runtime import RendererRuntime

_OUTPUT_KEYS = {"device", "inode", "sha256", "sizeBytes"}


def _cache(
    admitted: ResolvedAdmittedRender, runtime: RendererRuntime
) -> CacheBinding:
    identity = (
        admitted.admission.record["attemptId"],
        admitted.artifact.artifact_digest,
        admitted.artifact.build_digest,
        runtime.image_id,
    )
    try:
        return prepare_attempt_cache(admitted.attempt_root, identity)
    except (OSError, RuntimeError) as exc:
        raise AdmittedGraphicRenderReceiptError(
            "graphic media cache cannot be reopened"
        ) from exc


def _path(binding: CacheBinding, key: str) -> str:
    return os.path.join(binding.cache_dir, f"{key}.mov")


def _observe(path: str, binding: CacheBinding) -> dict:
    try:
        return _output_binding(path, binding)
    except (OSError, RuntimeError) as exc:
        raise AdmittedGraphicRenderReceiptError(
            "graphic media bytes cannot be reobserved"
        ) from exc


def _lane_identity(lane: object) -> tuple[dict, dict]:
    if type(lane) is not dict or type(lane.get("result")) is not dict:
        raise AdmittedGraphicRenderReceiptError("render result is invalid")
    output = lane.get("outputBinding")
    if type(output) is not dict or set(output) != _OUTPUT_KEYS:
        raise AdmittedGraphicRenderReceiptError(
            "render output binding is invalid"
        )
    return lane["result"], output


def reobserve_lane_results(
    admitted: ResolvedAdmittedRender,
    runtime: RendererRuntime,
    lane_results: object,
) -> None:
    """Re-hash each lane path and require its exact parent-validated binding."""
    overlays = admitted.artifact.overlays
    if type(lane_results) is not tuple or len(lane_results) != len(overlays):
        raise AdmittedGraphicRenderReceiptError("render result count is stale")
    binding = _cache(admitted, runtime)
    for overlay, lane in zip(overlays, lane_results):
        result, expected = _lane_identity(lane)
        path = _path(binding, overlay.resolved.key)
        identity = (
            lane.get("selectionId"),
            result.get("key"),
            result.get("path"),
        )
        wanted = (overlay.overlay_id, overlay.resolved.key, path)
        if identity != wanted or _observe(path, binding) != expected:
            raise AdmittedGraphicRenderReceiptError(
                "graphic media changed after lane validation"
            )


def reobserve_retained_receipts(
    admitted: ResolvedAdmittedRender,
    runtime: RendererRuntime,
    receipts: object,
) -> None:
    """Re-hash cache bytes against reparsed retained receipt identities."""
    overlays = admitted.artifact.overlays
    if type(receipts) is not tuple or len(receipts) != len(overlays):
        raise AdmittedGraphicRenderReceiptError(
            "graphic receipt count is stale"
        )
    binding = _cache(admitted, runtime)
    for overlay, receipt in zip(overlays, receipts):
        try:
            validate_graphic_render_receipt_v1(receipt)
        except RuntimeError as exc:
            raise AdmittedGraphicRenderReceiptError(
                "graphic receipt is invalid"
            ) from exc
        if type(receipt) is not GraphicRenderReceiptV1:  # pragma: no cover
            raise AdmittedGraphicRenderReceiptError(
                "graphic receipt is invalid"
            )
        observed = _observe(_path(binding, overlay.resolved.key), binding)
        actual = (observed["sha256"], observed["sizeBytes"])
        expected = (
            receipt.media.artifact.sha256,
            receipt.media.artifact.size_bytes,
        )
        identity = (receipt.graphic_id, receipt.render_input_key)
        if actual != expected or identity != (
            overlay.overlay_id,
            overlay.resolved.key,
        ):
            raise AdmittedGraphicRenderReceiptError(
                "retained graphic receipt no longer matches cache bytes"
            )
