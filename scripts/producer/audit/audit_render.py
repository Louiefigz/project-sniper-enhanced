#!/usr/bin/env python3
"""audit_render — Audit B: post-render QC over a PRODUCER render output dir.

Reads a finished render directory (``final.mp4`` + ``cover.png`` +
``timeline_map.json`` + ``edit_plan.json`` — the layout render.py writes) and
runs the deterministic checks (duration, loudness, format, file budget, cover),
extracts frames for visual review, and runs the safe-zone edge heuristic. Writes
``audit_report.json`` (machine) and ``audit_report.md`` (human, with a VISION
REVIEW CHECKLIST). Exit 0 when nothing FAILs (warnings are fine), exit 1 on any
FAIL. See docs/producer/PRODUCER_PLAN.md §5 (Audit B).

CLI: audit_render.py <out_dir>
"""

from __future__ import annotations

import argparse
import json
import copy
import os
import sys
from dataclasses import asdict, dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audit.audit_checks import (  # noqa: E402
    CheckResult, FAIL, PASS, WARN, check_cover, check_duration,
    check_file_budget, check_format, check_loudness, has_audio_stream,
    worst_status,
)
from audit.audit_frames import (  # noqa: E402
    FrameRef, check_frame_extraction, extract_review_frames, plan_frames,
    scan_safe_zone,
)
from audit.audit_glitch import check_glitch_screens  # noqa: E402
from audit.audit_composite_visual import check_composite_visuals  # noqa: E402
from audit.audit_captions import check_caption_authority  # noqa: E402
from audit.audio_quality import check_audio_quality  # noqa: E402
from audit.audit_motion import (  # noqa: E402
    check_pacing_rendered, check_presence, check_smoothness,
)
from audit.audit_placements import check_eye_trace  # noqa: E402
from audit.audit_probe import (  # noqa: E402
    ffprobe_json, first_stream, fps_from_stream, video_frame_count,
)
from compile_timeline import TimelineMap  # noqa: E402
from fingerprints import file_sha256  # noqa: E402
from audio.audio_mix_delivery import (  # noqa: E402
    AUDIO_DELIVERY_POLICY_VERSION, measure_delivery,
)


@dataclass
class Probed:
    """The identity + probed streams of one render (keeps helpers <=4 params)."""

    out_dir: str
    final: str
    mode: str
    video: dict
    audio: dict | None
    audio_delivery: dict | None = None
    final_sha256: str | None = None


@dataclass
class AuditReport:
    """The full Audit B result for one render directory."""

    out_dir: str
    final_path: str
    mode: str
    overall: str
    exit_code: int
    checks: list[CheckResult]
    frames: list[FrameRef]
    audio_delivery: dict | None = None
    final_sha256: str | None = None


def _load_json(path: str) -> dict | None:
    """Parse a JSON file, or None if it is missing/unreadable."""
    try:
        with open(path) as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def _fallback_duration(final_path: str, video: dict) -> float:
    """Output duration from the video timeline when timeline_map.json is absent."""
    frames = video_frame_count(final_path)
    fps = fps_from_stream(video)
    return frames / fps if frames and fps else 0.0


def _emit(status: str, **fields) -> None:
    """One JSON status line on stdout (NDJSON, like the sibling stages)."""
    print(json.dumps({"status": status, **fields}), flush=True)


