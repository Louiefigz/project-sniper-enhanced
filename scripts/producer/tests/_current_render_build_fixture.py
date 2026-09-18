"""Synthetic complete V2 metadata for current-lane unit tests, not proof.

These identities describe no actual executable or source bytes. Historical
V1 fixture generators remain independent and retain their original schema.
"""

from __future__ import annotations

import hashlib
import json
import stat

from headless.render_build_manifest_v2_contract import (
    RENDER_BUILD_V2_DIGEST_DOMAIN,
    RENDER_BUILD_V2_IMPLEMENTATION_PATHS,
    RENDER_BUILD_V2_POLICY,
)


def canonical(value: object) -> bytes:
    """Return exact canonical bytes for synthetic wire mutation tests."""
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"),
                      sort_keys=True, allow_nan=False).encode("ascii")


def current_manifest(label: str = "test") -> dict:
    """Return complete, structurally valid metadata with distinct identities."""
    source_rows = [{
        "path": path,
        "sha256": hashlib.sha256((label + path).encode()).hexdigest(),
        "sizeBytes": len(label + path),
    } for path in RENDER_BUILD_V2_IMPLEMENTATION_PATHS]
    tools = [{
        "label": role, "path": f"/opt/sniper/bin/{role}",
        "sha256": hashlib.sha256((label + role).encode()).hexdigest(),
        "sizeBytes": 100 + index,
    } for index, role in enumerate(("docker", "proof-ffmpeg", "proof-ffprobe", "python"))]
    return {
        "schemaVersion": 2, "policy": RENDER_BUILD_V2_POLICY,
        "imageId": "sha256:" + "1" * 64, "userId": "501:20",
        "dockerSocket": {
            "path": "/opt/sniper/docker.sock", "device": 1, "inode": 2,
            "mode": stat.S_IFSOCK, "ownerUid": 501,
        },
        "runtimeRoot": "/srv/sniper", "pipelineRoot": "/srv/sniper",
        "timeoutSeconds": 30,
        "pythonFlags": ["-I", "-S", "-B", "-X", "pycache_prefix=<attempt>"],
        "implementation": source_rows, "tools": tools,
    }


def current_receipt(manifest: dict | None = None) -> bytes:
    """Encode V2 with the frozen domain, without calling the live writer."""
    document = manifest if manifest is not None else current_manifest()
    digest = hashlib.sha256(RENDER_BUILD_V2_DIGEST_DOMAIN + canonical(document)).hexdigest()
    return canonical({"buildDigest": digest, "manifest": document, "schemaVersion": 2}) + b"\n"
