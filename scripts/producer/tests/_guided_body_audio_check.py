"""Bounded actual TEST calibration→source AAC→PCM master→AAC audio evidence.

No video, ingest/source authority, ASR, words heard, or human approval is proved.
The applicable audio-only Audit B rows and complete delivery measurements run
on the actual final AAC, never on declared signal parameters alone.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

from _cut_preview_fixture import PROGRAM_PULSE_PEAK, _pulse_track
from _guided_body_audio import write_calibration_bed
from _guided_body_program import BODY_PROGRAM
from _guided_longform_program import build_program
from audio.audio_mix_delivery import measure_delivery
from audio.master import build_pass2_afilter, measure_loudness
from audit.audio_quality import _channel_result, _decode_stereo, _ending_result, _hum_result
from cut_preview_io import file_hash
from guided_body_execution import body_clock
from palmier.process_deadline import process_timeout, use_process_deadline


def _ffmpeg(args: list[str]) -> None:
    """One non-network child, charged to the original shared test deadline."""
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-err_detect", "explode",
        "-n", *args], check=True, capture_output=True, timeout=process_timeout())


def _source(root: Path, duration: float, starts: list[float]) -> Path:
    """Exact TEST bed/pulse mix used by the new fixture, encoded once as source."""
    bed = root / "TEST-non-speech-calibration.wav"
    write_calibration_bed(bed, duration + 1, process_timeout)
    pulses = _pulse_track(root / "pulses.wav", starts, duration, PROGRAM_PULSE_PEAK)
    source = root / "source.m4a"
    _ffmpeg(["-i", str(pulses), "-i", str(bed), "-filter_complex",
        "[0:a][1:a]amix=inputs=2:duration=first:normalize=0[a]", "-map", "[a]",
        "-t", str(duration), "-c:a", "aac", "-ac", "2", str(source)])
    return source


def _master(root: Path, source: Path, duration: float) -> tuple[Path, dict]:
    """Use actual shared mastering math; no fabricated source-bus receipt."""
    measured = measure_loudness(str(source))
    chain, note = build_pass2_afilter(str(source), None, measured)
    master = root / "program-master.wav"
    chain += f",aresample=48000,atrim=end_sample={round(duration * 48000)},asetpts=PTS-STARTPTS"
    _ffmpeg(["-i", str(source), "-af", chain, "-c:a", "pcm_f32le", str(master)])
    measurement = measure_delivery(str(master))
    if not measurement["qualified"]:
        raise RuntimeError(f"TEST full PCM mastering rejected: {measurement}")
    return master, {"chain": chain, "note": note, "measurement": measurement}


def qualify(root: Path, duration: float, starts: list[float]) -> dict:
    """Retain actual full-duration outcomes including failures; at most120s work."""
    clock, started = body_clock(120), time.monotonic()
    evidence = {"scope": "TEST-non-speech-audio-calibration-not-listening-or-approval",
        "durationSeconds": duration, "videoTimingQualified": False, "status": "failed"}
    try:
        with use_process_deadline(clock):
            source = clock.phase("source-AAC", lambda: _source(root, duration, starts))
            master, proof = clock.phase("full-PCM-master", lambda: _master(root, source, duration))
            final = root / "delivery.m4a"
            clock.phase("delivery-AAC", lambda: _ffmpeg(["-i", str(master), "-c:a", "aac", "-ar", "48000", str(final)]))
            delivery = clock.phase("full-AAC-delivery-measurement", lambda: measure_delivery(str(final)))
            checks = clock.phase("whole-audio-QC", lambda: audio_checks(final))
            evidence.update({"master": proof, "delivery": delivery, "checks": checks,
                "final": {"path": str(final), "sha256": file_hash(final)}})
            if not delivery["qualified"] or any(row["status"] != "pass" for row in checks):
                raise RuntimeError("TEST final AAC failed real delivery/audio-only QC")
            clock.remaining()
            evidence["status"] = "complete"
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        evidence["error"] = str(error)
        raise
    finally:
        evidence.update({"elapsedMs": round((time.monotonic() - started) * 1000), "stages": clock.events})
        (root / "TEST-audio-evidence.json").write_text(json.dumps(evidence, indent=2))
    return evidence


def audio_checks(path: Path) -> list[dict]:
    """Same actual decoded samples/checks as Audit B, excluding nonexistent video."""
    samples = _decode_stereo(str(path))
    if samples is None or not len(samples):
        raise RuntimeError("TEST full AAC decode produced no samples")
    return [asdict(row) for row in (_channel_result(samples), _hum_result(samples), _ending_result(samples, {}))]


def main() -> None:
    """Run the short probe or actual entire new source signal without any video."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    program = build_program(312, BODY_PROGRAM)
    duration = program["meta"]["sourceDurationS"] if args.full else 12.0
    starts = [word["start"] for row in program["transcript"]["transcript"]
              for word in row["words"] if word["start"] < duration - 0.02]
    root = Path(tempfile.mkdtemp(prefix="sniper-body-audio-", dir="/private/tmp"))
    print(f"TEST retained root: {root}", flush=True)
    print(json.dumps(qualify(root, duration, starts), indent=2))


if __name__ == "__main__":
    main()
