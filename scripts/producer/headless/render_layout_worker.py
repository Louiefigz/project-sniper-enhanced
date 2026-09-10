"""Explicit private observation worker; never a release/cache/approval authority."""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from fractions import Fraction

from color.deadline import require_time, wall_budget
from graphics.asset_proof import AssetProofRequest, prove_rendered_asset
from graphics.template_contract import validate_entry
from headless.container_io import SealedInput
from headless.container_renderer import RenderRequest, render_to
from headless.render_layout_contract import (
    MAX_RESULT_BYTES, POLICY, PIPELINE_POLICY, bounded_bytes, canonical, closed, finite_number,
    role_inventory, sealed_documents, sha, validate_request,
)
from headless.render_layout_result import validate_observation
from headless.render_layout_transport import approved_sources
from headless.container_policy import required_runtime
from headless.runtime_receipt import bind_runtime_receipt


@dataclass(frozen=True)
class LayoutJob:
    """Original caller expiry, owned output and independently held sealed input."""

    snapshot: SealedInput
    observation: dict
    output: str
    container_name: str
    deadline: float


def parse_worker_request(value: object) -> LayoutJob:
    """Capture one <=600s caller work deadline before any filesystem reads."""
    row = closed(value, {"schemaVersion", "operation", "snapshot", "observation",
                         "outputPath", "containerName", "expiresAtUnixMs"}, "layout worker")
    expires = finite_number(row["expiresAtUnixMs"])
    remaining = expires / 1000 - time.time()
    if not 0 < remaining <= 600:
        raise ValueError("layout worker original expiry is elapsed or beyond its ceiling")
    deadline = time.monotonic() + remaining
    observation = validate_request(row["observation"])
    operations = {POLICY: "observe-sealed-agenda-layout", PIPELINE_POLICY: "observe-sealed-pipeline-layout"}
    if type(row["schemaVersion"]) is not int or row["schemaVersion"] != 2 \
            or row["operation"] != operations[observation["profile"]]:
        raise ValueError("layout worker version/operation differs")
    snapshot = closed(row["snapshot"], {"path", "sha256", "manifest"}, "layout snapshot")
    sha(snapshot["sha256"])
    if type(snapshot["manifest"]) is not list:
        raise ValueError("layout sealed source manifest is missing")
    for name in (snapshot["path"], row["outputPath"]):
        if type(name) is not str or not os.path.isabs(name) or os.path.realpath(name) != name:
            raise ValueError("layout worker paths must be exact canonical paths")
    if type(row["containerName"]) is not str:
        raise ValueError("layout worker requires the caller-owned exact container name")
    sealed = SealedInput(snapshot["path"], snapshot["sha256"], tuple(snapshot["manifest"]))
    return LayoutJob(sealed, observation,
                     row["outputPath"], row["containerName"], deadline)


def _entry(job: LayoutJob, documents: dict[str, bytes]) -> dict:
    """Validate actual captured spec/template before any costly render admission."""
    rate = Fraction(job.observation["frameRate"])
    duration = float(job.observation["totalFrames"] / rate)
    html = documents["motion/" + job.observation["composition"]].decode("utf-8")
    entry = {"kind": os.path.basename(job.observation["composition"])[:-5], "anchor": "own-screen", "outStart": 0,
             "outEnd": duration, "spec": json.loads(documents["request/variables.json"])}
    validate_entry(entry, html)
    role_inventory(documents, job.observation["profile"])
    return entry


def _prove(job: LayoutJob, documents: dict[str, bytes], entry: dict) -> dict:
    """Reuse the existing real decode/copy/format proof; no new media renderer."""
    rate = Fraction(job.observation["frameRate"])
    duration = float(job.observation["totalFrames"] / rate)
    html = documents["motion/" + job.observation["composition"]].decode("utf-8")
    request = AssetProofRequest(job.output, entry, "mp4", (1920, 1080), duration,
                                hashlib.sha256(canonical(job.observation)).hexdigest(),
                                float(rate), html, sealed_asset_inputs=())
    with wall_budget(job.deadline):
        proof = prove_rendered_asset(request)
        proof = bind_runtime_receipt(job.output, proof)
    return proof


def execute(value: object) -> dict:
    """Run only an explicit private sealed observation, preserving default v1."""
    job = parse_worker_request(value)
    with wall_budget(job.deadline):
        documents = sealed_documents(job.snapshot, job.observation)
        entry = _entry(job, documents)
        runtime = required_runtime()
        sources = approved_sources(runtime)
    request = RenderRequest(job.observation["composition"], "mp4", job.output,
                            job.snapshot, job.container_name, job.observation["frameRate"],
                            job.observation, job.deadline)
    render_to(request)  # Own work timer disarmed before exact container cleanup.
    proof = _prove(job, documents, entry)
    with wall_budget(job.deadline):
        raw = bounded_bytes(job.output + ".layout.json", MAX_RESULT_BYTES)
        observed = validate_observation(json.loads(raw), job.observation, {
            "observerSources": sources, "roleInventory": role_inventory(documents, job.observation["profile"]),
            "media": {"sha256": proof["asset"]["sha256"],
                                                  "sizeBytes": proof["asset"]["sizeBytes"]}})
        if approved_sources(runtime) != sources:
            raise ValueError("layout observer source closure changed after proof")
        sealed_documents(job.snapshot, job.observation)
        proof_raw = bounded_bytes(job.output + ".proof.json", 4 * 1024 * 1024)
        if bounded_bytes(job.output + ".layout.json", MAX_RESULT_BYTES) != raw:
            raise ValueError("actual layout bytes changed at final proof boundary")
        require_time(job.deadline)
    return {"schemaVersion": 2, "kind": "sealed-layout-render-result",
            "scope": "private-observation-not-release-or-caption-legibility-approval",
            "requestSha256": hashlib.sha256(canonical(job.observation)).hexdigest(),
            "path": job.output, "mediaSha256": proof["asset"]["sha256"],
            "observation": {"path": job.output + ".layout.json",
                            "sha256": hashlib.sha256(raw).hexdigest()},
            "proof": {"path": job.output + ".proof.json",
                      "sha256": hashlib.sha256(proof_raw).hexdigest()},
            "status": observed["status"], "qcPassed": False,
            "creativeApproved": False, "deliveryApproved": False}
