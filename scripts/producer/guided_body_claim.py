"""Body activation-bound renderer resources, never historical opening claims."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cut_preview_io import digest
from guided_body_contract import BodyInvocation, body_path
from guided_body_inputs import BodyControl, read_body_control_header
from guided_opening_claim import verify_runtime_controls
from headless.resource_ledger import ResourceRequest


@dataclass(frozen=True)
class BodyResourceClaim:
    """Externally held body invocation/activation, not source or success evidence."""

    invocation: BodyInvocation
    root: Path
    value: dict
    activation: dict


def read_body_resource_claim(invocation: BodyInvocation, root: Path) -> BodyResourceClaim:
    """No provenance dereference; known-resource absence is not local quiescence."""
    value, activation, _producer = read_body_control_header(invocation, root)
    approval = body_path(value["runtime"]["imageApprovalPath"])
    if approval.parts[-4:] != ("scripts", "producer", "headless", "render_image_approval.json"):
        raise RuntimeError("body cleanup approval is outside the exact pinned image-document role")
    verify_runtime_controls(value["runtime"], str(approval.parents[3]))
    return BodyResourceClaim(invocation, root, value, activation)


def body_resource_claim(control: BodyControl) -> BodyResourceClaim:
    """Project already revalidated body metadata; no kind/authority casting occurs."""
    return BodyResourceClaim(control.invocation, control.root, control.value, control.activation)


def body_resource_request(claim: BodyResourceClaim, order: int) -> ResourceRequest:
    """One exact candidate-order ledger and same-daemon controls, without discovery."""
    if type(order) is not int or order not in claim.value["selectedGraphicOrders"]:
        raise RuntimeError("body resource order is not claimed")
    runtime = claim.value["runtime"]
    root = claim.root / "graphics/attempts" / f"graphic-{order}"
    identity = f"body-{claim.value['executionId']}-graphic-{order}"
    return ResourceRequest(str(root), identity, runtime["dockerPath"], runtime["dockerSocketPath"],
                           runtime["imageId"], runtime["userId"])


def body_registration_intent(claim: BodyResourceClaim, order: int) -> dict:
    """Arm the exact before-spawn ledger using the separate executable activation."""
    return {"schemaVersion": 1, "kind": "guided-body-registration-intent",
        "activationSha256": claim.invocation.activation_sha256, "inputSha256": claim.invocation.input_sha256,
        "order": order, "attemptId": body_resource_request(claim, order).attempt_id,
        "runtimeHash": digest(claim.value["runtime"])}
