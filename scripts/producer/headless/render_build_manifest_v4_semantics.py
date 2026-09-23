"""Pure closed render V4 parser using immutable historical field primitives."""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from .wire_identity import same_wire_value

import headless.render_build_manifest_semantics as common
from .render_build_manifest_v2_semantics import RenderBuildManifestV2
from .render_build_manifest_v3_contract import RENDER_BUILD_V3_IMPLEMENTATION_PATHS

RENDER_BUILD_V4_POLICY = "sniper-headless-render-build-v5"
RENDER_BUILD_V4_DIGEST_DOMAIN = b"sniper-render-build-v5\0"
RENDER_BUILD_V4_IMPLEMENTATION_PATHS = (
    *RENDER_BUILD_V3_IMPLEMENTATION_PATHS,
    "scripts/producer/graphics/scene_contract.py",
    "scripts/producer/graphics/visual_source_policy.py",
    "scripts/producer/graphics/visual_source_receipt.py",
    "schemas/producer/visual-source-policy-v1.json",
    "scripts/producer/headless/render_build_manifest_v4_semantics.py",
    "scripts/producer/headless/render_build_receipt_v4_semantics.py",
)

RenderBuildManifestSchemaError = common.RenderBuildManifestSchemaError


@dataclass(frozen=True)
class RenderBuildManifestV4(RenderBuildManifestV2):
    """Distinct exact wire type sharing the existing immutable metadata shape."""


def _envelope(document: dict) -> tuple[str, str, str, str, int | float]:
    """Validate V4 metadata without relabeling it as a historical document."""
    timeout = document.get("timeoutSeconds")
    valid = set(document) == common._TOP_KEYS
    valid = valid and type(document.get("schemaVersion")) is int
    valid = valid and document.get("schemaVersion") == 4
    valid = valid and document.get("policy") == RENDER_BUILD_V4_POLICY
    valid = valid and type(timeout) in {int, float} and math.isfinite(timeout)
    valid = valid and 0 < timeout <= 3600
    valid = valid and type(document.get("imageId")) is str
    valid = valid and common._IMAGE.fullmatch(document["imageId"]) is not None
    valid = valid and type(document.get("userId")) is str
    valid = valid and common._USER.fullmatch(document["userId"]) is not None
    valid = valid and document.get("pythonFlags") == list(common._PYTHON_FLAGS)
    if not valid:
        raise RenderBuildManifestSchemaError("render V4 build envelope is invalid")
    pipeline = common._canonical_absolute(document["pipelineRoot"], "pipeline")
    runtime = common._canonical_absolute(document["runtimeRoot"], "runtime")
    return document["imageId"], document["userId"], pipeline, runtime, timeout


def _source_rows(value: object) -> tuple[common.RenderBuildSourceRowV1, ...]:
    """Require every V4 path and exact row shape at its declared position."""
    expected = RENDER_BUILD_V4_IMPLEMENTATION_PATHS
    if type(value) is not list or len(value) != len(expected):
        raise RenderBuildManifestSchemaError("render V4 source count is invalid")
    rows = []
    for item, path in zip(value, expected):
        if type(item) is not dict or set(item) != common._SOURCE_KEYS:
            raise RenderBuildManifestSchemaError("render V4 source keys are invalid")
        if type(item["path"]) is not str or item["path"] != path:
            raise RenderBuildManifestSchemaError("render V4 closed path order is invalid")
        rows.append(common.RenderBuildSourceRowV1(
            path, common._digest(item["sha256"], "source digest"),
            common._positive_size(item["sizeBytes"], "source")))
    return tuple(rows)


def parse_render_build_manifest_v4(raw: object) -> RenderBuildManifestV4:
    """Reject unbounded/mixed wire input and recompute V4's own domain."""
    if type(raw) is not bytes or not 0 < len(raw) <= 2 * 1024 * 1024:
        raise RenderBuildManifestSchemaError("render V4 manifest bytes are invalid")
    document = common._document(raw)
    image, user, pipeline, runtime, timeout = _envelope(document)
    sources = _source_rows(document["implementation"])
    tools = common._tool_rows(document["tools"])
    socket = common._socket(document["dockerSocket"])
    if socket.casefold() in {row.path.casefold() for row in tools}:
        raise RenderBuildManifestSchemaError("render socket and tool paths alias")
    digest = hashlib.sha256(RENDER_BUILD_V4_DIGEST_DOMAIN + raw).hexdigest()
    return RenderBuildManifestV4(image, user, pipeline, runtime, timeout, sources, tools, socket, raw, digest)


def validate_render_build_manifest_v4(value: object) -> None:
    """Reject forged instances without accepting historical wire classes."""
    if type(value) is not RenderBuildManifestV4:
        raise RenderBuildManifestSchemaError("render V4 manifest instance is invalid")
    parsed = parse_render_build_manifest_v4(value.document_json)
    if not same_wire_value(value, parsed):
        raise RenderBuildManifestSchemaError("render V4 manifest was forged")
