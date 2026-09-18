"""Fake executable/runtime declaration fixture for descriptor reobservation."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from _assembly_receipt_fixture import canonical
from _runtime_capability_fixture import runtime_capability_fixture
from headless.runtime_capability_manifest import (
    parse_runtime_capability_manifest_v1,
)
from headless.runtime_executable_reobservation import (
    RuntimeExecutableReobservationRequestV1,
)

FFMPEG_BYTES = b"fixture-ffmpeg-executable-v1\n"
FFPROBE_BYTES = b"fixture-ffprobe-executable-v1\n"


@dataclass(frozen=True)
class RuntimeExecutableFixture:
    request: RuntimeExecutableReobservationRequestV1
    ffmpeg_path: str
    ffprobe_path: str


def write_executable(path: str, content: bytes) -> None:
    """Create one non-shared, owner-only fake executable."""
    Path(path).write_bytes(content)
    os.chmod(path, 0o700)


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def runtime_executable_fixture(root: str) -> RuntimeExecutableFixture:
    """Create two exact tool inodes and a parse-valid declaration for them."""
    tool_root = os.path.join(root, "tools")
    os.mkdir(tool_root, 0o700)
    ffmpeg = os.path.join(tool_root, "ffmpeg")
    ffprobe = os.path.join(tool_root, "ffprobe")
    write_executable(ffmpeg, FFMPEG_BYTES)
    write_executable(ffprobe, FFPROBE_BYTES)
    source = runtime_capability_fixture().binding.runtime_manifest
    document = json.loads(source.document_json)
    document["tools"]["ffmpeg"]["sha256"] = digest(FFMPEG_BYTES)
    document["tools"]["ffprobe"]["sha256"] = digest(FFPROBE_BYTES)
    manifest = parse_runtime_capability_manifest_v1(canonical(document))
    request = RuntimeExecutableReobservationRequestV1(
        manifest, ffmpeg, ffprobe
    )
    return RuntimeExecutableFixture(request, ffmpeg, ffprobe)
