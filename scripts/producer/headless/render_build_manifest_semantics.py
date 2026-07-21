"""Closed semantic parser for retained render-build manifests."""

from __future__ import annotations

import hashlib
import json
import math
import posixpath
import re
import stat
import unicodedata
from dataclasses import dataclass

from .render_build_manifest_v1_contract import (
    RENDER_BUILD_V1_DIGEST_DOMAIN,
    RENDER_BUILD_V1_IMPLEMENTATION_PATHS,
    RENDER_BUILD_V1_POLICY,
)
from .wire_identity import same_wire_value

_DIGEST = re.compile(r"[0-9a-f]{64}")
_IMAGE = re.compile(r"sha256:[0-9a-f]{64}")
_USER = re.compile(r"[1-9][0-9]*:[1-9][0-9]*")
_TOP_KEYS = frozenset(
    "dockerSocket imageId implementation pipelineRoot policy pythonFlags "
    "runtimeRoot schemaVersion timeoutSeconds tools userId".split()
)
_SOURCE_KEYS = frozenset("path sha256 sizeBytes".split())
_TOOL_KEYS = frozenset("label path sha256 sizeBytes".split())
_SOCKET_KEYS = frozenset("device inode mode ownerUid path".split())
_TOOL_LABELS = ("docker", "proof-ffmpeg", "proof-ffprobe", "python")
_PYTHON_FLAGS = ("-I", "-S", "-B", "-X", "pycache_prefix=<attempt>")


class RenderBuildManifestSchemaError(RuntimeError):
    """A retained render-build manifest is not the current closed wire type."""


class _DuplicateKey(ValueError):
    pass


@dataclass(frozen=True)
class RenderBuildSourceRowV1:
    """One declared implementation source identity."""

    path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class RenderBuildToolRowV1:
    """One declared host executable identity."""

    label: str
    path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class RenderBuildManifestV1:
    """Exact static render source/tool manifest retained by the live lane."""

    image_id: str
    user_id: str
    pipeline_root: str
    runtime_root: str
    timeout_seconds: int | float
    implementation: tuple[RenderBuildSourceRowV1, ...]
    tools: tuple[RenderBuildToolRowV1, ...]
    docker_socket: str
    document_json: bytes
    build_digest: str


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    document = {}
    for key, value in pairs:
        if key in document:
            raise _DuplicateKey(key)
        document[key] = value
    return document


def _canonical(value: object) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise RenderBuildManifestSchemaError(
            "render build manifest cannot be canonicalized"
        ) from exc
    return text.encode("ascii")


def _document(raw: object) -> dict:
    if type(raw) is not bytes:
        raise RenderBuildManifestSchemaError(
            "render build manifest must be bytes"
        )
    try:
        document = json.loads(
            raw, object_pairs_hook=_pairs, parse_constant=_constant
        )
    except _DuplicateKey as exc:
        raise RenderBuildManifestSchemaError(
            "render build manifest has duplicate keys"
        ) from exc
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RenderBuildManifestSchemaError(
            "render build manifest is invalid JSON"
        ) from exc
    if type(document) is not dict or _canonical(document) != raw:
        raise RenderBuildManifestSchemaError(
            "render build manifest is not exact canonical JSON"
        )
    return document


def _constant(value: str) -> None:
    raise ValueError(f"non-finite JSON value: {value}")


def _digest(value: object, label: str) -> str:
    if type(value) is not str or not _DIGEST.fullmatch(value):
        raise RenderBuildManifestSchemaError(
            f"{label} is not lowercase SHA-256"
        )
    return value


def _canonical_absolute(value: object, label: str) -> str:
    valid = type(value) is str and value.startswith("/")
    valid = valid and not value.startswith("//") and "\\" not in value
    valid = valid and posixpath.normpath(value) == value
    valid = valid and unicodedata.normalize("NFC", value) == value
    valid = valid and not any(
        unicodedata.category(char) == "Cc" for char in value
    )
    try:
        encoded = value.encode("utf-8") if valid else b""
    except UnicodeEncodeError:
        encoded = b""
    parts = (() if value == "/" else value.split("/")[1:]) if encoded else ()
    valid = valid and 0 < len(encoded) <= 4096
    valid = valid and all(
        0 < len(part.encode("utf-8")) <= 255 for part in parts
    )
    if not valid:
        raise RenderBuildManifestSchemaError(f"{label} path is not canonical")
    return value