def run_audit(out_dir: str, graphics_reference: str | None = None) -> AuditReport:
    """Run all checks; a trusted caller may supply its exact graphics-free base."""
    final = os.path.join(out_dir, "final.mp4")
    plan = _load_json(os.path.join(out_dir, "edit_plan.json")) or {}
    mode = (plan.get("target") or {}).get("mode", "short")
    if not os.path.exists(final):
        probed = Probed(out_dir, final, mode, {}, None)
        return _assemble(probed, [CheckResult(
            "final_present", FAIL, "missing", "final.mp4 not found")], [])
    probe = ffprobe_json(final)
    video = first_stream(probe, "video")
    audio = first_stream(probe, "audio")
    if video is None:
        probed = Probed(out_dir, final, mode, {}, None)
        return _assemble(probed, [CheckResult(
            "format_video", FAIL, "no video stream", "no decodable video")], [])
    probed = Probed(out_dir, final, mode, video, audio,
                    final_sha256=file_sha256(final))
    checks, duration = _deterministic_checks(probed)
    # Frame planning must aim inside the DELIVERED stream: predicted duration
    # runs a few sub-frame roundings long on multi-segment mining cuts, and a
    # "final" ref past the last frame PTS makes extraction fail spuriously.
    stream_duration = 0.0
    try:
        stream_duration = float(video.get("duration") or 0.0)
    except (TypeError, ValueError):
        stream_duration = 0.0
    frame_horizon = min(duration, stream_duration) if stream_duration > 0 else duration
    frames = extract_review_frames(final, out_dir, plan_frames(plan, frame_horizon), probe)
    checks.append(check_frame_extraction(frames))
    checks.extend(scan_safe_zone(frames, plan, video))
    checks.extend(check_composite_visuals(out_dir, plan, frames, graphics_reference))
    checks.extend(check_caption_authority(out_dir, plan))
    return _assemble(probed, checks, frames)


def _deterministic_checks(p: Probed) -> tuple[list[CheckResult], float]:
    """The measurement checks plus the output duration used for frame planning."""
    checks: list[CheckResult] = []
    plan = _load_json(os.path.join(p.out_dir, "edit_plan.json")) or {}
    # Sealed cut lineage binds the plan exactly as saved; the audio sections
    # derived below are for the dialogue check only and must not reach it.
    saved_plan = copy.deepcopy(plan)
    plan.pop("audioReviewSections", None)
    tmap_data = _load_json(os.path.join(p.out_dir, "timeline_map.json"))
    if tmap_data is None:
        checks.append(CheckResult("timeline_map_present", FAIL, "missing",
                                  "cannot verify duration without timeline_map"))
        duration = _fallback_duration(p.final, p.video)
    else:
        tmap = TimelineMap.from_dict(tmap_data)
        checks.append(check_duration(p.final, p.video, tmap))
        duration = tmap.output_duration
        plan["audioReviewSections"] = [
            {"start": segment.out_start, "end": segment.out_end,
             "label": f"picture cut {segment.index}: {segment.source_id}"}
            for segment in tmap.segments]
    audio_present = has_audio_stream(p.audio)
    p.audio_delivery = measure_delivery(p.final)
    checks.extend(check_loudness(p.final, audio_present, p.audio_delivery))
    checks.extend(check_format(p.final, p.video, p.audio, p.mode))
    if audio_present:
        checks.extend(check_audio_quality(p.final, plan))
    checks.append(check_file_budget(p.final, p.mode))
    checks.append(check_cover(p.out_dir, p.video))
    # Plan-declared own-screen takeover windows: a dark takeover world is
    # near-black by design — detect_black demotes runs inside them to WARN.
    own_screen = [(float(g["outStart"]), float(g["outEnd"]))
                  for g in plan.get("graphicsTrack") or []
                  if g.get("anchor") == "own-screen"]
    checks.extend(check_glitch_screens(p.final, duration, own_screen))
    # Motion integrity fails here; ambiguous cut-rate shortfalls remain review
    # warnings. This mirrors the upstream pacing planner; see audit_motion.
    checks.extend(check_pacing_rendered(p.final, duration, saved_plan, p.mode))
    checks.extend(check_presence(p.final, plan, p.out_dir))
    checks.extend(check_smoothness(p.final, plan))
    # Placement evidence is fail-closed; once measurable, eye-trace distance
    # stays advisory because the measured pro baseline is a null result.
    checks.extend(check_eye_trace(plan, p.out_dir))
    return checks, duration


def _assemble(p: Probed, checks: list[CheckResult],
              frames: list[FrameRef]) -> AuditReport:
    """Roll up verdict + exit code and build the report object."""
    if p.final_sha256 is not None:
        try:
            stable = file_sha256(p.final) == p.final_sha256
        except OSError:
            stable = False
        checks.append(CheckResult(
            "final_identity", PASS if stable else FAIL,
            p.final_sha256, "exact candidate SHA-256 before/after audit"))
    overall = worst_status(checks) if checks else FAIL
    exit_code = 1 if overall == FAIL else 0
    return AuditReport(out_dir=p.out_dir, final_path=p.final, mode=p.mode,
                       overall=overall, exit_code=exit_code,
                       checks=checks, frames=frames, audio_delivery=p.audio_delivery,
                       final_sha256=p.final_sha256)


