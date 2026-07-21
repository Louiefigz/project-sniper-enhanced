"""Admitted source/tool context for private prebound composition."""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from typing import Callable

from .compositor_build_manifest_v1_contract import (
    COMPOSITOR_BUILD_V1_DIGEST_DOMAIN,
    COMPOSITOR_BUILD_V1_IMPLEMENTATION_PATHS,
    COMPOSITOR_BUILD_V1_POLICY,
)
from .quality_pass_contract import ArtifactRefV1
from .safe_source_files import PinnedSourceRoot

BUILD_POLICY = COMPOSITOR_BUILD_V1_POLICY
_DIGEST_DOMAIN = COMPOSITOR_BUILD_V1_DIGEST_DOMAIN
_IMPLEMENTATION_FILES = COMPOSITOR_BUILD_V1_IMPLEMENTATION_PATHS


class PreboundCompositorBuildError(RuntimeError):
    """The compositor context does not bind the current source closure."""


@dataclass(frozen=True)
class PreboundCompositorContextV1:
    """Attempt-private storage, exact tools, and artifact resolver."""

    candidate_root: str
    resolve_artifact: Callable[[ArtifactRefV1], str]
    ffmpeg_path: str
    ffprobe_path: str
    expected_build_digest: str
    timeout_seconds: float = 180.0


def _implementation_rows(root: str) -> list[dict]:
    rows = []
    with PinnedSourceRoot(root) as source:
        for relative in _IMPLEMENTATION_FILES:
            raw = source.read(relative)
            if not raw:
                raise PreboundCompositorBuildError(
                    f"compositor source must be nonempty: {relative}"
                )
            rows.append(
                {
                    "path": relative,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "sizeBytes": len(raw),
                }
            )
        source.assert_current()
    return rows


def compositor_build_manifest() -> dict:
    """Capture frozen V1 source rows from the loaded release root."""
    rows = _implementation_rows(_LOADED_ROOT)
    if rows != list(_LOADED_IMPLEMENTATION) or rows != _implementation_rows(
        _LOADED_ROOT
    ):
        raise PreboundCompositorBuildError(
            "compositor source closure changed while hashing"
        )
    return {
        "schemaVersion": 1,
        "policy": BUILD_POLICY,
        "implementation": rows,
    }


def compositor_build_manifest_digest(manifest: dict) -> str:
    """Reproduce the legacy build digest from closed manifest source rows."""
    rows = manifest.get("implementation") if type(manifest) is dict else None
    if type(rows) is not list:
        raise PreboundCompositorBuildError(
            "compositor build manifest is invalid"
        )
    digest = hashlib.sha256(_DIGEST_DOMAIN)
    for row in rows:
        valid = type(row) is dict and set(row) == {
            "path",
            "sha256",
            "sizeBytes",
        }
        valid = valid and type(row.get("path")) is str
        valid = valid and type(row.get("sha256")) is str
        try:
            source_digest = bytes.fromhex(row["sha256"]) if valid else b""
        except ValueError as exc:
            raise PreboundCompositorBuildError(
                "compositor source digest is invalid"
            ) from exc
        if not valid or len(source_digest) != 32:
            raise PreboundCompositorBuildError(
                "compositor source manifest row is invalid"
            )
        digest.update(os.path.basename(row["path"]).encode("utf-8") + b"\0")
        digest.update(source_digest)
    return digest.hexdigest()


def compositor_build_receipt_bytes() -> bytes:
    """Return the canonical retained compositor build receipt V1 wire bytes."""
    manifest = compositor_build_manifest()
    document = {
        "schemaVersion": 1,
        "buildDigest": compositor_build_manifest_digest(manifest),
        "manifest": manifest,
    }
    return (
        json.dumps(
            document,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("ascii")
        + b"\n"
    )


def compositor_build_digest() -> str:
    """Bind the adapter, graph, smoothness, clip, and receipt sources."""
    return compositor_build_manifest_digest(compositor_build_manifest())


def validate_compositor_context(value: object) -> PreboundCompositorContextV1:
    """Require one exact private root, tool pair, and source build."""
    if type(value) is not PreboundCompositorContextV1:
        raise PreboundCompositorBuildError(
            "prebound compositor context is invalid"
        )
    paths = (value.candidate_root, value.ffmpeg_path, value.ffprobe_path)
    canonical = all(
        os.path.isabs(path)
        and os.path.realpath(path) == path
        and os.path.normpath(path) == path
        for path in paths
    )
    timeout = value.timeout_seconds
    valid = (
        canonical
        and callable(value.resolve_artifact)
        and type(value.expected_build_digest) is str
        and len(value.expected_build_digest) == 64
        and type(timeout) in {int, float}
        and math.isfinite(timeout)
        and 0 < timeout <= 3600
    )
    if not valid or value.expected_build_digest != compositor_build_digest():
        raise PreboundCompositorBuildError(
            "prebound compositor build is not admitted"
        )
    return value


_LOADED_ROOT = os.path.realpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..")
)
_LOADED_IMPLEMENTATION = tuple(_implementation_rows(_LOADED_ROOT))
