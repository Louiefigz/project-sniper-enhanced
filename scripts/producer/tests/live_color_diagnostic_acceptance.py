"""Explicit real-container synthetic acceptance; never run in ordinary discovery.

Requires the existing approved-image environment. No downloads, grade, master,
or approval. Prints a retained temporary artifact path; this is diagnostic
plumbing evidence, not creator-footage quality or color pipeline parity.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from color.diagnostic import run_diagnostic
from color.model import DiagnosticRequest
from cut_preview_io import write_new
from headless.external_media_probe import admit_external_media
from headless.external_media_probe_policy import MediaProbeLimits
from ingest_admission import IngressCandidate, admit_ingest_candidates


def _synthetic_source(path: Path) -> None:
    subprocess.run([
        "ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
        "color=c=0x303030:s=160x90:r=2:d=60", "-f", "lavfi", "-i",
        "color=c=0xc0c0c0:s=160x90:r=2:d=30", "-f", "lavfi", "-i",
        "sine=frequency=440:sample_rate=48000:duration=90", "-filter_complex",
        "[0:v][1:v]concat=n=2:v=1:a=0,setparams=range=limited:color_primaries=bt709:color_trc=bt709:colorspace=bt709[v]",
        "-map", "[v]", "-map", "2:a",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709",
        "-color_trc", "bt709", "-c:a", "aac", "-af", "volume=0.03", "-shortest", str(path),
    ], check=True, capture_output=True, timeout=15)


def _admit(source: str, store: str) -> dict:
    return admit_external_media(source, store, MediaProbeLimits(max_decode_seconds=90))


def create_fixture(root: Path) -> tuple[Path, list[dict]]:
    """Create a genuinely admitted synthetic source, not a forged fixture receipt."""
    producer = root / "producer"
    producer.mkdir()
    original = root / "synthetic-dark-then-light.mp4"
    _synthetic_source(original)
    admitted = admit_ingest_candidates([IngressCandidate(original, "source")], producer, _admit)
    media = admitted.media_by_original[str(original)]
    source = {"id": "raw-1", "path": media.snapshot_path, "originalPath": media.original_path,
              "sourceSha256": media.sha256, "sourceSizeBytes": media.size_bytes,
              "admissionReceiptPath": media.receipt_path, "admissionReceiptSha256": media.receipt_sha256,
              "duration": 90, "fps": 2, "resolution": [160, 90], "audio": {"present": True}}
    manifest = {"sources": [source], "broll": [], "music": [], "sourceSetAdmission": admitted.binding}
    plan = {"planVersion": 1, "target": {"mode": "short", "scope": "light"},
            "cutTrack": [{"sourceId": "raw-1", "start": 0, "end": 10},
                         {"sourceId": "raw-1", "start": 55, "end": 90}], "graphicsTrack": []}
    write_new(producer / "asset_manifest.json", manifest)
    write_new(producer / "edit_plan.json", plan)
    write_new(root / "project.json", {"origin": "raw", "history": [], "syntheticTestOnly": True})
    contexts = [{"sourceId": "raw-1", "sourceProfile": "bt709-sdr", "cameraProfile": None,
                 "historyState": "known", "transformHistory": [], "lightingGroups": [
                     {"id": "dark", "start": 0, "end": 60, "intent": "dark", "description": "intentional synthetic dark plate"},
                     {"id": "light", "start": 60, "end": 90, "intent": "neutral", "description": "synthetic light plate"}]}]
    return producer, contexts


def main() -> None:
    started = time.monotonic()
    root = Path(tempfile.mkdtemp(prefix="sniper-color-live-", dir="/private/tmp"))
    producer, contexts = create_fixture(root)
    setup = time.monotonic() - started
    plan = (producer / "edit_plan.json").read_bytes()
    manifest = (producer / "asset_manifest.json").read_bytes()
    request = DiagnosticRequest(producer, hashlib.sha256(plan).hexdigest(), hashlib.sha256(manifest).hexdigest(), contexts)
    result = run_diagnostic(request)
    summary = {"fixtureDir": str(root), "setupAndRealAdmissionMs": round(setup * 1000),
               "totalElapsedMs": round((time.monotonic() - started) * 1000),
               "state": result["state"], "diagnosticElapsedMs": result["elapsedMs"],
               "artifactDir": result["artifactDir"], "error": result.get("error"),
               "groups": [{"id": row["groupId"], "summary": row["summary"],
                           "actualTimes": [sample.get("actualSourceTime") for sample in row["observations"]],
                           "suggestions": row["suggestions"], "warnings": row["warnings"]}
                          for row in result["groups"]]}
    if (producer / "edit_plan.json").read_bytes() != plan or (producer / "asset_manifest.json").read_bytes() != manifest:
        raise AssertionError("diagnostic mutated canonical inputs")
    if (producer / "final.mp4").exists() or result["deliveryApproved"]:
        raise AssertionError("diagnostic produced delivery authority")
    print(json.dumps(summary, indent=2))
    raise SystemExit(0 if result["state"] == "complete" else 1)


if __name__ == "__main__":
    main()