def report_to_dict(report: AuditReport) -> dict:
    """Serialize the report for audit_report.json."""
    return {
        "outDir": report.out_dir,
        "final": report.final_path,
        "mode": report.mode,
        "overall": report.overall,
        "exitCode": report.exit_code,
        "counts": _status_counts(report.checks),
        "checks": [asdict(c) for c in report.checks],
        "frames": [asdict(f) for f in report.frames],
        "audioDeliveryPolicyVersion": AUDIO_DELIVERY_POLICY_VERSION,
        "audioDelivery": report.audio_delivery,
        "finalSha256": report.final_sha256,
    }


def _status_counts(checks: list[CheckResult]) -> dict:
    """Tally pass / warn / fail across the checks."""
    return {s: sum(1 for c in checks if c.status == s)
            for s in (PASS, WARN, FAIL)}


def _md_escape(text: str) -> str:
    """Escape pipe characters so a value can't break the markdown table."""
    return text.replace("|", "\\|")


def _checks_table(checks: list[CheckResult]) -> list[str]:
    """Markdown rows for the checks table."""
    rows = ["| Check | Status | Measured | Detail |",
            "|---|---|---|---|"]
    for c in checks:
        rows.append(f"| {c.name} | {c.status.upper()} | "
                    f"{_md_escape(c.measured)} | {_md_escape(c.detail)} |")
    return rows


def _frames_section(frames: list[FrameRef]) -> list[str]:
    """Markdown for the extracted-frames list + the vision-review checklist."""
    lines = ["", "## Extracted frames", ""]
    if not frames:
        lines.append("_No frames extracted._")
    for f in frames:
        loc = f.path or "(extraction failed)"
        lines.append(f"- **{f.label}** ({f.kind}, t={f.timestamp:.3f}s): {loc}")
    lines += ["", "## VISION REVIEW CHECKLIST", "",
              "Eyeball each frame above (a human or Claude, multimodal):", ""]
    for f in frames:
        if f.note:
            lines.append(f"- **{f.label}** (t={f.timestamp:.3f}s): {f.note}")
    return lines


def render_markdown(report: AuditReport) -> str:
    """Human-readable audit_report.md."""
    counts = _status_counts(report.checks)
    header = [
        f"# Audit B — {os.path.basename(report.out_dir.rstrip('/'))}",
        "",
        f"- **Overall:** {report.overall.upper()} (exit {report.exit_code})",
        f"- **Mode:** {report.mode}",
        f"- **Final:** {report.final_path}",
        f"- **Checks:** {counts[PASS]} pass / {counts[WARN]} warn / "
        f"{counts[FAIL]} fail",
        "",
        "## Deterministic checks",
        "",
    ]
    body = _checks_table(report.checks)
    return "\n".join(header + body + _frames_section(report.frames)) + "\n"


def write_reports(report: AuditReport) -> tuple[str, str]:
    """Write audit_report.json + audit_report.md into the out dir; return paths."""
    json_path = os.path.join(report.out_dir, "audit_report.json")
    md_path = os.path.join(report.out_dir, "audit_report.md")
    with open(json_path, "w") as handle:
        json.dump(report_to_dict(report), handle, indent=2)
    with open(md_path, "w") as handle:
        handle.write(render_markdown(report))
    return json_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="PRODUCER Audit B — post-render QC")
    parser.add_argument("out_dir", help="a render output dir (final.mp4 etc.)")
    args = parser.parse_args()
    if not os.path.isdir(args.out_dir):
        _emit("error", error=f"not a directory: {args.out_dir}")
        return 1
    report = run_audit(args.out_dir)
    json_path, md_path = write_reports(report)
    counts = _status_counts(report.checks)
    _emit("done", overall=report.overall, exitCode=report.exit_code,
          passed=counts[PASS], warnings=counts[WARN], failed=counts[FAIL],
          report=md_path, machine=json_path)
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
