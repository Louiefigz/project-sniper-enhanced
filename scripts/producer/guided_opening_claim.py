"""Exact server-held execution claims and trusted Docker controls for recovery.

An externally held raw claim SHA is required. JSON digests alone do not
authenticate a journal/lease: the server supplies those durable guarantees.
Recovery reads no source media and never searches outside exact claimed orders.
"""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from cut_preview_io import digest, file_hash
from guided_opening_inputs import _document, _json, closed, hash_value
from headless.resource_ledger import ResourceRequest

_KEYS = {"schemaVersion", "kind", "scope", "requestId", "executionId", "beforeJournalHash", "inputPath",
    "inputSha256", "executionInputHash", "outputRoot", "clockHash", "generationStartedAt", "budgetAdmissionHash",
    "selectedGraphicOrders", "runtime"}
_RUNTIME_KEYS = {"dockerPath", "dockerSha256", "dockerSocketPath", "dockerSocketDevice", "dockerSocketInode",
    "imageId", "userId", "imageApprovalPath", "imageApprovalSha256", "runtimeRepoRoot"}


@dataclass(frozen=True)
class HeldOpeningClaim:
    """A server-provided claim reference captured before any media or registration."""

    path: Path
    sha256: str
    value: dict


def _canonical_path(value: object) -> Path:
    """Require exact POSIX spelling and no linked path components."""
    if type(value) is not str or not value.startswith("/") or "\\" in value \
            or any(ord(char) < 32 for char in value) or any(part in {"", ".", ".."} for part in value.split("/")[1:]):
        raise RuntimeError("opening claim path is not canonical")
    path = Path(value)
    if path.resolve(strict=True) != path:
        raise RuntimeError("opening claim path is linked")
    return path


def verify_claim_runtime(claim: HeldOpeningClaim, snapshot: str) -> None:
    """Bind actual same-daemon controls and the captured approved-image document."""
    verify_runtime_controls(claim.value["runtime"], snapshot)


def verify_runtime_controls(runtime: dict, snapshot: str) -> None:
    """Reuse exact Docker admission without inventing an opening execution claim."""
    runtime = closed(runtime, _RUNTIME_KEYS, "claim runtime")
    docker = _canonical_path(runtime["dockerPath"])
    socket = _canonical_path(runtime["dockerSocketPath"])
    _canonical_path(runtime["runtimeRepoRoot"])
    if file_hash(docker) != hash_value(runtime["dockerSha256"]) or not os.access(docker, os.X_OK):
        raise RuntimeError("opening claim Docker executable changed")
    info = socket.lstat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid() \
            or str(info.st_dev) != runtime["dockerSocketDevice"] or str(info.st_ino) != runtime["dockerSocketInode"]:
        raise RuntimeError("opening claim Docker socket identity changed")
    approval = _canonical_path(runtime["imageApprovalPath"])
    if approval != Path(snapshot) / "scripts/producer/headless/render_image_approval.json":
        raise RuntimeError("opening claim approval is outside the exact pinned pipeline")
    value = _json(approval, runtime["imageApprovalSha256"], 1024 * 1024)[0]
    if value.get("imageId") != runtime["imageId"]:
        raise RuntimeError("opening claim image differs from pinned approval")
    if type(runtime["imageId"]) is not str or not runtime["imageId"].startswith("sha256:"):
        raise RuntimeError("opening claim image is not an immutable digest")
    hash_value(runtime["imageId"][7:])
    parts = runtime["userId"].split(":") if type(runtime["userId"]) is str else []
    if len(parts) != 2 or any(not part.isdigit() or part.startswith("0") for part in parts):
        raise RuntimeError("opening claim requires a literal nonroot renderer user")


