#!/usr/bin/env python3
"""Shared strict predicates for retained baseline evidence."""
from __future__ import annotations

import hashlib
import json
import re

SHA256 = re.compile(r"^[0-9a-f]{64}$")
DIRECT_SCOPE = "direct-entrypoints-not-transitive-source-closure"


def document_sha256(value: dict) -> str:
    """Hash one parsed JSON object with the baseline canonicalization."""
    try:
        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return ""
    return hashlib.sha256(payload).hexdigest()


def valid_media_tool_record(value: object) -> bool:
    """Whether one decode-tool record includes identity and version."""
    if not isinstance(value, dict) or set(value) != {
            "path", "sha256", "version"}:
        return False
    return (
        isinstance(value["path"], str)
        and value["path"].startswith("/")
        and isinstance(value["version"], str)
        and bool(value["version"])
        and isinstance(value["sha256"], str)
        and SHA256.fullmatch(value["sha256"]) is not None
    )


def valid_media_tools(value: object) -> bool:
    """Whether ffmpeg and ffprobe decode identities are both closed."""
    return (
        isinstance(value, dict)
        and set(value) == {"ffmpeg", "ffprobe"}
        and all(valid_media_tool_record(value[name]) for name in value)
    )


def valid_direct_tool(value: object) -> bool:
    """Whether one direct binary/source entrypoint has a full hash."""
    return (
        isinstance(value, dict)
        and set(value) == {"path", "sha256"}
        and isinstance(value["path"], str)
        and value["path"].startswith("/")
        and isinstance(value["sha256"], str)
        and SHA256.fullmatch(value["sha256"]) is not None
    )


def valid_tool_authority(value: object) -> bool:
    """Whether a trace's direct (explicitly non-transitive) tool set is closed."""
    if not isinstance(value, dict) or set(value) != {
            "executable", "entrypoints", "externalTools", "scope"}:
        return False
    entries = value["entrypoints"]
    external = value["externalTools"]
    return (
        value["scope"] == DIRECT_SCOPE
        and valid_direct_tool(value["executable"])
        and isinstance(entries, list)
        and all(valid_direct_tool(item) for item in entries)
        and isinstance(external, list)
        and len(external) == 2
        and all(valid_direct_tool(item) for item in external)
    )
