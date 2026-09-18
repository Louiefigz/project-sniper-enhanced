#!/usr/bin/env python3
"""Validate baseline fixtures and reverify current-media input authority."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

EVIDENCE_CLASSES = {
    "synthetic-harness-validation",
    "current-full-path-baseline",
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FIXTURE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


class FixtureAuthorityError(ValueError):
    """A fixture or its admitted source closure is malformed."""


def _safe_relative(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts


def _validate_common(value: object) -> dict[str, Any]:
    required = {
        "schemaVersion", "fixtureId", "evidenceClass", "mode",
        "durationFrames", "fps", "outputPaths",
    }
    allowed = required | {"inputAuthority"}
    if not isinstance(value, dict) or set(value) - allowed or not required <= set(value):
        raise FixtureAuthorityError("baseline fixture manifest is malformed")
    outputs = value["outputPaths"]
    valid_outputs = (
        isinstance(outputs, list)
        and bool(outputs)
        and len(outputs) == len(set(outputs))
        and all(_safe_relative(path) for path in outputs)
    )
    if (
        value["schemaVersion"] != 1
        or not _FIXTURE_ID.fullmatch(str(value["fixtureId"]))
        or value["evidenceClass"] not in EVIDENCE_CLASSES
        or value["mode"] not in {"short", "longform"}
        or isinstance(value["durationFrames"], bool)
        or not isinstance(value["durationFrames"], int)
        or value["durationFrames"] < 1
        or not valid_outputs
    ):
        raise FixtureAuthorityError("baseline fixture manifest is malformed")
    fps = value["fps"]
    if not isinstance(fps, dict) or set(fps) != {"numerator", "denominator"}:
        raise FixtureAuthorityError("baseline fixture FPS is malformed")
    if any(not isinstance(fps[key], str) or not fps[key].isdigit()
           or int(fps[key]) <= 0 for key in fps):
        raise FixtureAuthorityError("baseline fixture FPS is malformed")
    return value


def _validate_current_authority(value: dict[str, Any]) -> None:
    if value["evidenceClass"] != "current-full-path-baseline":
        return
    authority = value.get("inputAuthority")
    keys = {
        "planPath", "planSha256", "manifestPath", "manifestSha256",
        "sourceSetDigest", "snapshotSha256s",
    }
    if not isinstance(authority, dict) or set(authority) != keys:
        raise FixtureAuthorityError(
            "current full-path fixture lacks closed input authority")
    snapshots = authority["snapshotSha256s"]
    hashes = [
        authority["planSha256"], authority["manifestSha256"],
        authority["sourceSetDigest"],
        *(snapshots if isinstance(snapshots, list) else []),
    ]
    if (
        not all(_safe_relative(authority[key])
                for key in ("planPath", "manifestPath"))
        or not isinstance(snapshots, list)
        or not snapshots
        or len(set(snapshots)) != len(snapshots)
        or any(not isinstance(item, str) or not _SHA256.fullmatch(item)
               for item in hashes)
    ):
        raise FixtureAuthorityError(
            "current full-path fixture lacks closed input authority")
    if len(value["outputPaths"]) != 1:
        raise FixtureAuthorityError(
            "current full-path fixture requires exactly one final output")


def load_fixture(path: Path) -> dict[str, Any]:
    """Load one closed fixture document."""
    value = _validate_common(json.loads(path.read_text(encoding="utf-8")))
    _validate_current_authority(value)
    return value


def _authority_file(root: Path, relative: str, label: str) -> Path:
    lexical = root / relative
    if lexical.is_symlink():
        raise FixtureAuthorityError(f"{label} is not a regular file")
    path = lexical.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise FixtureAuthorityError(f"{label} escapes trace cwd") from exc
    if not path.is_file():
        raise FixtureAuthorityError(f"{label} is not a regular file")
    return path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def verify_current_authority(fixture: dict[str, Any], root: Path) -> None:
    """Rehash the exact plan/manifest and sandbox-admitted source set."""
    if fixture["evidenceClass"] != "current-full-path-baseline":
        return
    authority = fixture["inputAuthority"]
    plan = _authority_file(root, authority["planPath"], "baseline plan")
    manifest_path = _authority_file(
        root, authority["manifestPath"], "baseline manifest")
    if (_sha256_file(plan) != authority["planSha256"]
            or _sha256_file(manifest_path) != authority["manifestSha256"]):
        raise FixtureAuthorityError("baseline plan or manifest hash changed")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        from ingest_admission_contract import verify_source_set_binding
        entries = verify_source_set_binding(manifest, manifest_path.parent)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        raise FixtureAuthorityError(
            "baseline source-set authority did not reverify") from exc
    binding = manifest.get("sourceSetAdmission") or {}
    observed = sorted(entry["sha256"] for entry in entries)
    if (binding.get("sourceSetDigest") != authority["sourceSetDigest"]
            or observed != sorted(authority["snapshotSha256s"])):
        raise FixtureAuthorityError("baseline source-set identity changed")
