"""Exact request, admitted-source, and executable identities for cut previews."""
from __future__ import annotations

import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

from cut_preview_io import bound_json, digest, file_hash, real_directory
from edit.compatibility_projection import build_projection
from ingest_execution_authority import execution_media_authority_entries
from render_effect_discovery import local_python_import_closure

SHA = re.compile(r"^[a-f0-9]{64}$")
REQUEST_HASHES = {
    "requestHash", "requestKey", "planHash", "authorityDigest",
    "cutAuthorityDigest", "cutApprovalReceiptHash", "cutReviewApprovalReceiptHash",
    "pictureLockHash", "timelineMapHash", "projectionReceiptHash",
}
INPUT_KEYS = {"schemaVersion", "request", "producerDir", "planPath",
              "manifestPath", "executionKey", "attempt", "runId",
              "pipelineDigest", "proxyScale", "timeoutSeconds", "createdAt", "executionNonce"}


def request_value(value: object) -> dict:
    """Validate the frozen request without adding acceptance semantics."""
    if type(value) is not dict or set(value) != REQUEST_HASHES | {"schemaVersion", "createdAt"}:
        raise RuntimeError("cut preview requires the exact V1 cut request")
    if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1 \
            or any(type(value[key]) is not str or not SHA.fullmatch(value[key])
                   for key in REQUEST_HASHES):
        raise RuntimeError("cut preview request has malformed identity")
    created = value["createdAt"]
    if type(created) is not str or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", created):
        raise RuntimeError("cut preview request timestamp is malformed")
    datetime.fromisoformat(created.replace("Z", "+00:00"))
    if value["requestHash"] != digest({key: item for key, item in value.items()
                                        if key != "requestHash"}):
        raise RuntimeError("cut preview request hash changed")
    return value


def validate_input(value: dict, input_path: Path, new_only: bool = True) -> Path:
    """Derive the only permitted new-only artifact directory."""
    if type(value) is not dict or set(value) != INPUT_KEYS \
            or type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1:
        raise RuntimeError("cut preview invocation is malformed")
    request = request_value(value["request"])
    if type(value["executionKey"]) is not str or not SHA.fullmatch(value["executionKey"]):
        raise RuntimeError("cut preview execution key is malformed")
    if type(value["attempt"]) is not int or not 1 <= value["attempt"] <= 10000 \
            or type(value["runId"]) is not str or not 1 <= len(value["runId"]) <= 200 \
            or type(value["proxyScale"]) not in {int, float} \
            or not 0 < value["proxyScale"] <= 1 \
            or type(value["timeoutSeconds"]) is not int \
            or not 1 <= value["timeoutSeconds"] <= 900:
        raise RuntimeError("cut preview execution bounds are malformed")
    if type(value["executionNonce"]) is not str or not re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", value["executionNonce"]) \
            or (value["pipelineDigest"] is not None and (type(value["pipelineDigest"]) is not str
                or not SHA.fullmatch(value["pipelineDigest"]))) \
            or type(value["createdAt"]) is not str or not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", value["createdAt"]):
        raise RuntimeError("cut preview invocation identity is malformed")
    datetime.fromisoformat(value["createdAt"].replace("Z", "+00:00"))
    key_fields = ("runId", "attempt", "createdAt", "executionNonce", "proxyScale", "pipelineDigest")
    expected_key = digest({"requestHash": request["requestHash"],
                           **{key: value[key] for key in key_fields}})
    if value["executionKey"] != expected_key:
        raise RuntimeError("cut preview execution key does not bind its attempt")
    producer = Path(value["producerDir"])
    real_directory(producer)
    output = producer / "cut-previews" / request["requestHash"] / value["executionKey"]
    if input_path != output / "input.json":
        raise RuntimeError("cut preview output path is not controller-derived")
    real_directory(output)
    if new_only and set(item.name for item in output.iterdir()) != {"input.json"}:
        raise RuntimeError("cut preview attempt is not new and empty")
    return output


def observe_inputs(value: dict) -> tuple[dict, dict, dict]:
    """Recheck exact request/lock/projection and every admitted source byte."""
    request = request_value(value["request"])
    producer = Path(value["producerDir"])
    plan = bound_json(Path(value["planPath"]), request["planHash"])
    bound_json(producer / ".sniper-cut-approval.json", request["cutApprovalReceiptHash"])
    bound_json(producer / ".sniper-cut-review-approved.json", request["cutReviewApprovalReceiptHash"])
    lock = bound_json(producer / "picture_locks" / f"{request['pictureLockHash']}.json",
                      request["pictureLockHash"])
    for key in ("cutAuthorityDigest", "cutApprovalReceiptHash",
                "cutReviewApprovalReceiptHash", "timelineMapHash", "projectionReceiptHash"):
        if lock.get(key) != request[key]:
            raise RuntimeError("cut preview picture lock disagrees with request")
    projection = bound_json(producer / "compatibility_projections"
                            / f"{request['projectionReceiptHash']}.json", request["projectionReceiptHash"])
    if build_projection(plan, lock["approvedCutPlanHash"]) != projection:
        raise RuntimeError("cut preview compiler/projection disagrees with approved cut")
    manifest_path = Path(value["manifestPath"])
    manifest = bound_json(manifest_path, lock["manifestHash"])
    entries = execution_media_authority_entries(plan, manifest, str(manifest_path))
    if entries is None:
        raise RuntimeError("cut preview requires admitted sources; re-ingest this legacy project")
    if not entries or not manifest.get("sources"):
        raise RuntimeError("cut preview has no admitted source set")
    return plan, manifest, {
        "sourceSetDigest": manifest["sourceSetAdmission"]["sourceSetDigest"],
        "sourceSetReceiptHash": manifest["sourceSetAdmission"]["receiptSha256"],
        "manifestHash": lock["manifestHash"],
    }


def toolchain(value: dict) -> dict:
    """Bind the actual pinned script closure, interpreter, FFmpeg and FFprobe."""
    root = Path(__file__).resolve().parent
    paths = local_python_import_closure([root / "cut_preview.py"])
    paths.append(root.parents[1] / "schemas/producer/channel-normalization-receipt-v1.schema.json")
    binaries = {"python": str(Path(sys.executable).resolve())}
    for name in ("ffmpeg", "ffprobe"):
        resolved = shutil.which(name)
        if not resolved:
            raise RuntimeError(f"cut preview is missing {name}")
        binaries[name] = str(Path(resolved).resolve())
    paths.extend(Path(item) for item in binaries.values())
    rows = [{"path": str(item), "sha256": file_hash(item)} for item in sorted(set(paths))]
    core = {"kind": "cut-preview-toolchain-v1", "pipelineDigest": value["pipelineDigest"],
            "files": rows, "binaries": binaries}
    return {**core, "toolchainHash": digest(core)}