def _identity(value: dict, inputs: dict, context: tuple[Path, str, Path]) -> None:
    """Tie exact invocation, clock and derived output/request identity together."""
    input_path, input_sha, root = context
    if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1 \
            or value["kind"] != "guided-opening-execution-claim" \
            or value["scope"] != "private-opening-owned-execution-not-approval":
        raise RuntimeError("opening execution claim role is unsupported")
    for key in ("requestId", "executionId"):
        if type(value[key]) is not str or str(UUID(value[key])) != value[key]:
            raise RuntimeError("opening execution claim UUID is malformed")
    expected = {"inputPath": str(input_path), "inputSha256": input_sha, "outputRoot": str(root),
        "executionInputHash": inputs["executionInputHash"], "executionId": inputs["executionId"]}
    if any(value[key] != item for key, item in expected.items()):
        raise RuntimeError("opening claim is not this held execution/input/output")
    for key in ("beforeJournalHash", "inputSha256", "executionInputHash", "clockHash", "budgetAdmissionHash"):
        hash_value(value[key])
    orders = value["selectedGraphicOrders"]
    if type(orders) is not list or len(orders) > 8 or any(type(item) is not int or not 0 <= item < 128 for item in orders) \
            or orders != sorted(set(orders)):
        raise RuntimeError("opening claim selected graphic orders are not closed exact indices")


def read_execution_claim(paths: tuple[Path, Path], refs: tuple[str, Path, str]) -> HeldOpeningClaim:
    """Keep legacy current-runtime admission after the exact metadata identity read."""
    claim, snapshot = _claim_metadata(paths, refs)
    verify_claim_runtime(claim, snapshot)
    return claim


def read_execution_claim_metadata(paths: tuple[Path, Path], refs: tuple[str, Path, str]) -> HeldOpeningClaim:
    """Read original claim/document bindings without resurrecting retired runtime controls.

    Cold readers separately authenticate actual stopped-process/final-cleanup
    evidence. This metadata-only result grants no current runtime or ownership.
    """
    return _claim_metadata(paths, refs)[0]


def _claim_metadata(paths: tuple[Path, Path], refs: tuple[str, Path, str]) -> tuple[HeldOpeningClaim, str]:
    """Share the original single metadata read and retain its original runtime root."""
    input_path, root = paths
    input_sha, claim_path, claim_sha = refs
    _canonical_path(str(input_path))
    _canonical_path(str(root))
    _canonical_path(str(claim_path))
    inputs = _json(input_path, input_sha, 128 * 1024)[0]
    value = closed(_json(claim_path, claim_sha, 128 * 1024)[0], _KEYS, "execution claim")
    _identity(value, inputs, (input_path, input_sha, root))
    authority = _document(inputs["documents"]["authority"], 16 * 1024 * 1024)[0]
    bindings = _document(inputs["documents"]["frameBindings"], 16 * 1024 * 1024)[0]
    orders = sorted(row["order"] for row in bindings["graphics"] if row["startFrame"] < authority["review"]["endFrameExclusive"])
    if value["selectedGraphicOrders"] != orders or value["clockHash"] != authority["clockHash"] \
            or value["generationStartedAt"] != authority["generationStartedAt"]:
        raise RuntimeError("opening claim does not bind the exact source clock/selected graphic orders")
    return HeldOpeningClaim(claim_path, claim_sha, value), inputs["pipeline"]["snapshotRoot"]


def resource_request(claim: HeldOpeningClaim, order: int) -> ResourceRequest:
    """Derive one exact candidate-order ledger; never recursively discover targets."""
    if order not in claim.value["selectedGraphicOrders"]:
        raise RuntimeError("opening resource order is not claimed")
    runtime = claim.value["runtime"]
    root = Path(claim.value["outputRoot"]) / "graphics/attempts" / f"graphic-{order}"
    identity = f"opening-{claim.value['executionId']}-graphic-{order}"
    return ResourceRequest(str(root), identity, runtime["dockerPath"], runtime["dockerSocketPath"],
                           runtime["imageId"], runtime["userId"])


def registration_intent(claim: HeldOpeningClaim, order: int) -> dict:
    """A durable armed marker precedes existing ledger registration and spawn."""
    return {"schemaVersion": 1, "kind": "guided-opening-registration-intent", "claimSha256": claim.sha256,
        "inputSha256": claim.value["inputSha256"], "order": order,
        "attemptId": resource_request(claim, order).attempt_id, "runtimeHash": digest(claim.value["runtime"])}
