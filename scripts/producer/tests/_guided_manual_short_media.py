"""TEST-only tiny crop pixels, actual ordinary base/master, no server admission."""
from __future__ import annotations

import contextlib
import subprocess
from pathlib import Path

from _cut_preview_fixture import ffmpeg
from _ingest_admission_fixture import runner as admission_fixture
from cut_preview_io import file_hash, write_new
from guided_media_profile import SHORT_PROFILE
from guided_opening_inputs import OpeningInputs
from guided_opening_prepare import prepare_full_program
from ingest_admission import admit_ingest_candidates, collect_ingest_candidates


def source_manifest(root: Path, rotated: bool = False) -> tuple[dict, Path]:
    """Generate known right-half green/blue pixels and non-speech test audio."""
    source = root / "source"
    source.mkdir(mode=0o700)
    raw = root / "test-calibration.mp4"
    boxes = ("drawbox=x=0:y=0:w=240:h=270:color=green:t=fill,drawbox=x=240:y=0:w=240:h=270:color=blue:t=fill"
        if rotated else "drawbox=x=240:y=0:w=240:h=134:color=green:t=fill,drawbox=x=240:y=134:w=240:h=136:color=blue:t=fill")
    ffmpeg(["-f", "lavfi", "-i", "color=red:s=480x270:r=30000/1001:d=2.002",
        "-f", "lavfi", "-i", "anoisesrc=c=pink:a=0.12:s=48000:d=2.002:seed=713",
        "-vf", boxes,
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2", str(raw)])
    if rotated:
        display = root / "test-rotated.mp4"
        ffmpeg(["-display_rotation", "90", "-i", str(raw), "-c", "copy", str(display)])
        raw = display
    admitted = admit_ingest_candidates(collect_ingest_candidates([raw], None, None), source, admission_fixture)
    item = admitted.media_by_original[str(raw)]
    manifest = {"sources": [{"id": "test-right-half", "duration": 2.002, "path": item.snapshot_path,
        "originalPath": item.original_path, "sourceSha256": item.sha256,
        "admissionReceiptPath": item.receipt_path, "admissionReceiptSha256": item.receipt_sha256}],
        "sourceSetAdmission": admitted.binding}
    path = source / "asset_manifest.json"
    write_new(path, manifest)
    return manifest, path


def preparation(root: Path, rotated: bool = False):
    """Enter below authenticated 14-doc authority with explicitly TEST metadata."""
    manifest, manifest_path = source_manifest(root, rotated)
    plan = {"planVersion": 1, "target": {"mode": "short", "excerpt": True, "scope": "trim",
        "width": 1080, "height": 1920, "fps": 30}, "captions": {"burn": False},
        "reframe": {"layout": "fill", "crop": [0.5, 0, 0.5, 1], "track": False},
        "cutTrack": [{"sourceId": "test-right-half", "start": 0, "end": 2.002}]}
    if rotated:
        plan["reframe"]["crop"] = [0, 0, 1, 0.5]
    plan_path = root / "candidate.json"
    write_new(plan_path, plan)
    refs = {"candidatePlan": {"path": str(plan_path), "sha256": file_hash(plan_path)},
        "manifest": {"path": str(manifest_path), "sha256": file_hash(manifest_path)}}
    authority = {"frameRate": "30000/1001", "totalFrames": 60, "target": plan["target"],
        "core": {"startFrame": 0, "endFrameExclusive": 4},
        "review": {"startFrame": 0, "endFrameExclusive": 8}}
    inputs = OpeningInputs(plan_path, refs["candidatePlan"]["sha256"],
        {"executionInputHash": "c" * 64, "profile": SHORT_PROFILE, "documents": refs},
        {"candidatePlan": plan, "manifest": manifest, "authority": authority})
    output = root / "execution"
    output.mkdir(mode=0o700)
    with (root / "ordinary.log").open("w") as log, contextlib.redirect_stdout(log):
        prepared = prepare_full_program(inputs, output)
    return inputs, output, prepared


def pixel_bands(path: Path, at: float = 0.1) -> list[tuple[float, float, float]]:
    """Independent decoded oracle, reduced only for TEST color measurements."""
    raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", str(at), "-i", str(path),
        "-frames:v", "1", "-vf", "scale=108:192", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
        capture_output=True, check=True, timeout=15).stdout
    if len(raw) != 108 * 192 * 3:
        raise AssertionError("TEST pixel oracle did not decode the entire expected frame")
    bands = [raw[20 * 108 * 3:70 * 108 * 3], raw[120 * 108 * 3:170 * 108 * 3]]
    return [tuple(sum(band[channel::3]) / (len(band) // 3) for channel in range(3)) for band in bands]
