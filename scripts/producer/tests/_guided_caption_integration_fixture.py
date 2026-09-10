"""TEST-only native caption/shared-graph preparation, no authenticated job claim."""
from __future__ import annotations

import contextlib
from fractions import Fraction
from pathlib import Path
from typing import Callable

from _cut_preview_fixture import ffmpeg
from _ingest_admission_fixture import runner as admission_fixture
from cut_preview_io import file_hash, write_new
from guided_caption_profile import CAPTION_PROFILE, CAPTION_SHORT_PROFILE
from guided_opening_frames import _profile
from guided_opening_inputs import OpeningInputs
from guided_opening_prepare import prepare_full_program
from ingest_admission import admit_ingest_candidates, collect_ingest_candidates


def _source(root: Path, short: bool) -> tuple[dict, Path]:
    """Real local non-speech seeded calibration; TEST attestations are explicit."""
    size = "480x270" if short else "1920x1080"
    raw = root / "TEST-calibration.mp4"
    ffmpeg(["-f", "lavfi", "-i", f"testsrc2=s={size}:r=30000/1001:d=4.1041",
        "-f", "lavfi", "-i", "anoisesrc=c=pink:a=0.12:s=48000:d=4.1041:seed=733",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2", str(raw)])
    source = root / "source"
    source.mkdir(mode=0o700)
    admitted = admit_ingest_candidates(collect_ingest_candidates([raw], None, None), source, admission_fixture)
    item = admitted.media_by_original[str(raw)]
    transcript = source / "TEST-words.json"
    write_new(transcript, {"transcript": [{"words": [
        {"word": "SYNTHETIC", "start": .2, "end": .6},
        {"word": "CALIBRATION", "start": .65, "end": 1.1},
        {"word": "ONLY", "start": 3.3001, "end": 3.9001}]}]})
    manifest = {"sources": [{"id": "TEST", "duration": 4.1041, "path": item.snapshot_path,
        "originalPath": item.original_path, "sourceSha256": item.sha256, "transcriptPath": str(transcript),
        "admissionReceiptPath": item.receipt_path, "admissionReceiptSha256": item.receipt_sha256}],
        "sourceSetAdmission": admitted.binding}
    path = source / "asset_manifest.json"
    write_new(path, manifest)
    return manifest, path


def plan_for_profile(short: bool) -> dict:
    """Legal native TEST template/window; no actual template-render assertion."""
    target = {"mode": "short" if short else "longform", "excerpt": True, "scope": "trim",
        "width": 1080 if short else 1920, "height": 1920 if short else 1080, "fps": 30}
    plan = {"planVersion": 1, "target": target, "captions": {"burn": True},
        "captionsTrack": {"schemaVersion": 1, "source": "kept-transcript",
                          "defaultPolicy": "karaoke" if short else "line", "groups": []},
        "cutTrack": [{"sourceId": "TEST", "start": 0, "end": 4.004}],
        "graphicsTrack": [{"id": "TEST-card", "kind": "statement-card", "anchor": "own-screen",
            "outStart": .1001, "outEnd": 2.6026, "exitOnCut": False,
            "reason": "TEST ONLY compositor/layer geometry, not actual template or creator review.",
            "spec": {"text": "TEST ONLY", "variant": "classic"}}]}
    if short:
        plan["reframe"] = {"layout": "fill", "crop": [0.25, 0, 0.5, 1], "track": False}
        plan["graphicsTrack"][0].update(kind="kinetic-quote", outEnd=float(Fraction(77 * 1001, 30000)),
                                      spec={"quote": "TEST ONLY", "bg": "dark", "highlight": ""})
    seam = plan["graphicsTrack"][0]["outEnd"]
    plan["cutTrack"] = [{"sourceId": "TEST", "start": 0, "end": seam},
        {"sourceId": "TEST", "start": seam + .1001, "end": 4.1041}]
    return plan


def preparation(root: Path, short: bool, guard: Callable[[], float]) -> tuple:
    """Current explicit profile and actual ordinary base/master/caption return."""
    manifest, manifest_path = _source(root, short)
    plan = plan_for_profile(short)
    target = plan["target"]
    profile = CAPTION_SHORT_PROFILE if short else CAPTION_PROFILE
    _profile(plan, profile)
    path, lock = root / "candidate.json", root / "TEST-pipeline-lock.json"
    write_new(path, plan)
    write_new(lock, {"TEST": "not an authenticated pipeline lock"})
    refs = {"candidatePlan": {"path": str(path), "sha256": file_hash(path)},
        "manifest": {"path": str(manifest_path), "sha256": file_hash(manifest_path)}}
    authority = {"frameRate": "30000/1001", "totalFrames": 120, "target": target,
        "core": {"startFrame": 0, "endFrameExclusive": 8}, "review": {"startFrame": 0, "endFrameExclusive": 15}}
    inputs = OpeningInputs(path, refs["candidatePlan"]["sha256"],
        {"executionInputHash": "c" * 64, "profile": profile, "documents": refs, "pipeline": {"lockPath": str(lock)}},
        {"candidatePlan": plan, "manifest": manifest, "authority": authority})
    output = root / "opening"
    output.mkdir(mode=0o700)
    with (root / "ordinary.log").open("w") as log, contextlib.redirect_stdout(log):
        prepared = prepare_full_program(inputs, output, guard)
    return inputs, output, prepared


def graphic(root: Path, canvas: tuple[int, int]) -> tuple[Path, dict]:
    """Deliberately synthetic native opaque asset, not an OCI/template render."""
    path = root / "TEST-opaque-graphic.mp4"
    frames = 74 if canvas == (1080, 1920) else 75
    duration, end = float(Fraction(frames * 1001, 30000)), float(Fraction((frames + 3) * 1001, 30000))
    ffmpeg(["-f", "lavfi", "-i", f"color=c=0x202020:s={canvas[0]}x{canvas[1]}:r=30000/1001:d={duration}",
            "-frames:v", str(frames), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)])
    return path, {"path": str(path), "graphicId": "TEST-card", "outStart": .1001, "outEnd": end,
        "anchor": "own-screen", "x": 0, "y": 0, "startFrame": 3, "endFrameExclusive": frames + 3}
