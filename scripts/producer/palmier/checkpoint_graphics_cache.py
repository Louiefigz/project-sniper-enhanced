"""Content-addressed full-canvas alpha assets for Palmier graphics."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import uuid
from dataclasses import dataclass

from fingerprints import file_sha256, json_canon, write_json_atomic
from graphics.asset_proof import AssetProofRequest, prove_rendered_asset
from graphics.render_cache import _key_lock
from palmier.mcp_client import PalmierError

_VERSION = 1
_KIND = "palmier-checkpoint-placed-graphic"


@dataclass(frozen=True)
class PlacedAssetRequest:
    """Closed inputs for one placed, delivery-sized alpha render."""

    entry: dict
    raw_path: str
    raw_proof: dict
    cache_dir: str
    fps: float
    canvas: tuple[int, int]
    offset: tuple[int, int]
    metadata: dict
    reference: dict | None = None


def _proof_path(path: str) -> str:
    return path + ".proof.json"


def _receipt_path(path: str) -> str:
    return path + ".placement.json"


def _read_json(path: str, label: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PalmierError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise PalmierError(f"{label} is not an object")
    return value


def _raw_authority(request: PlacedAssetRequest) -> dict:
    path = os.path.abspath(request.raw_path)
    proof_path = _proof_path(path)
    proof = request.raw_proof
    asset = proof.get("asset") if isinstance(proof, dict) else None
    digest = file_sha256(path)
    if proof.get("schemaVersion") != 1 or not isinstance(asset, dict) \
            or asset.get("sha256") != digest:
        raise PalmierError("checkpoint graphic proof is not bound to raw media")
    if not os.path.isfile(proof_path):
        raise PalmierError(f"checkpoint graphic proof is missing: {proof_path}")
    stored = _read_json(proof_path, "checkpoint graphic proof")
    supplied = {key: value for key, value in proof.items()
                if key != "sidecar"}
    if json_canon(stored) != json_canon(supplied):
        raise PalmierError(
            "checkpoint graphic proof object differs from its sidecar")
    return {"path": path, "sha256": digest, "proofPath": proof_path,
            "proofSha256": file_sha256(proof_path)}


def _delivery(request: PlacedAssetRequest) -> dict:
    asset = request.raw_proof.get("asset") or {}
    frames = int(asset.get("frameCount") or 0)
    if frames <= 0 or request.fps <= 0:
        raise PalmierError("checkpoint graphic proof has no positive frame rate")
    width, height = request.canvas
    if width <= 0 or height <= 0:
        raise PalmierError("checkpoint graphic delivery canvas is not positive")
    return {"width": width, "height": height, "fps": request.fps,
            "frameCount": frames, "durationS": frames / request.fps}


def _placement(request: PlacedAssetRequest) -> dict:
    scale = request.metadata.get("scaledDims")
    if scale is not None:
        if not isinstance(scale, (list, tuple)) or len(scale) != 2:
            raise PalmierError("checkpoint graphic scaledDims is malformed")
        scale = [int(scale[0]), int(scale[1])]
        if min(scale) <= 0:
            raise PalmierError("checkpoint graphic scaledDims is not positive")
    return {"x": int(request.offset[0]), "y": int(request.offset[1]),
            "scaledDims": scale, "metadata": json_canon(request.metadata)}


def _key_payload(request: PlacedAssetRequest) -> dict:
    reference = json_canon(request.reference)
    return {"schemaVersion": _VERSION, "raw": _raw_authority(request),
            "entry": json_canon(request.entry), "delivery": _delivery(request),
            "placement": _placement(request), "reference": reference}


def _cache_key(request: PlacedAssetRequest) -> str:
    raw = json.dumps(_key_payload(request), sort_keys=True,
                     separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _filter_graph(request: PlacedAssetRequest) -> str:
    delivery = _delivery(request)
    placement = _placement(request)
    width, height = delivery["width"], delivery["height"]
    fps, duration = delivery["fps"], delivery["durationS"]
    prefix = ""
    if placement["scaledDims"]:
        scaled_w, scaled_h = placement["scaledDims"]
        prefix = f"scale={scaled_w}:{scaled_h}:flags=lanczos,"
    return (
        f"color=c=black@0.0:s={width}x{height}:r={fps:.12g}:"
        f"d={duration:.12g},format=rgba[canvas];"
        f"[0:v]{prefix}setpts=PTS-STARTPTS,format=rgba[graphic];"
        f"[canvas][graphic]overlay=x={placement['x']}:y={placement['y']}:"
        "format=auto:eof_action=pass,format=yuva444p10le[out]"
    )


def _render(request: PlacedAssetRequest, output: str) -> None:
    delivery = _delivery(request)
    command = [
        "ffmpeg", "-nostdin", "-v", "error", "-y", "-i", request.raw_path,
        "-filter_complex", _filter_graph(request), "-map", "[out]", "-an",
        "-frames:v", str(delivery["frameCount"]), "-r",
        f"{request.fps:.12g}", "-c:v", "prores_ks", "-profile:v", "4444",
        "-pix_fmt", "yuva444p10le", output,
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise PalmierError(
            "checkpoint graphic placement render failed: "
            + (result.stderr or result.stdout).strip()[-500:])


def _prove(request: PlacedAssetRequest, path: str, key: str) -> dict:
    delivery = _delivery(request)
    return prove_rendered_asset(AssetProofRequest(
        path, request.entry, "mov", request.canvas,
        delivery["durationS"], key, request.fps))


def _output_record(path: str, proof_path: str) -> dict:
    return {"path": os.path.abspath(path), "sha256": file_sha256(path),
            "proofPath": os.path.abspath(proof_path),
            "proofSha256": file_sha256(proof_path)}


def _receipt(request: PlacedAssetRequest, key: str,
             path: str, proof_path: str) -> dict:
    payload = _key_payload(request)
    return {"schemaVersion": _VERSION, "kind": _KIND, "key": key,
            "rawAsset": payload["raw"], "entry": payload["entry"],
            "delivery": payload["delivery"], "placement": payload["placement"],
            "reference": payload["reference"],
            "output": _output_record(path, proof_path)}


def _quarantine(path: str) -> None:
    suffix = f".rejected-{uuid.uuid4().hex}"
    for candidate in (path, _proof_path(path), _receipt_path(path)):
        if os.path.lexists(candidate):
            os.replace(candidate, candidate + suffix)


def _digest(path: str, cache: dict[str, str]) -> str:
    absolute = os.path.abspath(path)
    if absolute not in cache:
        cache[absolute] = file_sha256(absolute)
    return cache[absolute]


def validate_placement_receipt(
    path: str,
    digest_cache: dict[str, str] | None = None,
) -> dict:
    """Validate every byte edge named by a placement receipt."""
    cache = digest_cache if digest_cache is not None else {}
    receipt_path = _receipt_path(path)
    receipt = _read_json(receipt_path, "checkpoint placement receipt")
    if receipt.get("schemaVersion") != _VERSION or receipt.get("kind") != _KIND:
        raise PalmierError("checkpoint placement receipt has unknown schema")
    for label in ("rawAsset", "output"):
        record = receipt.get(label)
        if not isinstance(record, dict):
            raise PalmierError(f"checkpoint placement receipt lacks {label}")
        for path_key, hash_key in (
                ("path", "sha256"), ("proofPath", "proofSha256")):
            target, expected = record.get(path_key), record.get(hash_key)
            if not isinstance(target, str) or not isinstance(expected, str) \
                    or _digest(target, cache) != expected:
                raise PalmierError(
                    f"checkpoint placement receipt {label}.{path_key} drifted")
    reference = receipt.get("reference")
    if reference is not None:
        if not isinstance(reference, dict) \
                or _digest(str(reference.get("path")), cache) \
                != reference.get("sha256"):
            raise PalmierError("checkpoint placement reference drifted")
    if os.path.abspath(path) != receipt["output"]["path"]:
        raise PalmierError("checkpoint placement receipt names another output")
    proof = _read_json(receipt["output"]["proofPath"],
                       "checkpoint placed graphic proof")
    if (proof.get("asset") or {}).get("sha256") \
            != receipt["output"]["sha256"]:
        raise PalmierError("checkpoint placed graphic proof is stale")
    return receipt


def _current(path: str, expected: dict) -> dict | None:
    reference = expected.get("reference")
    cache = ({os.path.abspath(reference["path"]): reference["sha256"]}
             if isinstance(reference, dict) else {})
    try:
        found = validate_placement_receipt(path, cache)
    except (OSError, PalmierError, ValueError):
        return None
    return found if found == expected else None


def _promote(candidate: str, output: str, request: PlacedAssetRequest,
             key: str, proof: dict) -> dict:
    candidate_proof = _proof_path(candidate)
    output_proof = _proof_path(output)
    try:
        os.replace(candidate, output)
        os.replace(candidate_proof, output_proof)
        proof["sidecar"] = output_proof
        receipt = _receipt(request, key, output, output_proof)
        write_json_atomic(_receipt_path(output), receipt, indent=2)
        return receipt
    except Exception:
        _quarantine(output)
        raise


def materialize_placed_asset(request: PlacedAssetRequest) -> dict:
    """Return a proved full-canvas alpha asset, rebuilding any stale hit."""
    os.makedirs(request.cache_dir, exist_ok=True)
    key = _cache_key(request)
    output = os.path.join(
        request.cache_dir, f"checkpoint-placed-{key}.mov")
    lock = os.path.join(request.cache_dir, f".checkpoint-placed-{key}.lock")
    with _key_lock(lock):
        if os.path.isfile(output) and os.path.isfile(_proof_path(output)):
            proof = _read_json(_proof_path(output), "placed graphic proof")
            expected = _receipt(request, key, output, _proof_path(output))
            receipt = _current(output, expected)
            if receipt is not None:
                proof["sidecar"] = _proof_path(output)
                return {"path": output, "proof": proof, "receipt": receipt,
                        "key": key, "cached": True}
            _quarantine(output)
        descriptor, candidate = tempfile.mkstemp(
            prefix=f".{key}.", suffix=".mov", dir=request.cache_dir)
        os.close(descriptor)
        try:
            _render(request, candidate)
            proof = _prove(request, candidate, key)
            receipt = _promote(candidate, output, request, key, proof)
        finally:
            for path in (candidate, _proof_path(candidate)):
                if os.path.exists(path):
                    os.remove(path)
        return {"path": output, "proof": proof, "receipt": receipt,
                "key": key, "cached": False}
