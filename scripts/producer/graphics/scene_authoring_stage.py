"""Strict attempt-owned application staging for project scene authoring."""
from __future__ import annotations

import hashlib
import math
import os
import stat

from contracts.schema_validator import (
    SchemaValidationError,
    validate_document,
)
from graphics.scene_contract import SceneContractError, canonical_json


def _packet(value: object) -> dict:
    try:
        packet = validate_document(
            "scene-authoring-packet-v1.schema.json", value)
    except SchemaValidationError as exc:
        raise SceneContractError(
            f"scene authoring packet schema failed: {exc}") from exc
    authority = packet["sceneAuthority"]
    timing = authority["timing"]
    canvas = authority["canvas"]
    rate = timing["fps"]
    numerator, denominator = int(rate["numerator"]), int(rate["denominator"])
    if not packet["brief"].strip():
        raise SceneContractError("scene authoring brief must be nonblank")
    if canvas["width"] % 2 or canvas["height"] % 2:
        raise SceneContractError("authoring canvas dimensions must be even")
    if math.gcd(numerator, denominator) != 1:
        raise SceneContractError("authoring FPS must be reduced")
    if authority["durationFrames"] != (
            timing["endFrameExclusive"] - timing["startFrame"]):
        raise SceneContractError(
            "authoring durationFrames disagrees with exact timing")
    assets = packet["approvedAssets"]
    if len({row["assetId"] for row in assets}) != len(assets) \
            or len({row["bundleMember"] for row in assets}) != len(assets):
        raise SceneContractError(
            "approved authoring asset IDs and members must be unique")
    examples = packet["examples"]
    if len({row["bundleId"] for row in examples}) != len(examples):
        raise SceneContractError("authoring example bundle IDs must be unique")
    provenance = authority["provenance"]
    if provenance["origin"] == "reference-style" \
            and "stylePackHash" not in provenance:
        raise SceneContractError(
            "reference-style authoring requires stylePackHash")
    return packet


def _attempt(path: object) -> str:
    if not isinstance(path, str) or not os.path.isabs(path) \
            or os.path.normpath(path) != path or os.path.lexists(path):
        raise SceneContractError(
            "authoring attempt path must be absolute, normalized, and unused")
    parent = os.path.dirname(path)
    if os.path.realpath(parent) != parent or os.path.islink(parent) \
            or not os.path.isdir(parent):
        raise SceneContractError(
            "authoring attempt parent must be a canonical real directory")
    os.mkdir(path, mode=0o700)
    os.chmod(path, 0o700)
    info = os.stat(path, follow_symlinks=False)
    if info.st_uid != os.geteuid() \
            or stat.S_IMODE(info.st_mode) != 0o700:
        raise SceneContractError(
            "authoring attempt is not owned with mode 0700")
    return path


def _write(path: str, value: dict, mode: int = 0o400) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL \
        | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, mode)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(canonical_json(value) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def _sync_directory(path: str) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def stage_scene_authoring(value: object, attempt_path: str) -> dict:
    """Stage a closed packet; this does not claim OS/model write isolation."""
    packet = _packet(value)
    attempt = _attempt(attempt_path)
    bundle = os.path.join(attempt, "bundle")
    os.mkdir(bundle, mode=0o700)
    os.chmod(bundle, 0o700)
    packet_path = os.path.join(attempt, "authoring-packet.json")
    _write(packet_path, packet)
    packet_hash = hashlib.sha256(canonical_json(packet)).hexdigest()
    boundary = {
        "attemptOwned": True, "ownerUid": os.geteuid(), "mode": "0700",
        "applicationWriteRoot": bundle,
        "applicationPathContractOnly": True,
        "osSandboxProved": False, "modelWriteIsolationProved": False,
    }
    value = {
        "schemaVersion": 1, "kind": "scene-authoring-stage",
        "attemptId": packet["attemptId"], "attemptPath": attempt,
        "packetPath": packet_path, "packetHash": packet_hash,
        "bundlePath": bundle, "filesystemBoundary": boundary,
    }
    receipt = {**value, "receiptHash": hashlib.sha256(
        canonical_json(value)).hexdigest()}
    _write(os.path.join(attempt, "stage-receipt.json"), receipt)
    _sync_directory(attempt)
    _sync_directory(os.path.dirname(attempt))
    return receipt
