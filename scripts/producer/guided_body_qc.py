"""Hold actual whole Audit B coverage and candidate support through final read.

This checks the existing restricted-profile report vocabulary and uses its
existing frame planner/text-role declarations. It does not rerun or replace
pixel/audio checks, manufacture passing rows, or grant subjective approval.
"""
from __future__ import annotations

import os
from fractions import Fraction
from pathlib import Path

from audit.audit_frames import plan_frames, TIMESTAMP_PRECISION
from audit.audit_motion import _is_produced
from compile_timeline import TimelineMap
from cut_delivery_authority import DELIVERY_NAME
from cut_manifestation_authority import MANIFESTATION_NAME
from cut_preview_io import bound_json, digest, file_hash
from graphics.template_text_contrast import effective_text_roles, text_plate_contract, text_treatment
from guided_opening_inputs import closed
from guided_opening_result import held_ref

_BASE_CHECKS = frozenset({"duration", "audio_decode_complete", "loudness_integrated", "loudness_true_peak",
    "format_resolution", "format_vcodec", "format_profile", "format_pix_fmt", "format_cfr", "format_faststart",
    "format_acodec", "format_arate", "format_achannels", "audio_av_timing", "audio_channel_balance",
    "audio_tonal_hum", "audio_ending_mix", "file_budget", "cover", "glitch_black", "glitch_freeze", "glitch_flash",
    "review_frames_extracted", "final_identity"})
_REQUIRED_SUPPORT = (DELIVERY_NAME, MANIFESTATION_NAME, "timeline_map.json", "cover.png",
                     "final.mp4.assembled.json", "program_audio.v2.json")
_OPTIONAL_SUPPORT = ("graphics_placements.json", "geometry_predictions.json", "caption_authority.json",
    "caption_compilation.json", "caption_shards.json", "caption_palmier.json", "caption_chapters.json",
    "captions.ass", "captions.srt", "chapters.txt", ".caption-free-composite.mp4", ".caption-free-composite.json")


def artifact_reference(path: Path) -> dict:
    """Same regular-file bytes, not a self-authenticating approval reference."""
    return {"path": str(path), "sha256": file_hash(path), "sizeBytes": path.stat().st_size}


def _graphic_checks(plan: dict) -> set[str]:
    """Match own-screen contrast roles; the ordinary accent heuristic skips these."""
    result = set()
    for index, graphic in enumerate(plan.get("graphicsTrack") or []):
        prefix = f"graphic_composite_{index}"
        result.add(prefix + "_presence")
        contract = text_plate_contract(str(graphic.get("kind", "")))
        if contract is not None and text_treatment(graphic, contract) == "plates":
            result.update(prefix + "_contrast_" + role["id"] for role in effective_text_roles(graphic, contract))
            continue
        if contract is not None:
            result.add(prefix + "_contrast")
    if plan.get("graphicsTrack"):
        result.add("graphic_composite_reference")
        if _is_produced(plan):
            result.add("eye_trace")
    return result


def check_audit_coverage(report: dict, plan: dict, horizon: float) -> None:
    """Full required rows and planned frame phases, without any new media work."""
    checks, frames = report["checks"], report["frames"]
    if type(checks) is not list or not 1 <= len(checks) <= 4096 \
            or type(frames) is not list or not 1 <= len(frames) <= 1024:
        raise RuntimeError("body whole QC has missing or unbounded evidence")
    for row in checks:
        closed(row, {"name", "status", "measured", "detail"}, "body Audit B check")
        if any(type(row[key]) is not str for key in row) or row["status"] not in {"pass", "warn"}:
            raise RuntimeError("body Audit B has failed or malformed checks")
    required = set(_BASE_CHECKS) | _graphic_checks(plan)
    if type(plan.get("captionsTrack")) is dict:
        required.add("caption_authority")
    if _is_produced(plan):
        required.add("motion_pacing")
    names = [row["name"] for row in checks]
    if not required.issubset(names) or any(names.count(name) != 1 for name in required - {"eye_trace"}):
        raise RuntimeError("body whole Audit B required check coverage is incomplete or duplicated")
    counts = {status: sum(row["status"] == status for row in checks) for status in ("pass", "warn", "fail")}
    if digest(report["counts"]) != digest(counts) or report["overall"] != ("warn" if counts["warn"] else "pass"):
        raise RuntimeError("body whole Audit B counts/verdict differ from actual rows")
    expected = plan_frames(plan, horizon)
    if len(frames) != len(expected):
        raise RuntimeError("body whole Audit B frame coverage is incomplete")
    for actual, frame in zip(frames, expected):
        closed(actual, {"label", "kind", "timestamp", "path", "note"}, "body Audit B frame")
        if actual["label"] != frame.label or actual["kind"] != frame.kind or actual["note"] != frame.note \
                or type(actual["timestamp"]) not in (int, float) \
                or not abs(actual["timestamp"] - frame.timestamp) <= 10 ** -TIMESTAMP_PRECISION + 1e-9:
            raise RuntimeError("body whole Audit B frame phase differs from existing planner")


