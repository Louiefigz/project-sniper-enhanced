"""Bind a sealed cut manifestation through mastering and final assembly."""
from __future__ import annotations

import os
from dataclasses import dataclass

from cut_manifestation_authority import (
    MANIFESTATION_NAME,
    _artifact,
    _digest,
    _read_object,
    _receipt_hash,
    _strict,
    verify_manifestation,
)
from fingerprint_io import file_sha256, write_json_atomic
from fingerprints import base_plan_digest, plan_content_hash

DELIVERY_NAME = "cut_delivery.v1.json"
_DELIVERY_KEYS = {
    "schemaVersion", "kind", "manifestationReceiptHash", "timelineMapSha256",
    "renderRole", "basePlanHash", "planHash", "renderArtifact",
    "finalArtifact", "assembledSidecarSha256", "receiptHash",
}
_ARTIFACT_KEYS = {"path", "sha256", "videoFrames"}


@dataclass(frozen=True)
class CutProof:
    """Verified cut-lineage facts returned to Audit B."""

    parts: int
    frames: int
    mode: str


@dataclass(frozen=True)
class RenderSeal:
    """Render-seal options; a bare bool keeps the historical graphics-free argument."""

    graphics_free: bool
    audio_clock_policy: str = "legacy-v1"


@dataclass(frozen=True)
class _DeliveryInputs:
    """Fields used to seal one downstream delivery lineage record."""

    manifestation: dict
    plan: dict
    role: str
    render_artifact: dict
    final_artifact: dict | None
    sidecar_hash: str | None
    audio_clock_policy: str = "legacy-v1"


def base_plan_lineage_digest(plan: dict, audio_clock_policy: str = "legacy-v1") -> str:
    """The base-shaping plan authority for one audio clock policy.

    Under source-float-v2, audio finishing (audioEnhance, audioGain and
    transitions[].sfx) is applied in the retained float program master, never in
    the base picture or its raw dialogue bus, so the lineage binds the
    finishing-free projection. Legacy bases bake finishing into their audio and
    keep the full graphics-free digest exactly as before.
    """
    if audio_clock_policy == "source-float-v2":
        from audio.program_finish_contract import finishing_free_plan
        return base_plan_digest(finishing_free_plan(plan))
    return base_plan_digest(plan)


def _lineage_digests(plan: dict) -> set[str]:
    """Digests a plan may legitimately be bound by: its own, or a v2 finishing-free seal."""
    return {base_plan_lineage_digest(plan), base_plan_lineage_digest(plan, "source-float-v2")}


def _delivery_record(inputs: _DeliveryInputs) -> dict:
    """Build and self-hash one strict downstream lineage record."""
    record = {
        "schemaVersion": 1, "kind": "cut-delivery-lineage-v1",
        "manifestationReceiptHash": inputs.manifestation["receiptHash"],
        "timelineMapSha256": inputs.manifestation["timelineMapSha256"],
        "renderRole": inputs.role,
        "basePlanHash": base_plan_lineage_digest(inputs.plan, inputs.audio_clock_policy),
        "planHash": (
            plan_content_hash(inputs.plan) if inputs.final_artifact else None),
        "renderArtifact": inputs.render_artifact,
        "finalArtifact": inputs.final_artifact,
        "assembledSidecarSha256": inputs.sidecar_hash,
    }
    record["receiptHash"] = _receipt_hash(record)
    return record


def seal_render_delivery(
    directory: str,
    final_path: str,
    plan: dict,
    graphics_free: bool | RenderSeal,
) -> dict:
    """Bind a completed master to its cut receipt before work is discarded."""
    options = graphics_free if isinstance(graphics_free, RenderSeal) else RenderSeal(graphics_free)
    manifestation = verify_manifestation(directory, plan)
    artifact = _artifact(final_path)
    role = "graphics-free-base" if options.graphics_free else "monolithic-final"
    final = None if options.graphics_free else artifact
    record = _delivery_record(_DeliveryInputs(
        manifestation, plan, role, artifact, final, None, options.audio_clock_policy))
    write_json_atomic(os.path.join(directory, DELIVERY_NAME), record, 2)
    return record


