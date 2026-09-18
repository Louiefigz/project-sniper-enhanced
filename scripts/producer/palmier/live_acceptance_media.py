"""Exact media and managed-QC preflight for live Palmier acceptance."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from cut_delivery_authority import DELIVERY_NAME
from fingerprints import file_sha256, plan_content_hash
from ingest_execution_authority import verify_execution_media_authority
from ingest_probe import probe_media
from media_probe import probe_video_frames
from palmier.live_acceptance_cadence import verify_longform_cadence
from palmier.desktop_repair import validate_one_graphic_repair
from palmier.master import (
    APPROVAL_NAME, JOB_NAME, POLICY_NAME, approved_master,
)
from palmier.mcp_client import PalmierError
from palmier_visual_bootstrap_authority import \
    verify_palmier_visual_bootstrap


def _object(path: str, label: str) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PalmierError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise PalmierError(f"{label} is not a JSON object")
    return value


def plan_rounded_frames(plan: dict, fps: int) -> int:
    """Return float-plan rounding only as diagnostic, never authority."""
    rows = plan.get("cutTrack")
    if not isinstance(rows, list) or not rows \
            or any(not isinstance(row, dict) for row in rows):
        raise PalmierError("live acceptance plan has no valid cutTrack")
    try:
        duration = sum((float(row["end"]) - float(row["start"]))
                       / float(row.get("speed", 1.0) or 1.0)
                       for row in rows)
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise PalmierError("live acceptance cutTrack is malformed") from exc
    frames = round(duration * fps)
    if frames <= 0:
        raise PalmierError("live acceptance plan resolves to zero frames")
    return frames


def _renderer_audit(out_dir: str) -> dict:
    """Require the renderer's own deterministic audit to be non-failing."""
    path = os.path.join(out_dir, "audit_report.json")
    if not os.path.isfile(path) or os.path.islink(path):
        raise PalmierError(
            "live acceptance out dir has no regular renderer audit report")
    report = _object(path, "renderer audit report")
    checks = report.get("checks")
    passing = (
        report.get("overall") in {"pass", "warn"}
        and report.get("exitCode") == 0
        and isinstance(checks, list)
        and bool(checks)
        and not any(isinstance(row, dict) and row.get("status") == "fail"
                    for row in checks)
    )
    if not passing:
        raise PalmierError(
            "live acceptance renderer audit is not passing")
    return {
        "path": path, "overall": report["overall"],
        "exitCode": report["exitCode"],
    }


def _managed_markers(out_dir: str) -> dict:
    """Require this release cohort to use real managed Auto Edit authority."""
    names = (POLICY_NAME, APPROVAL_NAME, JOB_NAME)
    paths = {name: os.path.join(out_dir, name) for name in names}
    if any(not os.path.isfile(path) or os.path.islink(path)
           for path in paths.values()):
        raise PalmierError(
            "live acceptance requires regular managed Auto Edit markers")
    policy = _object(paths[POLICY_NAME], "quality-policy marker")
    if policy.get("schemaVersion") != 1 or policy.get("mode") != "managed":
        raise PalmierError(
            "live acceptance requires managed quality-policy authority")
    return {
        name: {"path": path, "sha256": file_sha256(path)}
        for name, path in paths.items()
    }


def _approved_target(config: Any, paths: dict,
                     plan: dict, canvas: tuple[int, int]) -> Any:
    delivery = os.path.join(config.out_dir, DELIVERY_NAME)
    if not os.path.isfile(delivery) or os.path.islink(delivery):
        raise PalmierError(
            f"cut delivery authority is not a regular file: {delivery}")
    master = approved_master(
        config.out_dir, paths["plan"], paths["manifest"],
        plan_content_hash(plan))
    actual = (master.frame_rate, master.width, master.height)
    expected = (f"{config.fps}/1", *canvas)
    if actual != expected or master.end_frame <= 0:
        raise PalmierError(
            f"approved master facts {actual}, frames={master.end_frame} "
            f"!= {expected}")
    return master


