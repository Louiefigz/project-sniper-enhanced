"""Opt-in current sealed plate renders and real composite contrast screening.

Two 2.5s overlays, six encoded backgrounds, 120s soft workload budget checked
between owned phases. Existing cleanup remains mandatory on any timeout. Tiny
silent fixtures cannot pass overall delivery QC and create no approval/final.
"""
from __future__ import annotations

import dataclasses
import json
import subprocess
import tempfile
import time
from pathlib import Path

from audit.audit_render import run_audit
from cut_preview_io import file_hash, write_new
from graphics.delivery_geometry import fallback_placement_evidence
from headless.render_build import render_build_manifests_equal
from headless.render_lane import (
    OverlayPreparationRequest, RenderExecutionPolicy, launch_overlay, prepare_overlay_launch,
)
from headless.render_runtime import current_render_build_manifest
from headless.request_artifact import store_request_artifact
from live_render_build_v2_smoke import error_chain, runtime
from planner.eye_trace import placement_row


def entries() -> list[dict]:
    common = {"kind": "section-marker", "anchor": "free-band", "outStart": 0, "outEnd": 2.5}
    return [{**common, "spec": {"num": "System No.1", "line1": "Current Plates", "line2": "Boundary",
                "side": "left", "readability": "plates"}},
            {**common, "spec": {"num": "A Longer Section Label", "line1": "A Longer Chapter Name",
                "line2": "A clear qualifier remains readable", "side": "right",
                "readability": "plates", "accent": "#123456"}}]


def remaining(deadline: float) -> float:
    value = deadline - time.monotonic()
    if value <= 0:
        raise TimeoutError("section-marker smoke workload deadline exceeded")
    return value


def render(directory: Path, graphic: dict, deadline: float) -> dict:
    current = dataclasses.replace(runtime(), timeout_seconds=min(90, int(remaining(deadline))))
    authority = directory / "authority"
    # mkdir(parents=True, mode=0o700) applies the mode to the leaf only; every level
    # of a durable authority root must be owned 0700 (headless/durable_files.py).
    for level in (authority, authority / "attempts", authority / "attempts" / "plate"):
        level.mkdir(mode=0o700)
    attempt = authority / "attempts" / "plate"
    artifact = store_request_artifact(str(authority), {"schemaVersion": 1, "operation": "render-overlays",
        "overlays": [{"overlayId": "plate", "entry": graphic}]})
    prepared = prepare_overlay_launch(OverlayPreparationRequest(str(authority), str(attempt),
        attempt.name, artifact, "plate"), current)
    return launch_overlay(RenderExecutionPolicy("sealed-oci-v2"), prepared, current)


def ffmpeg(arguments: list[str], deadline: float) -> None:
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-n", *arguments],
        check=True, capture_output=True, timeout=min(30, remaining(deadline)))


def composite_case(directory: Path, graphic: dict, media: str, context: tuple) -> dict:
    background, deadline = context
    directory.mkdir(mode=0o700)  # durable authority stores require owned 0700 roots
    started = time.monotonic()
    ffmpeg(["-f", "lavfi", "-i", f"color=c={background}:s=1080x1920:r=30:d=2.5",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-threads", "2",
        str(directory / "base_final.mp4")], deadline)
    ffmpeg(["-i", str(directory / "base_final.mp4"), "-i", media, "-filter_complex_threads", "1",
        "-filter_complex", "[0:v][1:v]overlay=format=auto:shortest=1[v]", "-map", "[v]", "-an",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-threads", "2", str(directory / "final.mp4")], deadline)
    observed = fallback_placement_evidence(media, (0, 0), {"anchor": "free-band"}, (1080, 1920))
    write_new(directory / "graphics_placements.json", [placement_row(graphic, observed, (1080, 1920))])
    write_new(directory / "edit_plan.json", {"target": {"mode": "short", "scope": "light"},
        "graphicsTrack": [graphic], "cutTrack": []})
    remaining(deadline)
    audit = run_audit(str(directory))
    checks = [vars(row) for row in audit.checks]
    write_new(directory / "all-checks.json", checks)
    visual = [row for row in checks if str(row["name"]).startswith("graphic_composite")]
    return {"background": background, "elapsedMs": round((time.monotonic() - started) * 1000),
        "visualChecks": visual, "visualPassed": bool(visual) and not any(row["status"] == "fail" for row in visual),
        "overallAudit": audit.overall, "deliveryApproved": False, "artifactDir": str(directory)}


def run(root: Path, result: dict, deadline: float) -> None:
    before = current_render_build_manifest(runtime())
    write_new(root / "build-before.json", before)
    for index, graphic in enumerate(entries()):
        directory = root / f"case-{index}"
        directory.mkdir(mode=0o700)  # durable authority stores require owned 0700 roots
        started = time.monotonic()
        launched = render(directory, graphic, deadline)
        row = {"entry": graphic, "launch": launched,
               "renderMs": round((time.monotonic() - started) * 1000), "backgrounds": []}
        result["renders"].append(row)
        write_new(directory / "launch.json", row)
        media = launched["result"]["path"]
        for name, color in (("black", "#000000"), ("navy", "#0a1123"), ("white", "#ffffff")):
            item = composite_case(directory / name, graphic, media, (color, deadline))
            row["backgrounds"].append(item)
            print(json.dumps(item), flush=True)
            remaining(deadline)
    after = current_render_build_manifest(runtime())
    write_new(root / "build-after.json", after)
    result["buildUnchanged"] = render_build_manifests_equal(before, after)
    remaining(deadline)
    result["passed"] = result["buildUnchanged"] and all(
        item["visualPassed"] for row in result["renders"] for item in row["backgrounds"])


def main() -> None:
    started = time.monotonic()
    root = Path(tempfile.mkdtemp(prefix="sniper-section-plates-live-", dir="/private/tmp"))
    result = {"passed": False, "renders": [], "deliveryApproved": False,
        "runnerAtStartSha256": file_hash(Path(__file__)), "artifactDir": str(root)}
    print(json.dumps({"phase": "start", "artifactDir": str(root)}), flush=True)
    try:
        run(root, result, started + 120)
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as error:
        result["errorChain"] = error_chain(error)
    result["elapsedMs"] = round((time.monotonic() - started) * 1000)
    write_new(root / "result.json", result)
    print(json.dumps(result), flush=True)
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
