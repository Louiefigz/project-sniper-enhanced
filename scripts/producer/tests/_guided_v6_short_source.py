"""Fresh TEST-only16s source with real admission, never ASR or creator approval."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from _guided_body_audio import write_calibration_bed
from cut_preview_io import write_new
from headless.process_runner import ProcessRequest, run_text
from ingest_admission import admit_ingest_candidates, collect_ingest_candidates
from ingest_probe import probe_media
from transcript_source_authority import bind_result, observe_source

DURATION = 16
TEXT = ("This synthetic clip demonstrates a fixed crop and readable captions. "
        "Each generated picture uses a repeating pattern, while every word below is authored test text. "
        "Nothing here represents speech recognition or a creator's recorded delivery.")


def short_documents() -> dict:
    """Author initial intent and exactly four previsual fields before any capture."""
    intent = {"mode": "short", "scope": "light",
              "lanes": {"captions": "auto", "motion": "off", "graphics": "off"}}
    tokens = TEXT.split()
    step = DURATION / len(tokens)
    words = [{"word": word, "start": round(index * step, 6),
              "end": round((index + 1) * step, 6), "confidence": 1.0}
             for index, word in enumerate(tokens)]
    return {"scope": "TEST-only-synthetic-text-not-ASR-or-human-approval", "intent": intent,
        "plan": {"planVersion": 1, "target": {**intent, "width": 1080, "height": 1920, "fps": 30},
                 "cutTrack": [{"sourceId": "raw-1", "start": 0, "end": DURATION, "speed": 1,
                               "rationale": "TEST ONLY retain the complete synthetic program."}],
                 "cutDecisions": {"schemaVersion": 1, "removals": []}},
        "transcript": {"transcript": [{"start": 0, "end": DURATION, "text": TEXT, "words": words}],
                       "testOnly": "Authored timing over non-speech calibration audio; no ASR was run."}}


def source_ffmpeg() -> str:
    """Require the same explicit installed canonical executable as the owner."""
    configured = os.environ.get("HYPERFRAMES_FFMPEG_PATH", "")
    if not configured or not os.path.isabs(configured):
        raise RuntimeError("TEST source requires explicit HYPERFRAMES_FFMPEG_PATH")
    executable = Path(configured)
    if str(executable.resolve(strict=True)) != configured \
            or not executable.is_file() or not os.access(executable, os.X_OK):
        raise RuntimeError("TEST source FFmpeg must be canonical and executable")
    return configured


def synthesize(root: Path) -> Path:
    """One owned local FFmpeg process; no model, downloads, or source reuse."""
    ffmpeg = source_ffmpeg()
    audio = root / "TEST-non-speech.wav"
    write_calibration_bed(audio, DURATION)
    video = root / "TEST-synthetic-source.mp4"
    command = (ffmpeg, "-nostdin", "-v", "error", "-n", "-f", "lavfi", "-i",
               f"testsrc2=size=1920x1080:rate=30:duration={DURATION}", "-i", str(audio),
               "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "ultrafast",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2", "-movflags", "+faststart", str(video))
    result = run_text(ProcessRequest(command=command, stdin_text="", cwd=str(root),
        environment=dict(os.environ), timeout_seconds=60, max_output_bytes=1024 * 1024))
    if result.returncode != 0:
        raise RuntimeError(f"TEST source synthesis failed: {result.stderr[-1000:]}")
    return video


def admit_source(root: Path, video: Path) -> dict:
    """Use the actual sandbox admission, with no fixture runner/probe override."""
    source = root / "source"
    admission = admit_ingest_candidates(collect_ingest_candidates([video], None, None), source)
    row = admission.media_by_original[str(video)]
    probe = probe_media(row.snapshot_path)
    return {"sources": [{"id": "raw-1", "duration": probe.duration, "path": row.snapshot_path,
        "originalPath": row.original_path, "sourceSha256": row.sha256,
        "admissionReceiptPath": row.receipt_path, "admissionReceiptSha256": row.receipt_sha256,
        "fps": probe.fps, "frameRate": probe.frame_rate, "vfr": probe.vfr,
        "resolution": [probe.width, probe.height], "rotation": probe.rotation,
        "audio": {"present": probe.audio_present, "channels": probe.audio_channels, "sampleRate": probe.audio_sample_rate},
        "transcriptPath": "raw.transcript.json"}], "sourceSetAdmission": admission.binding}


def create_source(root: Path) -> dict:
    """New-only fixture; failures remain for inspection, never reuse old admission."""
    root.mkdir(mode=0o700)
    documents = short_documents()
    write_new(root / "TEST-initial-documents.json", documents)
    write_new(root / "TEST-previsual-plan.json", documents["plan"])
    manifest = admit_source(root, synthesize(root))
    row = manifest["sources"][0]
    source = Path(row["path"])
    observation = observe_source(source, (row["sourceSha256"], source.stat().st_size))
    transcript = bind_result(documents["transcript"], observation)
    write_new(root / "source/raw.transcript.json", transcript)
    write_new(root / "source/asset_manifest.json", manifest)
    return {"scope": documents["scope"], "root": str(root), "realSandboxAdmission": True,
            "sourceKind": "testsrc2-and-seeded-non-speech-calibration", "actualAsr": False}


def main() -> None:
    """Describe pure initial metadata or explicitly create one actual TEST source."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path)
    parser.add_argument("--describe", action="store_true")
    args = parser.parse_args()
    if args.describe == (args.root is not None):
        parser.error("choose --describe OR one new absolute TEST source root")
    if args.describe:
        print(json.dumps(short_documents()))
        return
    if not args.root.is_absolute() or args.root != args.root.resolve():
        parser.error("TEST source root must be absolute and canonical")
    print(json.dumps(create_source(args.root)))


if __name__ == "__main__":
    main()
