"""Approved Sniper final authority and delivery-media facts for Palmier mirror."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime

from fingerprints import file_sha256
from ingest_probe import probe_media
from palmier.mcp_client import PalmierError
from palmier.quality_evidence import validate_approval
from palmier.quality_hash import authority_snapshot, request_key
from template_usage_approval import approval_required as template_approval_required

APPROVAL_NAME = ".sniper-qc-approved.json"
JOB_NAME = ".sniper-auto-edit-job.json"
POLICY_NAME = ".sniper-quality-policy.json"
PREVIEW_STALE_NAME = ".sniper-preview-stale.json"
_SHA = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class MasterFacts:
    """Hash-bound delivery facts derived from the approved final, not raw media."""

    path: str
    content_hash: str
    duration_s: float
    fps: float
    width: int
    height: int
    end_frame: int


def _json(path: str, label: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PalmierError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PalmierError(f"{label} {path} is not a JSON object")
    return value


def _timestamp(value: object, label: str) -> None:
    if not isinstance(value, str):
        raise PalmierError(f"{label} is not a timestamp")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PalmierError(f"{label} is not a timestamp") from exc


def _managed_context(out_dir: str, marker: dict, plan_path: str,
                     manifest_path: str) -> dict:
    ctx = marker.get("ctx")
    required = ("dir", "scope", "planPath", "manifestPath", "transcriptsDir")
    valid = isinstance(ctx, dict) and all(
        isinstance(ctx.get(key), str) and ctx[key] for key in required)
    if not valid or marker.get("qualityPolicyVersion") != 1:
        raise PalmierError("managed quality-policy marker is malformed")
    assert isinstance(ctx, dict)
    paths = (ctx["dir"], ctx["planPath"], ctx["manifestPath"],
             ctx["transcriptsDir"])
    if not all(os.path.isabs(path) for path in paths):
        raise PalmierError("managed quality-policy paths must be absolute")
    expected = (os.path.abspath(out_dir), os.path.abspath(plan_path),
                os.path.abspath(manifest_path))
    actual = (os.path.abspath(ctx["dir"]), os.path.abspath(ctx["planPath"]),
              os.path.abspath(ctx["manifestPath"]))
    if actual != expected or ctx["scope"] not in ("trim", "light", "produced", "full"):
        raise PalmierError("managed quality-policy context does not match this project")
    digest = marker.get("requestKey")
    if not isinstance(digest, str) or not _SHA.fullmatch(digest) \
            or request_key(ctx) != digest:
        raise PalmierError("managed quality-policy request key is invalid")
    _timestamp(marker.get("activatedAt"), "managed quality-policy activatedAt")
    return ctx


def _policy(out_dir: str, plan_path: str,
            manifest_path: str) -> tuple[str, dict | None]:
    marker = _json(os.path.join(out_dir, POLICY_NAME), "quality-policy marker")
    if marker.get("schemaVersion") != 1:
        raise PalmierError("quality-policy marker has an unsupported schema")
    if marker.get("mode") == "legacy":
        _timestamp(marker.get("migratedAt"), "legacy quality-policy migratedAt")
        if not isinstance(marker.get("reason"), str) or not marker["reason"].strip():
            raise PalmierError("legacy quality-policy marker requires a reason")
        return "legacy", None
    if marker.get("mode") != "managed":
        raise PalmierError("quality-policy marker mode is invalid")
    return "managed", _managed_context(out_dir, marker, plan_path, manifest_path)


def _job(out_dir: str, marker_ctx: dict, approval: dict,
         authority: dict) -> None:
    job = _json(os.path.join(out_dir, JOB_NAME), "Auto Edit job")
    required = approval["planningRoundsRequired"]
    expected = {
        "version": 1, "qualityPolicyVersion": 1, "status": "complete",
        "checkpoint": "complete", "requestKey": request_key(marker_ctx),
        "ctx": marker_ctx, "planHash": approval["planHash"],
        "planningCleanPlanHash": approval["planHash"],
        "reviewedPlanHash": approval["planHash"],
        "renderedPlanHash": approval["planHash"],
        "manifestHash": approval["manifestHash"],
        "renderedManifestHash": approval["manifestHash"],
        "authorityDigest": authority["digest"],
        "planningCleanAuthorityDigest": authority["digest"],
        "reviewedAuthorityDigest": authority["digest"],
        "renderedAuthorityDigest": authority["digest"],
        "planningRoundsRequired": required, "qcRound": approval["qcRound"],
        "candidateHash": approval["finalHash"], "finalHash": approval["finalHash"],
        "unresolvedFindingIds": [],
    }
    mismatch = next((key for key, value in expected.items()
                     if job.get(key) != value), None)
    clean = job.get("planningCleanRounds")
    rounds = job.get("planningRound")
    if mismatch or isinstance(clean, bool) or not isinstance(clean, int) or clean < required \
            or isinstance(rounds, bool) or not isinstance(rounds, int) or rounds < required:
        detail = mismatch or "planning review counts"
        raise PalmierError(f"Auto Edit job is not coherent with QC approval: {detail}")


def _managed_approval(out_dir: str, ctx: dict, final_path: str) -> None:
    approval = _json(os.path.join(out_dir, APPROVAL_NAME), "Auto Edit QC approval")
    try:
        authority = authority_snapshot(ctx)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise PalmierError(f"cannot recompute managed quality authority: {exc}") from exc
    validate_approval(out_dir, final_path, approval, authority)
    _job(out_dir, ctx, approval, authority)


def authority_hash(out_dir: str, plan_hash: str) -> str:
    """Prove final.mp4 was assembled from this plan and remains unchanged."""
    final = os.path.join(out_dir, "final.mp4")
    if not os.path.isfile(final):
        raise PalmierError(f"missing Sniper visual master {final} — render first")
    proof = _json(final + ".assembled.json", "final render provenance")
    if proof.get("planHash") != plan_hash:
        raise PalmierError(
            "Sniper final is stale or unproven for the current plan")
    actual = file_sha256(final)
    if proof.get("authorityHash") != actual:
        raise PalmierError(
            "Sniper final changed after its provenance checkpoint")
    return actual


def approved_master(out_dir: str, plan_path: str, manifest_path: str,
                    plan_hash: str) -> MasterFacts:
    """Return current approved final facts or fail closed on any stale proof."""
    final = os.path.join(out_dir, "final.mp4")
    if not os.path.isfile(final):
        raise PalmierError(f"missing approved Sniper visual master {final}")
    if os.path.exists(os.path.join(out_dir, PREVIEW_STALE_NAME)):
        raise PalmierError(
            "Sniper preview authority was invalidated by a newer edit request")
    actual = authority_hash(out_dir, plan_hash)
    mode, ctx = _policy(out_dir, plan_path, manifest_path)
    if mode == "managed":
        _managed_approval(out_dir, ctx or {}, final)
    elif template_approval_required(out_dir):
        raise PalmierError(
            "legacy produced/full edits must run governed saved-plan review before Palmier delivery")
    try:
        probe = probe_media(final)
    except (OSError, RuntimeError, ValueError) as exc:
        raise PalmierError(f"cannot probe approved visual master: {exc}") from exc
    facts = (probe.duration, probe.fps, probe.width, probe.height)
    if any(value is None for value in facts) or probe.vfr:
        raise PalmierError(
            "approved visual master requires CFR video with duration, fps, and canvas")
    project_fps = round(float(probe.fps))
    end_frame = round(float(probe.duration) * project_fps)
    if project_fps <= 0 or end_frame <= 0:
        raise PalmierError("approved visual master resolves to no timeline frames")
    return MasterFacts(final, actual, float(probe.duration), float(probe.fps),
                       int(probe.width), int(probe.height), end_frame)