def observe_body_qc(root: Path, final: dict, plan: dict) -> dict:
    """Bind actual complete report, every planned retained frame and support bytes."""
    candidate = root / "body-candidate"
    path = candidate / "audit_report.json"
    reference = artifact_reference(path)
    report = bound_json(path, reference["sha256"])
    if report["final"] != final["path"] or report["outDir"] != str(candidate) \
            or report["finalSha256"] != final["sha256"] or type(report["exitCode"]) is not int \
            or report["exitCode"] != 0 or report["overall"] not in {"pass", "warn"} \
            or report["mode"] != plan["target"]["mode"]:
        raise RuntimeError("body whole Audit B does not bind the exact complete candidate")
    duration = TimelineMap.from_dict(bound_json(candidate / "timeline_map.json")).output_duration
    horizon = min(duration, float(Fraction(final["frames"], 1) / Fraction(final["frameRate"])))
    check_audit_coverage(report, plan, horizon)
    references = []
    for frame in report["frames"]:
        frame_path = Path(frame["path"])
        if not frame_path.is_absolute() or not frame_path.is_relative_to(candidate):
            raise RuntimeError("body review frame is outside actual private QC evidence")
        references.append({"label": frame["label"], "timestamp": frame["timestamp"], **artifact_reference(frame_path)})
    held_ref(reference, root)
    return {**reference, "overall": report["overall"], "exitCode": 0, "finalSha256": final["sha256"],
        "frames": references, "scope": "actual-full-Audit-B-not-creative-or-subjective-listening-approval"}


def observe_body_support(root: Path, plan: dict, composition: dict) -> list[dict]:
    """Keep exact fixed candidate support, including absence of optional artifacts."""
    candidate, result = root / "body-candidate", []
    for name in (*_REQUIRED_SUPPORT, *_OPTIONAL_SUPPORT):
        path = candidate / name
        required = name in _REQUIRED_SUPPORT or (name == "graphics_placements.json" and bool(plan.get("graphicsTrack")))
        if required or os.path.lexists(path):
            result.append({"role": name, "artifact": artifact_reference(path)})
        else:
            result.append({"role": name, "artifact": None})
    staged = Path(composition["outputPath"]).parent / "edit_plan.json"
    reference = artifact_reference(staged)
    if digest(bound_json(staged, reference["sha256"])) != digest(plan):
        raise RuntimeError("body actual staged QC plan differs from original candidate")
    result.append({"role": "staged-edit-plan", "artifact": reference})
    return result


def verify_body_support(root: Path, rows: list[dict]) -> None:
    """Final after-source-read proof, including added optional support detection."""
    roles = [*_REQUIRED_SUPPORT, *_OPTIONAL_SUPPORT, "staged-edit-plan"]
    if type(rows) is not list or [row["role"] for row in rows] != roles:
        raise RuntimeError("body support inventory is incomplete or reordered")
    for row in rows:
        closed(row, {"role", "artifact"}, "body candidate support")
        if row["role"] in _REQUIRED_SUPPORT and row["artifact"] is None:
            raise RuntimeError("body required support cannot be declared absent")
        path = root / "body-candidate" / row["role"]
        if row["role"] == "staged-edit-plan":
            path = Path(row["artifact"]["path"])
        if row["artifact"] is None and os.path.lexists(path):
            raise RuntimeError("body optional support appeared after observation")
        if row["artifact"] is not None:
            held_ref(row["artifact"], root / "body-candidate", path)
