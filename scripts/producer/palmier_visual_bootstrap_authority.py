"""Seal and verify the graphics-free editable Palmier visual bootstrap."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from captions.caption_fingerprints import canonical_digest
from cut_manifestation_authority import verify_manifestation
from fingerprints import (
    base_plan_digest, file_sha256, fingerprint_record, plan_content_hash,
    write_json_atomic,
)
from ingest_probe import probe_media
from media_probe import probe_video_frames
from palmier.process_deadline import process_timeout

BOOTSTRAP_AUTHORITY_NAME = "palmier_visual_bootstrap.v1.json"


def _regular(path: str, label: str) -> str:
    absolute = os.path.abspath(path)
    if os.path.islink(absolute) or not os.path.isfile(absolute):
        raise ValueError(f"{label} is not a regular file: {absolute}")
    return absolute


def _stat(path: str) -> dict:
    value = os.stat(path, follow_symlinks=False)
    return {
        "device": value.st_dev, "inode": value.st_ino,
        "size": value.st_size, "mtimeNs": value.st_mtime_ns,
    }


def _artifact(path: str) -> dict:
    absolute = _regular(path, "bootstrap artifact")
    return {
        "path": absolute, "sha256": file_sha256(absolute),
        "statSignature": _stat(absolute),
        "videoFrames": probe_video_frames(absolute),
    }


def _tool(name: str) -> dict:
    path = shutil.which(name)
    if not path:
        raise ValueError(f"bootstrap authority cannot resolve {name}")
    resolved = os.path.realpath(path)
    return {"path": resolved, "sha256": file_sha256(resolved)}


def _code_closure() -> list[dict]:
    root = os.path.dirname(os.path.abspath(__file__))
    names = [
        "render.py", "cut_speed.py", "cut_reframe.py", "cut_encode_plan.py", "cut_decode.py",
        "cut_execution.py", "cut_manifestation_authority.py",
        "audio/master.py", "motion/baseline_look.py",
        "motion/face_track.py", "motion/reframe.py",
        "motion/reframe_split.py",
    ]
    return [{"path": os.path.join(root, name),
             "sha256": file_sha256(os.path.join(root, name))}
            for name in names]


def _media(path: str) -> dict:
    value = probe_media(path)
    facts = {
        "frameRate": value.frame_rate, "width": value.width,
        "height": value.height, "vfr": value.vfr,
        "rotation": value.rotation, "audioPresent": value.audio_present,
        "audioChannels": value.audio_channels,
        "audioSampleRate": value.audio_sample_rate,
    }
    required = (
        isinstance(facts["frameRate"], str)
        and isinstance(facts["width"], int)
        and isinstance(facts["height"], int)
        and facts["vfr"] is False and facts["rotation"] == 0
        and facts["audioPresent"] is True)
    if not required:
        raise ValueError(f"bootstrap media facts are unsafe: {facts}")
    return facts


def _sample_hashes(path: str, frames: int) -> dict:
    indexes = sorted({0, max(0, frames // 2), max(0, frames - 1)})
    expression = "+".join(f"eq(n\\,{index})" for index in indexes)
    process = subprocess.run([
        "ffmpeg", "-v", "error", "-i", path,
        "-vf", f"select='{expression}'", "-vsync", "0",
        "-an", "-f", "framemd5", "-",
    ], capture_output=True, text=True, timeout=process_timeout())
    rows = [line.strip() for line in process.stdout.splitlines()
            if line.strip() and not line.startswith("#")]
    if process.returncode or len(rows) != len(indexes):
        raise ValueError("bootstrap decoded sample proof failed")
    return {"frameIndexes": indexes, "frameMd5Rows": rows}


def _validate_trace(trace: list[dict]) -> list[dict]:
    if [row.get("stage") for row in trace] != [
            "audio_channels", "baseline_look", "reframe"]:
        raise ValueError("bootstrap stage trace is incomplete or out of order")
    if any(row.get("status") == "resume-skipped" for row in trace):
        raise ValueError(
            "cannot mint bootstrap authority from resume-skipped stages")
    return trace


def _input(path: str, label: str) -> dict:
    absolute = _regular(path, label)
    return {"path": absolute, "sha256": file_sha256(absolute)}


def seal_palmier_visual_bootstrap(
        ctx: object, cut_mezzanine: str,
        output: str) -> dict:
    """Seal freshly observed cut→channel→baseline→reframe production output."""
    if not isinstance(ctx.plan_path, str):
        raise ValueError("bootstrap authority has no source plan path")
    manifest_path = ctx.manifest.get("_path")
    if not isinstance(manifest_path, str):
        raise ValueError("bootstrap authority has no source manifest path")
    manifestation = verify_manifestation(ctx.out_dir, ctx.plan)
    cut = _artifact(cut_mezzanine)
    artifact = _artifact(output)
    frames = manifestation["concat"]["videoFrames"]
    if cut["videoFrames"] != frames or artifact["videoFrames"] != frames \
            or cut["sha256"] != manifestation["concat"]["sha256"]:
        raise ValueError("bootstrap does not preserve the sealed cut frames")
    trace = _validate_trace(list(ctx.bootstrap_trace))
    payload = {
        "schemaVersion": 1, "kind": "palmier-visual-bootstrap-authority",
        "plan": _input(ctx.plan_path, "bootstrap plan"),
        "manifest": _input(manifest_path, "bootstrap manifest"),
        "planContentHash": plan_content_hash(ctx.plan),
        "basePlanHash": base_plan_digest(ctx.plan),
        "fingerprints": fingerprint_record(ctx.plan),
        "manifestationReceiptHash": manifestation["receiptHash"],
        "timelineMapSha256": manifestation["timelineMapSha256"],
        "cutArtifact": cut, "bootstrapArtifact": artifact,
        "mediaFacts": _media(output),
        "decodedSamples": _sample_hashes(output, frames),
        "stageTrace": trace,
        "tools": {"ffmpeg": _tool("ffmpeg"), "ffprobe": _tool("ffprobe")},
        "codeClosure": _code_closure(),
        "negativeDeclaration": {
            "stageBoundary": "after-reframe-before-recompose-punch-broll-title-graphics-captions",
            "containsTitleCards": False, "containsGraphics": False,
            "containsCaptions": False, "containsBroll": False,
        },
    }
    receipt = {**payload, "receiptHash": canonical_digest(
        "sniper-palmier-visual-bootstrap-v1", payload)}
    path = os.path.join(ctx.out_dir, BOOTSTRAP_AUTHORITY_NAME)
    write_json_atomic(path, receipt, indent=2)
    return receipt


def _read(path: str) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"bootstrap authority is unreadable: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("bootstrap authority is malformed")
    return value


def verify_palmier_visual_bootstrap(
        out_dir: str, plan_path: str,
        manifest_path: str, bootstrap_path: str) -> dict:
    """Reobserve all mutable bootstrap inputs and exact media facts."""
    receipt_path = os.path.join(out_dir, BOOTSTRAP_AUTHORITY_NAME)
    receipt = _read(receipt_path)
    payload = {key: value for key, value in receipt.items()
               if key != "receiptHash"}
    expected = canonical_digest(
        "sniper-palmier-visual-bootstrap-v1", payload)
    if receipt.get("receiptHash") != expected:
        raise ValueError("bootstrap authority self-hash is stale")
    plan = _read(plan_path)
    manifestation = verify_manifestation(out_dir, plan)
    cut_receipt = receipt.get("cutArtifact")
    cut_path = cut_receipt.get("path") \
        if isinstance(cut_receipt, dict) else None
    checks = (
        receipt.get("plan") == _input(plan_path, "bootstrap plan"),
        receipt.get("manifest") == _input(
            manifest_path, "bootstrap manifest"),
        receipt.get("planContentHash") == plan_content_hash(plan),
        receipt.get("basePlanHash") == base_plan_digest(plan),
        receipt.get("fingerprints") == fingerprint_record(plan),
        receipt.get("manifestationReceiptHash")
        == manifestation["receiptHash"],
        receipt.get("timelineMapSha256")
        == manifestation["timelineMapSha256"],
        receipt.get("bootstrapArtifact") == _artifact(bootstrap_path),
        isinstance(cut_path, str)
        and receipt.get("cutArtifact") == _artifact(cut_path),
        receipt.get("tools")
        == {"ffmpeg": _tool("ffmpeg"), "ffprobe": _tool("ffprobe")},
        receipt.get("codeClosure") == _code_closure(),
    )
    if not all(checks):
        raise ValueError("bootstrap authority inputs or artifact drifted")
    artifact = receipt["bootstrapArtifact"]
    if receipt.get("mediaFacts") != _media(bootstrap_path) \
            or receipt.get("decodedSamples") != _sample_hashes(
                bootstrap_path, artifact["videoFrames"]):
        raise ValueError("bootstrap decoded media facts drifted")
    if receipt.get("negativeDeclaration") != {
            "stageBoundary": "after-reframe-before-recompose-punch-broll-title-graphics-captions",
            "containsTitleCards": False, "containsGraphics": False,
            "containsCaptions": False, "containsBroll": False}:
        raise ValueError("bootstrap negative declaration is malformed")
    _validate_trace(receipt.get("stageTrace") or [])
    return receipt