def _validate_bootstrap(config: Any, canvas: tuple[int, int],
                        frames: int, paths: dict) -> dict:
    path = paths["bootstrap"]
    try:
        receipt = verify_palmier_visual_bootstrap(
            config.out_dir, paths["plan"], paths["manifest"], path)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise PalmierError(
            f"bootstrap production authority is invalid: {exc}") from exc
    try:
        probe = probe_media(path)
        exact_frames = probe_video_frames(path)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise PalmierError(
            f"cannot probe live acceptance bootstrap: {exc}") from exc
    actual = (probe.frame_rate, probe.width, probe.height)
    expected = (f"{config.fps}/1", *canvas)
    if probe.vfr or probe.rotation != 0 or actual != expected \
            or exact_frames != frames:
        raise PalmierError(
            f"bootstrap facts {actual}, frames={exact_frames}, "
            f"vfr={probe.vfr}, rotation={probe.rotation} != "
            f"{expected}, frames={frames}")
    if probe.audio_present is not True:
        raise PalmierError("live acceptance bootstrap has no audio")
    return {
        "receiptHash": receipt["receiptHash"],
        "artifact": receipt["bootstrapArtifact"],
        "negativeDeclaration": receipt["negativeDeclaration"],
    }


def validate_media_authority(config: Any, paths: dict,
                             canvas: tuple[int, int]) -> dict:
    """Bind exact cut/final/bootstrap frames and real managed-QC authority."""
    plan = _object(paths["plan"], "edit plan")
    repair = _object(paths["repairPlan"], "repair plan")
    manifest = _object(paths["manifest"], "asset manifest")
    if plan.get("cutTrack") != repair.get("cutTrack"):
        raise PalmierError("repair plan changes the exact cutTrack")
    repair_target = validate_one_graphic_repair(plan, repair)
    if verify_execution_media_authority(
            plan, manifest, paths["manifest"]) is not True:
        raise PalmierError(
            "live acceptance media lacks admitted source-set authority")
    cadence = verify_longform_cadence(
        config, paths, plan, manifest)
    rounded = plan_rounded_frames(plan, config.fps)
    managed_markers = _managed_markers(config.out_dir)
    renderer_audit = _renderer_audit(config.out_dir)
    master = _approved_target(config, paths, plan, canvas)
    bootstrap = _validate_bootstrap(
        config, canvas, master.end_frame, paths)
    return {
        "targetFrames": master.end_frame, "planRoundedFrames": rounded,
        "roundingDeltaFrames": rounded - master.end_frame,
        "repairTargetId": repair_target,
        "approvedMaster": {
            "path": master.path, "sha256": master.content_hash,
            "frames": master.end_frame, "frameRate": master.frame_rate,
        },
        "bootstrapAuthority": bootstrap,
        "managedAutoEditAuthority": managed_markers,
        "rendererAudit": renderer_audit,
        "cadenceAuthority": cadence,
    }


def revalidate_bootstrap(config: Any, preflight: dict) -> dict:
    """Reobserve the exact bootstrap immediately around import_media."""
    paths = preflight["paths"]
    plan = _object(paths["plan"], "edit plan")
    manifest = _object(paths["manifest"], "asset manifest")
    markers = _managed_markers(config.out_dir)
    if markers != preflight.get("managedAutoEditAuthority"):
        raise PalmierError(
            "managed Auto Edit authority changed during acceptance")
    cadence = verify_longform_cadence(
        config, paths, plan, manifest)
    if cadence != preflight.get("cadenceAuthority"):
        raise PalmierError(
            "long cadence authority changed during connected acceptance")
    try:
        receipt = verify_palmier_visual_bootstrap(
            config.out_dir, paths["plan"], paths["manifest"],
            paths["bootstrap"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise PalmierError(
            f"bootstrap drifted during connected acceptance: {exc}") from exc
    expected = preflight.get("bootstrapAuthority") or {}
    actual = {
        "receiptHash": receipt["receiptHash"],
        "artifact": receipt["bootstrapArtifact"],
        "negativeDeclaration": receipt["negativeDeclaration"],
    }
    if actual != expected:
        raise PalmierError(
            "bootstrap production authority changed during acceptance")
    return {
        **actual, "cadenceAuthority": cadence,
        "managedAutoEditAuthority": markers,
    }
