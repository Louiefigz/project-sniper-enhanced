"""Bind external-media rows only through controller-inspected origin sidecars."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INSPECTOR = PROJECT_ROOT / "scripts" / "producer" / "native-short.ts"


def _inspection(sidecar: Path) -> dict:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("external-media origin inspection requires Node.js")
    result = subprocess.run(
        [node, "--import", "tsx", str(INSPECTOR),
         "inspect-origin", str(sidecar)],
        cwd=PROJECT_ROOT, capture_output=True, text=True,
        timeout=60, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"external-media origin inspection failed: {result.stderr[-1200:]}")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "external-media origin inspector returned invalid JSON") from exc
    if type(value) is not dict:
        raise RuntimeError("external-media origin inspection is malformed")
    return value


def _authorization(row: dict, sidecar: Path) -> dict | None:
    inspected = _inspection(sidecar)
    expected_keys = {
        "schemaVersion", "status", "asset", "origin",
        "authorizationEvidence",
    }
    if set(inspected) != expected_keys or inspected.get("schemaVersion") != 1:
        raise RuntimeError("external-media origin inspection is malformed")
    asset = inspected.get("asset")
    if type(asset) is not dict or asset.get("path") != row.get("originalPath") \
            or asset.get("sha256") != row.get("sourceSha256") \
            or asset.get("sizeBytes") != row.get("sourceSizeBytes"):
        raise RuntimeError("external-media origin differs from admitted ingress")
    evidence = inspected.get("authorizationEvidence")
    eligible = inspected.get("status") == \
        "controller-authorized-for-local-review"
    if eligible != (type(evidence) is dict):
        raise RuntimeError("external-media authorization status is inconsistent")
    if evidence is not None and evidence != inspected.get("origin"):
        raise RuntimeError("external-media authorization differs from its origin")
    return evidence


def external_authorization(original: str, sha256: str,
                           size_bytes: int) -> dict | None:
    """Derive one authorization pin from its exact sibling controller sidecar."""
    source = Path(original)
    if not source.is_absolute():
        raise RuntimeError("external-media row lacks an original ingress path")
    sidecar = source.parent / "ASSET.json"
    if not sidecar.exists():
        return None
    if sidecar.is_symlink() or not sidecar.is_file():
        raise RuntimeError("external-media ASSET.json is not a regular file")
    row = {"originalPath": original, "sourceSha256": sha256,
           "sourceSizeBytes": size_bytes}
    return _authorization(row, sidecar.resolve(strict=True))
