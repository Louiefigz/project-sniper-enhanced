"""Strict parent-side validation for one headless render-worker result."""
from __future__ import annotations
import hashlib
import json
import math
import os
import re
import stat
from dataclasses import dataclass
from typing import Any
from .runtime_receipt import validate_runtime_attestation
from .sealed_archive import validate_manifest
_SHA256 = re.compile(r"[0-9a-f]{64}")
_IMAGE = re.compile(r"sha256:[0-9a-f]{64}")
_PROOF_KEYS = {
    "alphaMode", "asset", "assetInputs", "copy", "decode", "kind",
    "occupancy", "runtimeAttestation", "schemaVersion", "sidecar",
    "terminalFrame",
}
_ASSET_KEYS = {
    "codec", "durationS", "fps", "frameCount", "height", "pixelFormat",
    "profile", "sha256", "sizeBytes", "width",
}
_RUNTIME_KEYS = {
    "activeNetworkProof", "attestationScope", "containerAfterOutput",
    "containerBeforeOutput", "containerRemoval", "dockerRuntime", "imageId",
    "imageAttestation", "outputSha256", "policy", "retainedInputArchive",
    "schemaVersion", "snapshotManifest", "snapshotSha256",
}
@dataclass(frozen=True)
class RenderExpectation:
    """Facts a trusted controller must supply and a worker must match."""
    kind: str
    fmt: str
    width: int
    height: int
    duration: float
    frame_count: int
    expected_copy: tuple[str, ...]
    asset_bindings: tuple[tuple[str, str, str, str], ...]
    variables_sha256: str
    container_names: tuple[str, ...]
    snapshot_sha256: str
    snapshot_manifest: tuple[dict, ...]
@dataclass(frozen=True)
class RenderProofIntent:
    """Expected proof fields that the future trusted controller must own."""
    fmt: str
    dimensions: tuple[int, int]
    expected_copy: tuple[str, ...]
    expected_asset_bindings: tuple[dict, ...]
    container_names: tuple[str, ...] = ()
    snapshot_sha256: str = ""
    snapshot_manifest: tuple[dict, ...] = ()
def _asset_bindings(rows: Any) -> tuple[tuple[str, str, str, str], ...]:
    if not isinstance(rows, (list, tuple)):
        raise RuntimeError("render proof asset inputs must be a list")
    normalized = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"field", "selector", "path", "sha256"}:
            raise RuntimeError("render proof asset-input row is invalid")
        field, selector, path, digest = (row[key] for key in
                                         ("field", "selector", "path", "sha256"))
        safe_path = (isinstance(path, str) and path.startswith("motion/")
                     and "\\" not in path and os.path.normpath(path) == path)
        if (not isinstance(field, str) or not field or not isinstance(selector, str)
                or not selector or not safe_path or not _SHA256.fullmatch(str(digest))):
            raise RuntimeError("render proof asset-input values are invalid")
        normalized.append((field, selector, path, digest))
    ordered = tuple(sorted(normalized))
    if len(ordered) != len(rows) or tuple(normalized) != ordered \
            or len(set(ordered)) != len(ordered):
        raise RuntimeError("render proof asset inputs are not canonical")
    return ordered
