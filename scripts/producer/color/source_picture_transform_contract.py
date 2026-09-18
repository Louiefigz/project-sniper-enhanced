"""Closed compiler inputs, not source admission or a transform execution API.

Paths/hashes below are independently held owner observations. Pure validation
does not open them or confer provenance; the owning source/parent/tool guard
must strongly revalidate them under its original deadline. No output path,
user filter, look adjustment, delivery approval or gamut waiver is accepted.
"""
from __future__ import annotations

import json
import re
from pathlib import PurePosixPath

from color.grade_contract import closed, integer, parse_source_binding
from color.grade_observation_profile import V2, observation_declaration
from cross_runtime_canonical_json import canonical_compact_json
from cut_preview_io import digest

TRANSFORM_POLICY = "xvycc709-display-to-bt709-v1"
_SHA = re.compile(r"[a-f0-9]{64}")
_INTENT = {"schemaVersion": 1, "kind": TRANSFORM_POLICY, "scope": "picture-only",
    "geometry": "native-geometry-and-clock", "gamutPolicy": "reject-out-of-gamut",
    "chromaResampling": "bilinear-same-siting", "quantization": "8bit-no-dither"}
_PARENTS = {"planSha256", "manifestSha256", "projectSha256"}


def bounded_json(value: object) -> str:
    """Bound trusted-context complexity before canonicalizing its exact values."""
    pending, nodes, text_size = [(value, 0)], 0, 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > 4096 or depth > 8:
            raise ValueError("picture transform context exceeds structural bounds")
        if type(item) in (dict, list) and len(item) > 4096:
            raise ValueError("picture transform context collection exceeds bound")
        if type(item) is dict:
            pending.extend((key, depth + 1) for key in item)
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
        elif type(item) is str:
            text_size += len(item)
        elif item is not None and type(item) not in (int, float, bool):
            raise ValueError("picture transform context is outside JSON types")
        if text_size > 128 * 1024 or len(pending) > 4096:
            raise ValueError("picture transform context exceeds byte/node bounds")
    result = canonical_compact_json(value)
    if len(result.encode("utf8")) > 128 * 1024:
        raise ValueError("picture transform context exceeds canonical byte bound")
    return result


def sha256(value: object) -> str:
    """Require exact lowercase byte or explicitly named semantic identities."""
    if type(value) is not str or _SHA.fullmatch(value) is None:
        raise ValueError("picture transform identity must be lowercase SHA-256")
    return value


def file_reference(value: object, maximum: int) -> dict:
    """No path discovery or IO: validate an exact owner-held observed reference."""
    row = closed(value, {"path", "sha256", "bytes"}, "picture transform file")
    path = row["path"]
    if type(path) is not str or not 1 <= len(path) <= 4096 or not path.startswith("/") \
            or "\\" in path or "//" in path or str(PurePosixPath(path)) != path \
            or ".." in path.split("/") or any(ord(char) < 32 or ord(char) == 127
                or 0xD800 <= ord(char) <= 0xDFFF for char in path):
        raise ValueError("picture transform file path must be exact absolute lexical form")
    sha256(row["sha256"])
    integer(row["bytes"], 1, maximum)
    return dict(row)


def parse_intent(value: object) -> dict:
    """Only one explicit fixed policy; Python bool/int equality is insufficient."""
    row = closed(value, set(_INTENT), "picture transform intent")
    if any(type(row[key]) is not type(expected) or row[key] != expected
           for key, expected in _INTENT.items()):
        raise ValueError("picture transform intent is unsupported")
    return dict(row)


def parse_authority(value: object) -> dict:
    """Cross-bind exact declaration/history/current parents; do not infer history."""
    row = closed(value, {"source", "binding", "declaration", "expectedParents", "projectHistory"},
                 "picture transform authority")
    bounded_json(row)
    source = file_reference(row["source"], 16 * 1024 ** 3)
    binding = parse_source_binding(row["binding"])
    declaration = row["declaration"]
    observation_declaration(declaration, binding, V2)
    if declaration["sourceProfile"] != "xvycc709" or declaration["historyState"] != "known":
        raise ValueError("picture transform requires explicit xvYCC and known declared history")
    parents = closed(row["expectedParents"], _PARENTS, "picture transform parents")
    for item in parents.values():
        sha256(item)
    history = closed(row["projectHistory"], {"projectSha256", "history"}, "picture transform history")
    if type(history["history"]) is not list or len(history["history"]) > 512 \
            or history["projectSha256"] != parents["projectSha256"] \
            or digest(history) != binding.project_history_sha256 \
            or source["sha256"] != binding.source_sha256:
        raise ValueError("picture transform source/history differs from exact bound parents")
    return json.loads(bounded_json(row))


def parse_tools(value: object) -> dict:
    """Pin the tested wrapper AND math library, never choose ambient executables."""
    row = closed(value, {"ffmpeg", "libavfilter", "libzimg", "ffmpegVersion", "zimgVersion"},
                 "picture transform tool closure")
    if row["ffmpegVersion"] != "8.0" or row["zimgVersion"] != "3.0.6":
        raise ValueError("picture transform tool versions are outside the tested class")
    refs = {key: file_reference(row[key], 512 * 1024 ** 2)
            for key in ("ffmpeg", "libavfilter", "libzimg")}
    if len({ref["path"] for ref in refs.values()}) != 3:
        raise ValueError("picture transform tool roles cannot alias one path")
    return {**refs, "ffmpegVersion": "8.0", "zimgVersion": "3.0.6"}
