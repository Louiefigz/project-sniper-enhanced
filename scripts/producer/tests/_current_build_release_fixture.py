"""Synthetic compositor V3/render V4 declarations, never actual build evidence."""
from __future__ import annotations

import hashlib
import json
import stat

from headless.compositor_build_manifest_v3_semantics import (
    COMPOSITOR_BUILD_V3_DIGEST_DOMAIN,
    COMPOSITOR_BUILD_V3_IMPLEMENTATION_PATHS,
    COMPOSITOR_BUILD_V3_POLICY,
)
from headless.render_build_manifest_v4_semantics import (
    RENDER_BUILD_V4_DIGEST_DOMAIN,
    RENDER_BUILD_V4_IMPLEMENTATION_PATHS,
    RENDER_BUILD_V4_POLICY,
)


def canonical(value: object) -> bytes:
    """Encode bounded test metadata with exact canonical spelling."""
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"),
                      sort_keys=True, allow_nan=False).encode("ascii")


def _rows(paths: tuple[str, ...], label: str) -> list[dict]:
    """Derive distinct deterministic identities without reading source files."""
    return [{"path": path, "sha256": hashlib.sha256((label + path).encode()).hexdigest(),
             "sizeBytes": len(label + path)} for path in paths]


def current_manifest(label: str = "test") -> dict:
    """Declare the complete current render V4 schema with synthetic tools."""
    roles = ("docker", "proof-ffmpeg", "proof-ffprobe", "python")
    tools = [{"label": role, "path": f"/opt/sniper/bin/{role}",
              "sha256": hashlib.sha256((label + role).encode()).hexdigest(),
              "sizeBytes": 100 + index} for index, role in enumerate(roles)]
    return {"schemaVersion": 4, "policy": RENDER_BUILD_V4_POLICY,
        "imageId": "sha256:" + "1" * 64, "userId": "501:20",
        "dockerSocket": {"path": "/opt/sniper/docker.sock", "device": 1, "inode": 2,
                         "mode": stat.S_IFSOCK, "ownerUid": 501},
        "runtimeRoot": "/srv/sniper", "pipelineRoot": "/srv/sniper", "timeoutSeconds": 30,
        "pythonFlags": ["-I", "-S", "-B", "-X", "pycache_prefix=<attempt>"],
        "implementation": _rows(RENDER_BUILD_V4_IMPLEMENTATION_PATHS, label), "tools": tools}


def current_compositor_manifest(label: str = "test") -> dict:
    """Declare compositor V3 directly, not by upgrading a retained V1 record."""
    return {"schemaVersion": 3, "policy": COMPOSITOR_BUILD_V3_POLICY,
            "implementation": _rows(COMPOSITOR_BUILD_V3_IMPLEMENTATION_PATHS, label)}


def receipt(manifest: dict, domain: bytes) -> bytes:
    """Hash independently of any live writer; malformed tests may still reseal."""
    digest = hashlib.sha256(domain + canonical(manifest)).hexdigest()
    return canonical({"schemaVersion": manifest["schemaVersion"],
                      "buildDigest": digest, "manifest": manifest}) + b"\n"


def current_receipt(manifest: dict | None = None) -> bytes:
    """Encode render V4 metadata for current-lane tests only."""
    return receipt(current_manifest() if manifest is None else manifest, RENDER_BUILD_V4_DIGEST_DOMAIN)


def current_compositor_receipt(manifest: dict | None = None) -> bytes:
    """Encode compositor V3 metadata with its independent full-document domain."""
    value = current_compositor_manifest() if manifest is None else manifest
    return receipt(value, COMPOSITOR_BUILD_V3_DIGEST_DOMAIN)
