"""Disk-backed fixture for source and tool build-closure checks."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

from _build_receipt_semantics_fixture import build_receipt_fixture
from headless.build_closure_reobservation import (
    BuildClosureReobservationRequestV1,
)
from headless.compositor_build_manifest_v1_contract import (
    COMPOSITOR_BUILD_V1_IMPLEMENTATION_PATHS,
)
from headless.render_build_manifest_v1_contract import (
    RENDER_BUILD_V1_IMPLEMENTATION_PATHS,
)


@dataclass(frozen=True)
class BuildClosureFixture:
    """One self-consistent build binding and its exact local byte paths."""

    request: BuildClosureReobservationRequestV1
    sources: tuple[str, ...]
    tools: tuple[str, ...]


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write(path: str, raw: bytes, mode: int = 0o600) -> None:
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(raw)
    os.chmod(path, mode)


def _sources(root: str) -> tuple[str, ...]:
    paths = []
    groups = (
        COMPOSITOR_BUILD_V1_IMPLEMENTATION_PATHS,
        RENDER_BUILD_V1_IMPLEMENTATION_PATHS,
    )
    for relatives in groups:
        for relative in relatives:
            path = os.path.join(root, relative)
            _write(path, f"source:{relative}".encode("ascii"))
            paths.append(path)
    return tuple(paths)


def _tools(root: str) -> tuple[tuple[str, bytes, str], ...]:
    rows = []
    for label in ("docker", "proof-ffmpeg", "proof-ffprobe", "python"):
        raw = f"#!/bin/sh\n# synthetic {label}\nexit 0\n".encode("ascii")
        path = os.path.join(root, "tools", label)
        _write(path, raw, 0o700)
        rows.append((path, raw, _digest(raw)))
    return tuple(rows)


def build_closure_fixture(root: str) -> BuildClosureFixture:
    """Materialize manifest bytes and return a reobservation request."""
    source_paths = _sources(root)
    tool_rows = _tools(root)

    def mutate(manifest: dict) -> None:
        manifest["pipelineRoot"] = root
        for row, (path, raw, digest) in zip(manifest["tools"], tool_rows):
            row.update({"path": path, "sha256": digest, "sizeBytes": len(raw)})

    runtime_digests = (tool_rows[1][2], tool_rows[2][2])
    binding = build_receipt_fixture(
        render_mutator=mutate, runtime_tool_digests=runtime_digests
    )
    request = BuildClosureReobservationRequestV1(binding, root)
    return BuildClosureFixture(
        request, source_paths, tuple(row[0] for row in tool_rows)
    )
