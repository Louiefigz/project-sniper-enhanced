"""Pure closed V2 build parser, separate from historical V1 authority.

The row/path primitives are frozen V1 validators, reused without changing
their policy or parser. Parsing identities does not reobserve live bytes or
prove execution, archive approval, or graphic quality.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

import headless.render_build_manifest_semantics as common
from .render_build_manifest_v2_contract import (
    RENDER_BUILD_V2_DIGEST_DOMAIN,
    RENDER_BUILD_V2_IMPLEMENTATION_PATHS,
    RENDER_BUILD_V2_POLICY,
)
from .wire_identity import same_wire_value

RenderBuildManifestSchemaError = common.RenderBuildManifestSchemaError


@dataclass(frozen=True)
class RenderBuildManifestV2:
    """Exact V2 source/tool declarations, not independently observed facts."""

    image_id: str
    user_id: str
    pipeline_root: str
    runtime_root: str
    timeout_seconds: int | float
    implementation: tuple[common.RenderBuildSourceRowV1, ...]
    tools: tuple[common.RenderBuildToolRowV1, ...]
    docker_socket: str
    document_json: bytes
    build_digest: str


def _envelope(document: dict) -> tuple[str, str, str, str, int | float]:
    timeout = document.get("timeoutSeconds")
    valid = set(document) == common._TOP_KEYS
    valid = valid and type(document.get("schemaVersion")) is int
    valid = valid and document.get("schemaVersion") == 2
    valid = valid and document.get("policy") == RENDER_BUILD_V2_POLICY
    valid = valid and type(timeout) in {int, float} and math.isfinite(timeout)
    valid = valid and 0 < timeout <= 3600
    valid = valid and type(document.get("imageId")) is str
    valid = valid and common._IMAGE.fullmatch(document["imageId"]) is not None
    valid = valid and type(document.get("userId")) is str
    valid = valid and common._USER.fullmatch(document["userId"]) is not None
    valid = valid and document.get("pythonFlags") == list(common._PYTHON_FLAGS)
    if not valid:
        raise RenderBuildManifestSchemaError("render V2 build envelope is invalid")
    pipeline = common._canonical_absolute(document["pipelineRoot"], "pipeline")
    runtime = common._canonical_absolute(document["runtimeRoot"], "runtime")
    return document["imageId"], document["userId"], pipeline, runtime, timeout


def _source_rows(value: object) -> tuple[common.RenderBuildSourceRowV1, ...]:
    expected = RENDER_BUILD_V2_IMPLEMENTATION_PATHS
    if type(value) is not list or len(value) != len(expected):
        raise RenderBuildManifestSchemaError("render V2 source count is invalid")
    rows = []
    for item, path in zip(value, expected):
        if type(item) is not dict or set(item) != common._SOURCE_KEYS:
            raise RenderBuildManifestSchemaError("render V2 source keys are invalid")
        if type(item["path"]) is not str or item["path"] != path:
            raise RenderBuildManifestSchemaError("render V2 closed path order is invalid")
        rows.append(common.RenderBuildSourceRowV1(
            path, common._digest(item["sha256"], "source digest"),
            common._positive_size(item["sizeBytes"], "source"),
        ))
    return tuple(rows)


def parse_render_build_manifest_v2(raw: object) -> RenderBuildManifestV2:
    """Validate the exact current wire version and recompute its own domain."""
    if type(raw) is not bytes or not 0 < len(raw) <= 2 * 1024 * 1024:
        raise RenderBuildManifestSchemaError("render V2 manifest bytes are invalid")
    document = common._document(raw)
    image, user, pipeline, runtime, timeout = _envelope(document)
    sources = _source_rows(document["implementation"])
    tools = common._tool_rows(document["tools"])
    socket = common._socket(document["dockerSocket"])
    if socket.casefold() in {row.path.casefold() for row in tools}:
        raise RenderBuildManifestSchemaError("render socket and tool paths alias")
    digest = hashlib.sha256(RENDER_BUILD_V2_DIGEST_DOMAIN + raw).hexdigest()
    return RenderBuildManifestV2(
        image, user, pipeline, runtime, timeout, sources, tools, socket, raw, digest,
    )


def validate_render_build_manifest_v2(value: object) -> None:
    """Reject forged instances without invoking caller-defined equality."""
    if type(value) is not RenderBuildManifestV2:
        raise RenderBuildManifestSchemaError("render V2 manifest instance is invalid")
    parsed = parse_render_build_manifest_v2(value.document_json)
    if not same_wire_value(value, parsed):
        raise RenderBuildManifestSchemaError("render V2 manifest was forged")
