"""Project parent-validated admitted-lane results into R0 receipts."""

from __future__ import annotations

import re

from .admitted_graphic_receipt_types import (
    AdmittedGraphicRenderReceiptError,
    validate_controller_authority,
)
from .artifact_contract import (
    ArtifactContractError,
    ArtifactRefV1,
    MediaFactsV1,
    MediaRefV1,
    validate_media_ref,
)
from .graphic_render_receipt_semantics import GraphicRenderReceiptV1
from .graphic_render_receipt_store_types import (
    GraphicRenderReceiptExpectedV1,
    GraphicRenderReceiptSetExpectationV1,
)
from .graphic_render_receipt_writer import (
    GraphicRenderReceiptAuthorityV1,
    build_graphic_render_receipt_v1,
)
from .quality_pass_contract import graphic_render_intent_digest
from .render_admission import ResolvedAdmittedRender
from .render_runtime import RendererRuntime

_DIGEST = re.compile(r"[0-9a-f]{64}")
_TOOL_LABELS = ("docker", "proof-ffmpeg", "proof-ffprobe", "python")
_TOOL_KEYS = {"label", "path", "sha256", "sizeBytes"}
_ASSET_KEYS = {
    "codec",
    "durationS",
    "fps",
    "frameCount",
    "height",
    "pixelFormat",
    "profile",
    "sha256",
    "sizeBytes",
    "width",
}


def _exact(value: object, keys: set[str], label: str) -> dict:
    if type(value) is not dict or set(value) != keys:
        raise AdmittedGraphicRenderReceiptError(f"{label} is invalid")
    return value


def _tool_digests(manifest: object) -> tuple[str, str]:
    if type(manifest) is not dict or type(manifest.get("tools")) is not list:
        raise AdmittedGraphicRenderReceiptError(
            "render build tools are invalid"
        )
    rows = manifest["tools"]
    labels = tuple(
        row.get("label") if type(row) is dict else None for row in rows
    )
    if labels != _TOOL_LABELS:
        raise AdmittedGraphicRenderReceiptError(
            "render build tool order is invalid"
        )
    for row in rows:
        valid = type(row) is dict and set(row) == _TOOL_KEYS
        valid = valid and type(row["label"]) is str
        valid = valid and type(row["path"]) is str and bool(row["path"])
        valid = valid and type(row["sha256"]) is str
        valid = valid and bool(_DIGEST.fullmatch(row["sha256"]))
        valid = valid and type(row["sizeBytes"]) is int
        valid = valid and row["sizeBytes"] > 0
        if not valid:
            raise AdmittedGraphicRenderReceiptError(
                "render build tool is invalid"
            )
    ffmpeg, ffprobe = rows[1]["sha256"], rows[2]["sha256"]
    if ffmpeg == ffprobe:
        raise AdmittedGraphicRenderReceiptError(
            "render proof tool roles alias"
        )
    return ffmpeg, ffprobe


def _expected_rows(
    admitted: ResolvedAdmittedRender,
) -> tuple[GraphicRenderReceiptExpectedV1, ...]:
    rows = []
    for ordinal, overlay in enumerate(admitted.artifact.overlays):
        entry = overlay.entry
        if type(entry) is not dict or entry.get("id") != overlay.overlay_id:
            raise AdmittedGraphicRenderReceiptError(
                "admitted graphic identity differs from its plan row"
            )
        rows.append(
            GraphicRenderReceiptExpectedV1(
                ordinal,
                overlay.overlay_id,
                entry.get("kind"),
                graphic_render_intent_digest(entry),
                overlay.resolved.key,
                overlay.resolved.snapshot.sha256,
            )
        )
    return tuple(rows)


