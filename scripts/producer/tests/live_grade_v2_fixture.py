"""Opt-in REAL admission of newly generated TEST-only UHD tagged media.

The synthetic tags exercise observation plumbing, NOT gamut/color correctness.
No creator footage, ASR, model, grade or approval is read or written. All failures
remain in the printed private root. Ordinary test discovery never executes it.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from color.deadline import require_time, wall_budget
from cut_preview_io import bound_json, file_hash, write_new
from headless.external_media_probe import admit_external_media
from headless.external_media_probe_policy import MediaProbeLimits
from headless.process_runner import ProcessRequest, run_text
from ingest_admission import IngressCandidate, admit_ingest_candidates


def encode_arguments(output: Path) -> tuple[str, ...]:
    """Generate24 native frames; metadata is authored only on this new fixture."""
    return ("-nostdin", "-v", "error", "-n", "-f", "lavfi", "-i",
        "color=c=0x808080:s=3840x2160:r=24000/1001", "-frames:v", "24", "-an",
        "-vf", "setsar=1,setparams=range=limited:color_primaries=bt709:color_trc=iec61966-2-4:colorspace=bt709",
        "-c:v", "libx264", "-threads", "4", "-preset", "ultrafast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-color_range", "tv", "-colorspace", "bt709",
        "-color_primaries", "bt709", "-color_trc", "iec61966-2-4",
        "-video_track_timescale", "24000", "-movflags", "+faststart", str(output))


def _encode(root: Path, output: Path, deadline: float) -> None:
    """Only the trusted local fixture encoder runs outside the actual OCI probe."""
    tool = shutil.which("ffmpeg")
    if tool is None:
        raise RuntimeError("existing local ffmpeg required; no installation fallback")
    command = (str(Path(tool).resolve()), *encode_arguments(output))
    write_new(root / "TEST-encoder-intent.json", {"command": list(command),
        "toolSha256": file_hash(Path(command[0]), 128 * 1024 ** 2), "remainingSeconds": require_time(deadline)})
    result = run_text(ProcessRequest(command, "", str(root),
        {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
        min(30, require_time(deadline)), max_output_bytes=128 * 1024))
    write_new(root / "TEST-encoder.json", {"command": list(command), "returncode": result.returncode,
        "stdout": result.stdout, "stderr": result.stderr, "syntheticTagsNotColorQualification": True})
    if result.returncode or result.stderr:
        raise RuntimeError("TEST source encoder failed; retained actual encoder output")


def _publish(project: Path, admitted, original: Path) -> Path:
    """Publish actual admission references, never forged or resealed source facts."""
    producer = project / "producer"
    media = admitted.media_by_original[str(original)]
    receipt = bound_json(producer / media.receipt_path, media.receipt_sha256)
    facts = receipt["decoded"]["facts"]
    if facts["declaredFrames"] != 24 or (facts["width"], facts["height"]) != (3840, 2160) \
            or facts["videoStreams"] != 1 or facts["sizeBytes"] != media.size_bytes \
            or media.size_bytes > 8 * 1024 ** 2:
        raise RuntimeError("actual TEST admission does not match the encoded tiny fixture")
    source = {"id": "raw-1", "path": media.snapshot_path, "originalPath": media.original_path,
        "sourceSha256": media.sha256, "sourceSizeBytes": media.size_bytes,
        "admissionReceiptPath": media.receipt_path, "admissionReceiptSha256": media.receipt_sha256,
        "duration": facts["durationSeconds"], "fps": 24000 / 1001, "frameRate": "24000/1001",
        "vfr": False, "resolution": [3840, 2160], "audio": {"present": False}}
    write_new(producer / "asset_manifest.json", {"sources": [source], "broll": [], "music": [],
        "sourceSetAdmission": admitted.binding})
    write_new(producer / "edit_plan.json", {"planVersion": 1,
        "target": {"mode": "longform", "scope": "light"}, "graphicsTrack": [],
        "cutTrack": [{"sourceId": "raw-1", "start": 0.25, "end": 0.5}]})
    write_new(project / "project.json", {"origin": "raw", "history": [],
        "syntheticTestOnly": True, "gradeV2Fixture": "native24-frames-tag-plumbing-only-v1"})
    return producer


def _admit_source(source: str, store: str, deadline: float) -> dict:
    """Keep policy's minimum decode allowance within the original setup clock."""
    if require_time(deadline) < 90:
        raise RuntimeError("TEST admission needs 90s remaining in its original 120s setup budget")
    result = admit_external_media(source, store, MediaProbeLimits(max_decode_seconds=90))
    # No outer alarm surrounds admission's mandatory cleanup; late success still rejects.
    require_time(deadline)
    return result


def create_fixture() -> Path:
    """Reject setup success after120s; retain existing admission cleanup semantics.

    The existing admission API has no caller-deadline parameter. Its own bounded
    control/decode/removal calls may outlive this success ceiling; do not put an
    outer alarm around its mandatory cleanup or call this an outer hard cap.
    """
    started = time.monotonic()
    root = Path(tempfile.mkdtemp(prefix="sniper-grade-v2-live-", dir="/private/tmp")).resolve()
    print(json.dumps({"retainedTestRoot": str(root)}), flush=True)
    project = root / "synthetic"
    project.mkdir(mode=0o700)
    producer = project / "producer"
    producer.mkdir(mode=0o700)
    original = project / "TEST-UHD-tagged.mp4"
    deadline = started + 120

    def admit(source: str, store: str) -> dict:
        return _admit_source(source, store, deadline)

    try:
        _encode(root, original, deadline)
        file_hash(original, 8 * 1024 ** 2)
        require_time(deadline)
        admitted = admit_ingest_candidates([IngressCandidate(original, "source")], producer, admit)
        with wall_budget(deadline):
            _publish(project, admitted, original)
            write_new(root / "TEST-fixture.json", {"producerDir": str(producer),
                "elapsedMs": round((time.monotonic() - started) * 1000),
                "sourceSha256": file_hash(original, 8 * 1024 ** 2),
                "syntheticTagsNotColorQualification": True, "gradeApplicable": False,
                "deliveryApproved": False})
        return producer
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        write_new(root / "TEST-setup-failed.json", {"error": str(error),
            "elapsedMs": round((time.monotonic() - started) * 1000), "retained": True})
        raise


if __name__ == "__main__":
    if sys.argv[1:] != ["--run"]:
        print("Usage: live_grade_v2_fixture.py --run (REAL synthetic encode + OCI admission; opt-in only)")
        raise SystemExit(0 if sys.argv[1:] in ([], ["--help"]) else 2)
    print(json.dumps({"producerDir": str(create_fixture()), "syntheticOnly": True}), flush=True)