def build_expectation(entry: dict[str, Any],
                      intent: RenderProofIntent) -> RenderExpectation:
    """Normalize explicit request facts before child launch."""
    kind = entry.get("kind")
    if not isinstance(kind, str) or not kind:
        raise RuntimeError("render expectation requires an explicit kind")
    if (intent.fmt not in {"mov", "mp4"} or len(intent.dimensions) != 2
            or any(type(value) is not int or value <= 0
                   for value in intent.dimensions)):
        raise RuntimeError("render expectation format or dimensions are invalid")
    if any(not isinstance(value, str) for value in intent.expected_copy):
        raise RuntimeError("render expectation copy must contain strings")
    if not _SHA256.fullmatch(intent.snapshot_sha256):
        raise RuntimeError("render expectation snapshot digest is invalid")
    validate_manifest(intent.snapshot_manifest)
    try:
        duration = float(entry["outEnd"]) - float(entry["outStart"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("render expectation window is invalid") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise RuntimeError("render expectation duration must be positive")
    variables = json.dumps(entry.get("spec") or {}, ensure_ascii=True,
                           separators=(",", ":"), sort_keys=True).encode()
    return RenderExpectation(
        kind, intent.fmt, intent.dimensions[0], intent.dimensions[1], duration,
        round(duration * 30), intent.expected_copy,
        _asset_bindings(intent.expected_asset_bindings),
        hashlib.sha256(variables).hexdigest(), intent.container_names,
        intent.snapshot_sha256, intent.snapshot_manifest)


def _validate_asset(asset: Any, output: dict,
                    expected: RenderExpectation) -> None:
    if not isinstance(asset, dict) or set(asset) != _ASSET_KEYS:
        raise RuntimeError("render proof asset schema is invalid")
    codec = {"mov": ("prores", "yuva444p12le"),
             "mp4": ("h264", "yuv420p")}[expected.fmt]
    tolerance = max(1.0 / 30.0 + 0.005, 0.04)
    valid = (
        asset["sha256"] == output["sha256"]
        and asset["sizeBytes"] == output["sizeBytes"]
        and (asset["width"], asset["height"]) == (expected.width, expected.height)
        and asset["codec"] == codec[0] and asset["pixelFormat"] == codec[1]
        and type(asset["frameCount"]) is int
        and asset["frameCount"] == expected.frame_count
        and type(asset["fps"]) in {int, float} and asset["fps"] == 30
        and type(asset["durationS"]) in {int, float}
        and math.isfinite(asset["durationS"])
        and abs(asset["durationS"] - expected.duration) <= tolerance
        and (expected.fmt != "mov" or asset["profile"] == "4444")
    )
    if not valid:
        raise RuntimeError("render proof asset does not match controller intent")


def _validate_copy(copy: Any, key: str,
                   expected: RenderExpectation) -> None:
    keys = {"expected", "method", "note", "renderInputKey", "sha256"}
    encoded = json.dumps(list(expected.expected_copy), ensure_ascii=False,
                         separators=(",", ":")).encode()
    valid = (
        isinstance(copy, dict) and set(copy) == keys
        and copy["method"] == "validated-template-input"
        and copy["expected"] == list(expected.expected_copy)
        and copy["renderInputKey"] == key
        and copy["sha256"] == hashlib.sha256(encoded).hexdigest()
    )
    if not valid:
        raise RuntimeError("render proof copy is not bound to controller intent")


def _validate_occupancy(value: Any, expected: RenderExpectation) -> None:
    base_keys = {"basis", "canvasPx", "measured", "mode"}
    if not isinstance(value, dict) or set(value) not in (base_keys,
                                                         base_keys | {"areaRatio"}):
        raise RuntimeError("render proof occupancy schema is invalid")
    measured = value["measured"]
    keys = {"meanRatio", "meaningfulFrameFraction", "meaningfulFrames", "method",
            "peakRatio", "sampleFps", "sampledFrames", "sustainedRatio"}
    if not isinstance(measured, dict) or set(measured) != keys:
        raise RuntimeError("render proof occupancy measurement is invalid")
    ratios = [measured[key] for key in
              ("meanRatio", "meaningfulFrameFraction", "peakRatio", "sustainedRatio")]
    sampled, meaningful = measured["sampledFrames"], measured["meaningfulFrames"]
    valid = (
        value["canvasPx"] == [expected.width, expected.height]
        and isinstance(value["basis"], str) and bool(value["basis"])
        and value["mode"] in {"alpha-hole-canvas", "alpha-overlay",
                              "opaque-measured-content", "presenter-filled-card"}
        and all(type(number) in {int, float} and math.isfinite(number)
                and 0 <= number <= 1 for number in ratios)
        and type(sampled) is int and type(meaningful) is int
        and 0 < meaningful <= sampled
        and type(measured["sampleFps"]) is int and measured["sampleFps"] > 0
        and measured["method"] in {"ffmpeg-alpha-sustained-area",
                                   "ffmpeg-rgb-sustained-content"}
        and abs(measured["meaningfulFrameFraction"] - meaningful / sampled) < 1e-12
        and measured["peakRatio"] >= measured["sustainedRatio"])
    if "areaRatio" in value:
        valid = valid and value["mode"] == "opaque-measured-content" \
            and value["areaRatio"] == measured["sustainedRatio"]
    if not valid:
        raise RuntimeError("render proof occupancy contradicts its measurements")


def _validate_media_oracles(proof: dict, expected: RenderExpectation) -> None:
    decode = proof["decode"]
    if decode != {"decoded": True, "method": "ffmpeg-full-xerror"}:
        raise RuntimeError("render proof lacks a complete decode oracle")
    terminal = proof["terminalFrame"]
    if expected.fmt == "mov":
        valid_terminal = (
            isinstance(terminal, dict)
            and set(terminal) == {"frame", "maxAlpha8", "meanAlpha8", "method"}
            and terminal["method"] == "ffmpeg-final-encoded-alpha"
            and type(terminal["frame"]) is int
            and terminal["frame"] == expected.frame_count - 1
            and type(terminal["maxAlpha8"]) is int and terminal["maxAlpha8"] == 0
            and type(terminal["meanAlpha8"]) in {int, float}
            and terminal["meanAlpha8"] == 0)
        if not valid_terminal:
            raise RuntimeError("render proof lacks a clear final alpha frame")
    elif terminal is not None:
        raise RuntimeError("opaque render proof has an unexpected terminal oracle")
    _validate_occupancy(proof["occupancy"], expected)


def _manifest_row(runtime: dict, path: str) -> dict | None:
    manifest = runtime.get("snapshotManifest")
    if not isinstance(manifest, list):
        return None
    rows = [row for row in manifest
            if isinstance(row, dict) and row.get("path") == path]
    return rows[0] if len(rows) == 1 else None


def _validate_runtime(runtime: Any, output: dict,
                      expected: RenderExpectation) -> None:
    if not isinstance(runtime, dict) or set(runtime) != _RUNTIME_KEYS:
        raise RuntimeError("render proof runtime schema is invalid")
    variables = _manifest_row(runtime, "request/variables.json") or {}
    retained = runtime.get("retainedInputArchive") or {}
    network = runtime.get("activeNetworkProof") or {}
    removal = runtime.get("containerRemoval") or {}
    valid = (
        runtime["schemaVersion"] == 1
        and runtime["policy"] == "sniper-oci-render-v2"
        and bool(_IMAGE.fullmatch(str(runtime["imageId"])))
        and runtime["outputSha256"] == output["sha256"]
        and variables.get("sha256") == expected.variables_sha256
        and runtime["snapshotSha256"] == expected.snapshot_sha256
        and runtime["snapshotManifest"] == list(expected.snapshot_manifest)
        and retained.get("sha256") == runtime["snapshotSha256"]
        and network.get("hostDecoyPositive") is True
        and removal.get("canonicalAbsenceProved") is True
    )
    if not valid:
        raise RuntimeError("render proof runtime is not bound to controller intent")
    label = "io.project-sniper.render-name"
    before = (runtime["containerBeforeOutput"].get("Config") or {}).get("Labels") or {}
    after = (runtime["containerAfterOutput"].get("Config") or {}).get("Labels") or {}
    if (not expected.container_names or before.get(label) != after.get(label)
            or before.get(label) not in expected.container_names):
        raise RuntimeError("render proof container is not the registered resource")


def _validate_asset_inputs(rows: Any, runtime: dict,
                           expected: RenderExpectation) -> None:
    actual = _asset_bindings(rows)
    if actual != expected.asset_bindings:
        raise RuntimeError("render proof asset inputs do not match controller intent")
    for _, _, path, digest in actual:
        manifest = _manifest_row(runtime, path)
        if manifest is None or manifest.get("sha256") != digest:
            raise RuntimeError("render proof asset input is absent from sealed snapshot")


def _validate_sidecar(proof: dict, media_path: str) -> None:
    path = proof.get("sidecar")
    if path != media_path + ".proof.json":
        raise RuntimeError("render proof sidecar path is invalid")
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        raw = os.read(fd, 1_048_577)
    finally:
        os.close(fd)
    safe = (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and info.st_uid == os.geteuid()
            and stat.S_IMODE(info.st_mode) == 0o600 and len(raw) <= 1_048_576)
    try:
        disk = json.loads(raw) if safe else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        disk = None
    expected = {key: value for key, value in proof.items() if key != "sidecar"}
    if disk != expected:
        raise RuntimeError("render proof sidecar does not match worker result")


def validate_worker_proof(value: dict, output: dict,
                          expected: RenderExpectation,
                          expected_image_id: str) -> None:
    """Require a complete proof bound to request, media, and retained sidecar."""
    proof = value.get("proof")
    if not isinstance(proof, dict) or set(proof) != _PROOF_KEYS:
        raise RuntimeError("headless render worker returned an incomplete proof")
    if proof["schemaVersion"] != 1 or proof["kind"] != expected.kind:
        raise RuntimeError("render proof identity is invalid")
    alpha = "required" if expected.fmt == "mov" else "opaque"
    if proof["alphaMode"] != alpha or not isinstance(proof["assetInputs"], list):
        raise RuntimeError("render proof alpha or asset-input schema is invalid")
    _validate_asset(proof["asset"], output, expected)
    _validate_copy(proof["copy"], value["key"], expected)
    _validate_media_oracles(proof, expected)
    runtime = proof["runtimeAttestation"]
    _validate_runtime(runtime, output, expected)
    _validate_asset_inputs(proof["assetInputs"], runtime, expected)
    validate_runtime_attestation(
        runtime, value["path"], output["sha256"], expected_image_id)
    _validate_sidecar(proof, value["path"])