def project_receipt_expectation(
    admitted: object,
    authority: object,
    runtime: object,
) -> GraphicRenderReceiptSetExpectationV1:
    """Derive the entire receipt-set identity from retained controller facts."""
    checked = validate_controller_authority(authority)
    if (
        type(admitted) is not ResolvedAdmittedRender
        or type(runtime) is not RendererRuntime
    ):
        raise AdmittedGraphicRenderReceiptError(
            "admitted receipt context is invalid"
        )
    manifest = admitted.artifact.build_manifest
    image = manifest.get("imageId") if type(manifest) is dict else None
    if image != runtime.image_id:
        raise AdmittedGraphicRenderReceiptError(
            "render runtime image is stale"
        )
    ffmpeg, ffprobe = _tool_digests(manifest)
    record = admitted.admission.record
    return GraphicRenderReceiptSetExpectationV1(
        record["authorityId"],
        record["attemptId"],
        admitted.artifact.artifact_digest,
        checked.request_digest,
        checked.quality_policy_id,
        admitted.artifact.build_digest,
        runtime.image_id,
        ffmpeg,
        ffprobe,
        _expected_rows(admitted),
    )


def _lane_asset_and_output(lane: object) -> tuple[dict, dict]:
    outer = _exact(
        lane,
        {
            "artifactDigest",
            "cacheBinding",
            "launcherSha256",
            "outputBinding",
            "renderBuildReceipt",
            "rendererMode",
            "result",
            "selectionId",
        },
        "admitted render result",
    )
    result = outer["result"]
    if type(result) is not dict or type(result.get("proof")) is not dict:
        raise AdmittedGraphicRenderReceiptError("render proof is invalid")
    asset = _exact(
        result["proof"].get("asset"), _ASSET_KEYS, "render proof asset"
    )
    output = outer["outputBinding"]
    if type(output) is not dict:
        raise AdmittedGraphicRenderReceiptError(
            "render output binding is invalid"
        )
    return asset, output


def _media(row: GraphicRenderReceiptExpectedV1, lane: object) -> MediaRefV1:
    asset, output = _lane_asset_and_output(lane)
    media = MediaRefV1(
        ArtifactRefV1(
            f"graphics/{row.graphic_id}.mov",
            output.get("sha256"),
            output.get("sizeBytes"),
        ),
        MediaFactsV1(
            asset["width"],
            asset["height"],
            asset["durationS"],
            30,
            1,
            asset["frameCount"],
            asset["sizeBytes"],
            asset["codec"],
            asset["pixelFormat"],
            asset["profile"],
            "straight",
            None,
        ),
    )
    try:
        validate_media_ref(media)
    except ArtifactContractError as exc:
        raise AdmittedGraphicRenderReceiptError(
            "render media facts are invalid"
        ) from exc
    return media


def _writer_authority(
    expectation: GraphicRenderReceiptSetExpectationV1,
    row: GraphicRenderReceiptExpectedV1,
    media: MediaRefV1,
) -> GraphicRenderReceiptAuthorityV1:
    return GraphicRenderReceiptAuthorityV1(
        row.ordinal,
        row.graphic_id,
        row.graphic_id,
        expectation.admission_artifact_digest,
        expectation.request_digest,
        expectation.quality_policy_id,
        media,
        expectation.render_build_digest,
        row.render_input_key,
        row.source_snapshot_sha256,
        expectation.runtime_image_id,
        expectation.proof_ffmpeg_sha256,
        expectation.proof_ffprobe_sha256,
    )


def build_admitted_graphic_receipts(
    admitted: ResolvedAdmittedRender,
    expectation: GraphicRenderReceiptSetExpectationV1,
    lane_results: object,
) -> tuple[GraphicRenderReceiptV1, ...]:
    """Invoke the exact receipt writer once per ordered admitted lane result."""
    if type(lane_results) is not tuple:
        raise AdmittedGraphicRenderReceiptError("render result set is invalid")
    if len(lane_results) != len(expectation.receipts):
        raise AdmittedGraphicRenderReceiptError("render result count is stale")
    if len(admitted.artifact.overlays) != len(expectation.receipts):
        raise AdmittedGraphicRenderReceiptError(
            "admitted graphic count is stale"
        )
    receipts = []
    for overlay, row, lane in zip(
        admitted.artifact.overlays, expectation.receipts, lane_results
    ):
        authority = _writer_authority(expectation, row, _media(row, lane))
        receipts.append(
            build_graphic_render_receipt_v1(authority, overlay.entry, lane)
        )
    return tuple(receipts)
