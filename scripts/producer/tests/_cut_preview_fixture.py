"""Real synthetic media with test-only admission attestations, never creative proof."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import time
import uuid
import wave
from array import array
from pathlib import Path

from _guided_longform_program import INTENT_LANES, build_program, program_plan
from _guided_body_program import BODY_BUDGET_S, BODY_PROGRAM
from _ingest_admission_fixture import runner as admission_fixture
from cut_preview_io import digest, write_new
from edit.compatibility_projection import build_projection
from ingest_admission import admit_ingest_candidates, collect_ingest_candidates
from ingest_probe import probe_media
from transcript_source_authority import bind_result, observe_source

LONGFORM_PROGRAM = "longform-96"
LONGFORM_300 = "longform-300"
PROGRAM_BUDGET_S = {LONGFORM_PROGRAM: 96.0, LONGFORM_300: 312.0, BODY_PROGRAM: BODY_BUDGET_S}
LONGFORM_TIMEOUT_S = 600      # a 96-340s 1080p ultrafast pair, not a 3s thumbnail
AUDIO_RATE_HZ, PULSE_HZ, PULSE_S = 48000, 880, 0.02
PULSE_PEAK = 16383            # half scale, matching the 0.5 amplitude default path
# Long-form programs carry a continuous, voice-like bed under quarter-scale
# pulses: a 5 % duty pulse track cannot be mastered to -14 LUFS under the
# -1 dBTP ceiling (opening run #11, 2026-09-06: LUFS residual -1.34), while
# real speech can. Measured: bed + pulses = -15.1 LUFS integrated, -3.3 dBFS
# peak, so the two-pass master lands inside AUDIO.lufs_tolerance (1.0 LU).
PROGRAM_PULSE_PEAK = 8191
VOICE_BED_EXPR = ("(0.8+0.2*sin(2*PI*3*t))*(0.274*sin(2*PI*140*t)"
                  "+0.164*sin(2*PI*280*t)+0.110*sin(2*PI*420*t))")
# TEST ONLY operator intent: an explicitly declared long-form EXCERPT whose
# engagement lanes are waived except graphics, so a mechanics run exercises the
# graphics/base path without owing motion/transition/caption/b-roll work.
PROJECT_INTENT = {
    "origin": "upload",
    "intent": {"mode": "longform", "scope": "produced",
               "lanes": dict(INTENT_LANES),
               "music": False},
}


def project_intent(program: dict) -> dict:
    """The stored operator intent; `excerpt` only below the 300s longform floor."""
    intent = dict(PROJECT_INTENT["intent"])
    if program["meta"]["excerpt"]:
        intent["excerpt"] = True
    return {"origin": "upload", "intent": intent}


def ffmpeg(args: list[str], timeout: int = 20) -> None:
    """Execute a short synthetic-media fixture with a hard test deadline."""
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", *args],
                   capture_output=True, check=True, timeout=timeout)


def _pulse_track(path: Path, starts: list[float], duration: float,
                 peak: int = PULSE_PEAK) -> Path:
    """Write a deterministic 48k WAV with an 880Hz pulse at every word start."""
    pulse = array("h", (int(peak * math.sin(2 * math.pi * PULSE_HZ * i
                                                  / AUDIO_RATE_HZ))
                        for i in range(int(PULSE_S * AUDIO_RATE_HZ))))
    samples = array("h", bytes(2 * (int(duration * AUDIO_RATE_HZ) + AUDIO_RATE_HZ)))
    for start in starts:
        at = int(start * AUDIO_RATE_HZ)
        samples[at:at + len(pulse)] = pulse
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(AUDIO_RATE_HZ)
        handle.writeframes(samples.tobytes())
    return path


def _synthesize_default(video: list[str], pair: tuple[Path, Path],
                        duration: float) -> None:
    """The historical 3-4s pair — argument-identical to the pre-program fixture."""
    raw, silent = pair
    pulse = "+".join(f"between(t,{start},{start + 0.02})" for start in (0.2, 1.42, 1.8, 2.92, 3.92))
    tone = f"aevalsrc='if({pulse},0.5*sin(2*PI*880*t),0)':s=48000:d={duration}"
    ffmpeg([*video, "-f", "lavfi", "-i", tone, "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ac", "2", str(raw)])
    ffmpeg([*video, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(silent)])


def _synthesize_longform(root: Path, video: list[str], pair: tuple[Path, Path],
                         program: dict) -> None:
    """1080p program footage whose audio is only ever loud where speech is."""
    raw, silent = pair
    starts = [word["start"] for row in program["transcript"]["transcript"]
              for word in row["words"]]
    duration = program["meta"]["sourceDurationS"]
    wav = _pulse_track(root / "pulses.wav", starts, duration, PROGRAM_PULSE_PEAK)
    fast = ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart"]
    bed = f"aevalsrc='{VOICE_BED_EXPR}':s=48000:d={duration + 1}"
    bed_input = ["-f", "lavfi", "-i", bed]
    if program["meta"].get("testProgramVariant") == BODY_PROGRAM:
        from _guided_body_audio import write_calibration_bed
        bed_path = root / "TEST-non-speech-calibration.wav"
        write_calibration_bed(bed_path, duration + 1)
        bed_input = ["-i", str(bed_path)]
    ffmpeg([*video, "-i", str(wav), *bed_input,
            "-filter_complex", "[1:a][2:a]amix=inputs=2:duration=first:normalize=0[a]",
            "-map", "0:v", "-map", "[a]", "-shortest", *fast, "-c:a", "aac", "-ac", "2",
            str(raw)], LONGFORM_TIMEOUT_S)
    ffmpeg([*video, *fast, str(silent)], LONGFORM_TIMEOUT_S)
    wav.unlink()


def _probed_fields(snapshot_path: str) -> dict:
    """Actual probed geometry/clock/audio facts, mirroring ingest_admitted_sources._source_entry."""
    probe = probe_media(snapshot_path)
    return {"fps": probe.fps, "frameRate": probe.frame_rate, "vfr": probe.vfr,
            "resolution": [probe.width, probe.height], "rotation": probe.rotation,
            "audio": {"present": probe.audio_present, "channels": probe.audio_channels,
                      "sampleRate": probe.audio_sample_rate}}


def media_manifest(root: Path, duration: float = 4, canvas: str = "160x90",
                   program: dict | None = None) -> dict:
    """Create NTSC tone/video and silent footage; retain real admitted hashes."""
    if canvas not in ("160x90", "1920x1080"):
        raise ValueError("Synthetic fixture canvas must be an explicitly supported source size")
    source = root / "source"
    source.mkdir(exist_ok=True)
    raw, silent = root / "tone.mp4", root / "silent.mp4"
    video = ["-f", "lavfi", "-i", f"testsrc2=size={canvas}:rate=30000/1001:duration={duration}"]
    started = time.monotonic()
    if program is None:
        _synthesize_default(video, (raw, silent), duration)
    else:
        _synthesize_longform(root, video, (raw, silent), program)
        print(f"[fixture] synthesized {duration}s {canvas} pair in "
              f"{time.monotonic() - started:.2f}s "
              f"({raw.stat().st_size} + {silent.stat().st_size} bytes)")
    admitted = admit_ingest_candidates(collect_ingest_candidates([raw, silent], None, None), source, admission_fixture)
    rows = []
    for index, original in enumerate((raw, silent)):
        row = admitted.media_by_original[str(original)]
        rows.append({"id": "raw-1" if index == 0 else "silent", "duration": duration,
                     "path": row.snapshot_path, "originalPath": row.original_path,
                     "sourceSha256": row.sha256, "admissionReceiptPath": row.receipt_path,
                     "admissionReceiptSha256": row.receipt_sha256, **_probed_fields(row.snapshot_path),
                     **({"transcriptPath": "raw.transcript.json"} if index == 0 else {})})
    manifest = {"sources": rows, "sourceSetAdmission": admitted.binding}
    (source / "asset_manifest.json").write_text(json.dumps(manifest))
    return manifest


def input_fixture(root: Path, scale: float = 1, lead: int = 100, speed: float = 1) -> tuple[dict, Path]:
    """Bind an isolated synthetic plan to structurally valid request fixtures."""
    root = root.resolve()
    manifest = media_manifest(root)
    producer = root / "producer"
    producer.mkdir(exist_ok=True)
    plan = {"cutTrack": [{"sourceId": "raw-1", "start": 0, "end": 1},
                         {"sourceId": "raw-1", "start": 1.5, "end": 3, "audioLeadMs": lead},
                         {"sourceId": "silent", "start": 0, "end": 1},
                         {"sourceId": "raw-1", "start": 3.5, "end": 4}],
            "cutDecisions": {"schemaVersion": 1, "removals": []}}
    for cut in plan["cutTrack"]:
        cut["speed"] = speed
    if lead == 0:
        plan["cutTrack"][1].pop("audioLeadMs")
    plan_path = producer / "edit_plan.json"
    plan_path.write_text(json.dumps(plan))
    plan_hash = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    receipt_paths = [producer / ".sniper-cut-approval.json", producer / ".sniper-cut-review-approved.json"]
    for target in receipt_paths:
        target.write_text('{"testOnly":true}')
    hashes = [hashlib.sha256(target.read_bytes()).hexdigest() for target in receipt_paths]
    projection = build_projection(plan, plan_hash)
    projection_raw = json.dumps(projection).encode()
    projection_hash = hashlib.sha256(projection_raw).hexdigest()
    lock = {"approvedCutPlanHash": plan_hash, "cutAuthorityDigest": "a" * 64,
            "cutApprovalReceiptHash": hashes[0], "cutReviewApprovalReceiptHash": hashes[1],
            "timelineMapHash": projection["timelineMapHash"], "projectionReceiptHash": projection_hash,
            "manifestHash": hashlib.sha256((root / "source/asset_manifest.json").read_bytes()).hexdigest()}
    lock_raw = json.dumps(lock).encode()
    lock_hash = hashlib.sha256(lock_raw).hexdigest()
    for name, key, raw in (("picture_locks", lock_hash, lock_raw), ("compatibility_projections", projection_hash, projection_raw)):
        directory = producer / name
        directory.mkdir(exist_ok=True)
        (directory / f"{key}.json").write_bytes(raw)
    request = {"schemaVersion": 1, "requestKey": "b" * 64, "planHash": plan_hash,
               "authorityDigest": "c" * 64, "pictureLockHash": lock_hash,
               **{key: lock[key] for key in ("cutAuthorityDigest", "cutApprovalReceiptHash", "cutReviewApprovalReceiptHash", "timelineMapHash", "projectionReceiptHash")},
               "createdAt": "2026-09-06T01:00:00.000Z"}
    request["requestHash"] = digest(request)
    value = {"schemaVersion": 1, "request": request, "producerDir": str(producer),
             "planPath": str(plan_path), "manifestPath": str(root / "source/asset_manifest.json"),
             "runId": "synthetic-preview", "attempt": 2, "pipelineDigest": None,
             "proxyScale": scale, "timeoutSeconds": 60, "createdAt": request["createdAt"], "executionNonce": str(uuid.uuid4())}
    keys = ("runId", "attempt", "createdAt", "executionNonce", "proxyScale", "pipelineDigest")
    value["executionKey"] = digest({"requestHash": request["requestHash"], **{key: value[key] for key in keys}})
    output = producer / "cut-previews" / request["requestHash"] / value["executionKey"]
    output.mkdir(parents=True)
    write_new(output / "input.json", value)
    return value, output


def write_program_files(root: Path, program: dict) -> None:
    """Author the Python-first program: intent, transcript, previsual plan, treatment.

    With ``--program`` this fixture is the authority for these files, so nothing
    may be required to exist first and every one is overwritten. The treatment
    is TEST-ONLY authored copy (``_guided_longform_treatment``), not creative
    approval — the TS guided fixture compiles it into a v4 proposal.
    """
    # local: the treatment module pulls the graphics catalog/planner stack, and
    # the default 3-second path must not change at all.
    from _guided_longform_treatment import (build_treatment, program_beats,
                                            write_treatment)
    producer, source = root / "producer", root / "source"
    producer.mkdir(parents=True, exist_ok=True)
    source.mkdir(parents=True, exist_ok=True)
    (root / "project.json").write_text(json.dumps(project_intent(program)))
    (source / "raw.transcript.json").write_text(json.dumps(program["transcript"]))
    (producer / "edit_plan.json").write_text(json.dumps(program_plan(program)))
    beats, allocation = program_beats(program)
    write_treatment(str(source / "test-treatment.json"),
                    build_treatment(program, beats, allocation))


def bind_transcript(root: Path, manifest: dict) -> None:
    """Join the synthetic transcript to the exact admitted media bytes."""
    transcript_file = root / "source/raw.transcript.json"
    source_row = manifest["sources"][0]
    source_path = Path(source_row["path"])
    # This is synthetic test text, not a claim that an ASR transcribed the tone.
    observation = observe_source(source_path, (source_row["sourceSha256"], source_path.stat().st_size))
    transcript_file.write_text(json.dumps(bind_result(json.loads(transcript_file.read_text()), observation)))


def main() -> None:
    """Write one fixture root: the 3s default, or the ~96s longform program."""
    arguments = argparse.ArgumentParser(description="TEST ONLY real synthetic source and admission")
    arguments.add_argument("root", type=Path)
    arguments.add_argument("--canvas", choices=("160x90", "1920x1080"), default="160x90")
    arguments.add_argument("--program", choices=tuple(PROGRAM_BUDGET_S), default=None,
                           help="author a full long-form program instead of the 3s stub")
    parsed = arguments.parse_args()
    fixture_root = parsed.root.resolve()
    if parsed.program is None:
        fixture_manifest = media_manifest(fixture_root, 3, parsed.canvas)
        bind_transcript(fixture_root, fixture_manifest)
        return
    program = build_program(PROGRAM_BUDGET_S[parsed.program],
                            BODY_PROGRAM if parsed.program == BODY_PROGRAM else None)
    write_program_files(fixture_root, program)
    fixture_manifest = media_manifest(
        fixture_root, program["meta"]["sourceDurationS"], "1920x1080", program)
    bind_transcript(fixture_root, fixture_manifest)
    print(f"[fixture] {parsed.program}: "
          f"source={program['meta']['sourceDurationS']}s "
          f"output={program['meta']['outputDurationS']}s "
          f"cuts={len(program['cutTrack'])} at {fixture_root}")


if __name__ == "__main__":
    main()