def seal_assembled_delivery(
    base_path: str,
    final_path: str,
    plan: dict,
    audio_clock_policy: str = "legacy-v1",
) -> dict | None:
    """Extend a base receipt through assemble; legacy bases remain unclaimed."""
    directory = os.path.dirname(os.path.abspath(final_path))
    manifestation_path = os.path.join(directory, MANIFESTATION_NAME)
    delivery_path = os.path.join(directory, DELIVERY_NAME)
    if not os.path.exists(manifestation_path) and not os.path.exists(delivery_path):
        return None
    manifestation = verify_manifestation(directory, plan)
    prior = _read_object(delivery_path, "base cut delivery receipt")
    _verify_delivery_record(prior)
    base = _artifact(base_path)
    bound = (
        prior["manifestationReceiptHash"] == manifestation["receiptHash"]
        and prior["timelineMapSha256"] == manifestation["timelineMapSha256"]
        and prior["basePlanHash"] == base_plan_lineage_digest(plan, audio_clock_policy)
    )
    if not bound \
            or prior["renderRole"] not in {
                "graphics-free-base", "assembled-final"} \
            or prior["renderArtifact"]["sha256"] != base["sha256"] \
            or prior["renderArtifact"]["videoFrames"] != base["videoFrames"]:
        raise ValueError("assembled base does not match its cut delivery receipt")
    final = _artifact(final_path)
    sidecar_path = final_path + ".assembled.json"
    _verify_assembled_sidecar(sidecar_path, final, plan)
    record = _delivery_record(_DeliveryInputs(
        manifestation, plan, "assembled-final", base, final,
        file_sha256(sidecar_path), audio_clock_policy))
    write_json_atomic(delivery_path, record, 2)
    return record


def _verify_delivery_record(record: dict) -> None:
    """Validate the strict delivery schema and its self-hash."""
    _strict(record, _DELIVERY_KEYS, "cut delivery receipt")
    if record["schemaVersion"] != 1 \
            or record["kind"] != "cut-delivery-lineage-v1":
        raise ValueError("cut delivery receipt version is unsupported")
    if _digest(record["receiptHash"], "cut delivery receipt hash") \
            != _receipt_hash(record):
        raise ValueError("cut delivery receipt hash is stale")
    for label in ("manifestationReceiptHash", "timelineMapSha256",
                  "basePlanHash"):
        _digest(record[label], label)


def _verify_artifact(record: object, current_path: str) -> dict:
    """Reobserve an artifact and require exact path/hash/frame equality."""
    if type(record) is not dict:
        raise ValueError("cut delivery artifact is malformed")
    _strict(record, _ARTIFACT_KEYS, "cut delivery artifact")
    observed = _artifact(current_path)
    if record != observed:
        raise ValueError("cut delivery artifact bytes or frames are stale")
    return observed


def _verify_assembled_sidecar(path: str, final: dict, plan: dict) -> None:
    """Require assembled authority for the exact final bytes and plan."""
    sidecar = _read_object(path, "assembled authority sidecar")
    if sidecar.get("authorityHash") != final["sha256"] \
            or sidecar.get("planHash") != plan_content_hash(plan):
        raise ValueError("assembled authority does not bind the final and plan")


def verify_delivered_cuts(directory: str, final_path: str, plan: dict) -> CutProof:
    """Fail-closed proof for cuts scene detection cannot see."""
    manifestation = verify_manifestation(directory, plan)
    record = _read_object(
        os.path.join(directory, DELIVERY_NAME), "cut delivery receipt")
    _verify_delivery_record(record)
    if record["manifestationReceiptHash"] != manifestation["receiptHash"] \
            or record["timelineMapSha256"] != manifestation["timelineMapSha256"]:
        raise ValueError("cut delivery receipt does not bind the manifestation")
    if record["basePlanHash"] not in _lineage_digests(plan):
        raise ValueError("cut delivery receipt does not bind the base plan")
    mode = record["renderRole"]
    final = _verify_final_delivery(record, final_path, plan, mode)
    frames = manifestation["concat"]["videoFrames"]
    if final["videoFrames"] != frames:
        raise ValueError("delivered frames do not equal the exact cut concat")
    return CutProof(len(manifestation["parts"]), frames, mode)


def _verify_final_delivery(
    record: dict,
    final_path: str,
    plan: dict,
    mode: str,
) -> dict:
    """Verify monolithic or assembled terminal links and return final facts."""
    final = _verify_artifact(record.get("finalArtifact"), final_path)
    if record["planHash"] != plan_content_hash(plan):
        raise ValueError("cut delivery receipt does not bind the final plan")
    if mode == "monolithic-final":
        if record["renderArtifact"] != final \
                or record["assembledSidecarSha256"] is not None:
            raise ValueError("monolithic cut delivery lineage is malformed")
        return final
    if mode != "assembled-final":
        raise ValueError("graphics-free base is not a delivered final")
    render = record.get("renderArtifact")
    if type(render) is not dict or set(render) != _ARTIFACT_KEYS:
        raise ValueError("assembled render artifact is malformed")
    _verify_artifact(render, render["path"])
    sidecar = final_path + ".assembled.json"
    if record["assembledSidecarSha256"] != file_sha256(sidecar):
        raise ValueError("assembled cut delivery sidecar is stale")
    _verify_assembled_sidecar(sidecar, final, plan)
    return final