def _positive_size(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise RenderBuildManifestSchemaError(f"{label} size is invalid")
    return value


def _source_rows(value: object) -> tuple[RenderBuildSourceRowV1, ...]:
    if type(value) is not list:
        raise RenderBuildManifestSchemaError(
            "render implementation is not an array"
        )
    rows = []
    for item in value:
        if type(item) is not dict or set(item) != _SOURCE_KEYS:
            raise RenderBuildManifestSchemaError(
                "render source row keys are invalid"
            )
        rows.append(
            RenderBuildSourceRowV1(
                item["path"],
                _digest(item["sha256"], "render source digest"),
                _positive_size(item["sizeBytes"], "render source"),
            )
        )
    expected = RENDER_BUILD_V1_IMPLEMENTATION_PATHS
    if tuple(row.path for row in rows) != expected:
        raise RenderBuildManifestSchemaError(
            "render source order or closed path set is invalid"
        )
    return tuple(rows)


def _tool_rows(value: object) -> tuple[RenderBuildToolRowV1, ...]:
    if type(value) is not list:
        raise RenderBuildManifestSchemaError("render tools are not an array")
    rows = []
    for item in value:
        if type(item) is not dict or set(item) != _TOOL_KEYS:
            raise RenderBuildManifestSchemaError(
                "render tool row keys are invalid"
            )
        rows.append(
            RenderBuildToolRowV1(
                item["label"],
                _canonical_absolute(item["path"], "render tool"),
                _digest(item["sha256"], "render tool digest"),
                _positive_size(item["sizeBytes"], "render tool"),
            )
        )
    paths = tuple(row.path for row in rows)
    valid = tuple(row.label for row in rows) == _TOOL_LABELS
    valid = valid and len({path.casefold() for path in paths}) == len(paths)
    valid = valid and len({row.sha256 for row in rows}) == len(rows)
    if not valid:
        raise RenderBuildManifestSchemaError(
            "render tool roles alias or reorder"
        )
    return tuple(rows)


def _socket(value: object) -> str:
    if type(value) is not dict or set(value) != _SOCKET_KEYS:
        raise RenderBuildManifestSchemaError(
            "render Docker socket row is invalid"
        )
    path = _canonical_absolute(value["path"], "render Docker socket")
    integers = tuple(value[key] for key in ("device", "inode", "ownerUid"))
    valid = all(type(item) is int and item >= 0 for item in integers)
    valid = valid and type(value["mode"]) is int
    valid = valid and value["mode"] == stat.S_IFSOCK
    if not valid:
        raise RenderBuildManifestSchemaError(
            "render Docker socket facts are invalid"
        )
    return path


def _envelope(document: dict) -> tuple[str, str, str, str, int | float]:
    timeout = document.get("timeoutSeconds")
    valid = set(document) == _TOP_KEYS
    valid = valid and type(document.get("schemaVersion")) is int
    valid = valid and document.get("schemaVersion") == 1
    valid = valid and document.get("policy") == RENDER_BUILD_V1_POLICY
    valid = valid and type(timeout) in {int, float} and math.isfinite(timeout)
    valid = valid and 0 < timeout <= 3600
    valid = (
        valid and _IMAGE.fullmatch(str(document.get("imageId"))) is not None
    )
    valid = valid and _USER.fullmatch(str(document.get("userId"))) is not None
    valid = valid and document.get("pythonFlags") == list(_PYTHON_FLAGS)
    if not valid:
        raise RenderBuildManifestSchemaError(
            "render build envelope is invalid"
        )
    pipeline = _canonical_absolute(
        document["pipelineRoot"], "render pipeline root"
    )
    runtime = _canonical_absolute(
        document["runtimeRoot"], "render runtime root"
    )
    return document["imageId"], document["userId"], pipeline, runtime, timeout


def parse_render_build_manifest_v1(raw: object) -> RenderBuildManifestV1:
    """Parse exact source/tool bytes and recompute their digest."""
    document = _document(raw)
    image, user, pipeline, runtime, timeout = _envelope(document)
    sources = _source_rows(document["implementation"])
    tools = _tool_rows(document["tools"])
    socket = _socket(document["dockerSocket"])
    if socket.casefold() in {row.path.casefold() for row in tools}:
        raise RenderBuildManifestSchemaError(
            "render socket and tool paths alias"
        )
    digest = hashlib.sha256(RENDER_BUILD_V1_DIGEST_DOMAIN + raw).hexdigest()
    return RenderBuildManifestV1(
        image,
        user,
        pipeline,
        runtime,
        timeout,
        sources,
        tools,
        socket,
        raw,
        digest,
    )


def validate_render_build_manifest_v1(value: object) -> None:
    """Reject construction and equality that disagree with retained bytes."""
    valid = type(value) is RenderBuildManifestV1
    valid = valid and type(getattr(value, "document_json", None)) is bytes
    if not valid:
        raise RenderBuildManifestSchemaError(
            "render build manifest instance is invalid"
        )
    parsed = parse_render_build_manifest_v1(value.document_json)
    if not same_wire_value(value, parsed):
        raise RenderBuildManifestSchemaError("render manifest was forged")
