#!/usr/bin/env python3
"""audio_separate — Demucs source separation for the ``separate`` enhance preset.

The heavy tool for NON-steady background noise (music bleed, chatter, traffic)
that survives ``afftdn``/``arnndn``: split the dialogue bus into ``vocals`` +
``no_vocals`` stems (Demucs two-stem mode), then remix the vocals over the
residual attenuated to ``--residual-db`` (default -60 dB ≈ mute). The video
stream is COPIED bit-identical; only audio is re-encoded.

Dispatch: ``audio_enhance.run_audio_enhance`` routes preset ``"separate"``
here, so the renderer keeps a single audio-cleanup entry point. Demucs runs in
whichever Python owns the ``demucs`` package — a dedicated
``audio/.demucs-venv`` if present, else the current interpreter. The first run
downloads the model weights (~80 MB) into ``~/.cache/torch`` — expected.

CLI: audio_separate.py <video_in> <video_out> [--residual-db N]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audio.master import has_audio
from producer_config import ENCODE

DEMUCS_MODEL = "htdemucs"          # default Demucs v4 hybrid transformer
RESIDUAL_DB_DEFAULT = -60.0        # bed level for the non-vocal stem (~mute)
RESIDUAL_DB_MIN, RESIDUAL_DB_MAX = -90.0, 0.0
_VENV_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        ".demucs-venv", "bin", "python3")


def emit(event: str, **fields) -> None:
    """Emit one NDJSON status line to stdout (worker convention)."""
    print(json.dumps({"event": event, **fields}, default=str), flush=True)


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def demucs_python() -> str:
    """Interpreter that owns the ``demucs`` package (fail loudly if none).

    Prefers the dedicated ``audio/.demucs-venv`` (the escape hatch for a main
    venv whose Python has no torch wheels), else the current interpreter.
    """
    if os.path.exists(_VENV_PY):
        return _VENV_PY
    probe = _run([sys.executable, "-c", "import demucs"])
    if probe.returncode == 0:
        return sys.executable
    raise RuntimeError(
        "demucs is not installed: `pip install demucs` into the project venv, "
        "or create scripts/producer/audio/.demucs-venv (python3.12) with it")


def extract_wav(video_in: str, wav_out: str) -> dict:
    """Extract the dialogue bus as 48 kHz stereo PCM for Demucs."""
    cmd = ["ffmpeg", "-y", "-hide_banner", "-nostats", "-i", video_in,
           "-map", "0:a:0", "-ac", "2", "-ar", "48000",
           "-c:a", "pcm_s16le", wav_out]
    res = _run(cmd)
    ok = res.returncode == 0 and os.path.exists(wav_out)
    return {"ok": ok, "stderr": "" if ok else res.stderr[-600:]}


def run_demucs(wav_in: str, out_dir: str) -> dict:
    """Two-stem Demucs pass → ``out_dir/htdemucs/<name>/{vocals,no_vocals}.wav``."""
    t0 = time.time()
    cmd = [demucs_python(), "-m", "demucs", "--two-stems=vocals",
           "-n", DEMUCS_MODEL, "-o", out_dir, wav_in]
    res = _run(cmd)
    name = os.path.splitext(os.path.basename(wav_in))[0]
    stem_dir = os.path.join(out_dir, DEMUCS_MODEL, name)
    vocals = os.path.join(stem_dir, "vocals.wav")
    residual = os.path.join(stem_dir, "no_vocals.wav")
    ok = (res.returncode == 0 and os.path.exists(vocals)
          and os.path.exists(residual))
    return {"ok": ok, "vocals": vocals, "residual": residual,
            "elapsed_s": round(time.time() - t0, 1),
            "stderr": "" if ok else res.stderr[-800:]}


def remix(video_in: str, stems: dict, residual_db: float, video_out: str) -> dict:
    """Vocals + attenuated residual → one bus; video stream copied."""
    fc = (f"[2:a]volume={residual_db}dB[res];"
          "[1:a][res]amix=inputs=2:duration=first:normalize=0[aout]")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-nostats",
           "-i", video_in, "-i", stems["vocals"], "-i", stems["residual"],
           "-filter_complex", fc, "-map", "0:v:0", "-c:v", "copy",
           "-map", "[aout]", "-c:a", ENCODE["acodec"],
           "-b:a", ENCODE["audio_bitrate"], "-ar", str(ENCODE["audio_rate"]),
           "-ac", str(ENCODE["audio_channels"]),
           "-movflags", ENCODE["movflags"], video_out]
    res = _run(cmd)
    ok = res.returncode == 0 and os.path.exists(video_out)
    return {"ok": ok, "stderr": "" if ok else res.stderr[-800:]}


def run_separate(video_in: str, video_out: str,
                 residual_db: float = RESIDUAL_DB_DEFAULT) -> dict:
    """Extract → Demucs two-stem → remix. Returns a status dict."""
    if not (RESIDUAL_DB_MIN <= residual_db <= RESIDUAL_DB_MAX):
        return {"status": "error", "error": f"residual_db {residual_db} outside "
                f"[{RESIDUAL_DB_MIN}, {RESIDUAL_DB_MAX}]"}
    if not has_audio(video_in):
        return {"status": "error", "error": "input has no audio stream to separate"}
    work = tempfile.mkdtemp(prefix="producer-separate-")
    try:
        return _pipeline(video_in, video_out, residual_db, work)
    except RuntimeError as exc:
        return {"status": "error", "error": str(exc)}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _pipeline(video_in: str, video_out: str,
              residual_db: float, work: str) -> dict:
    """The staged pass, emitting one NDJSON line per stage."""
    wav = os.path.join(work, "dialogue.wav")
    ext = extract_wav(video_in, wav)
    emit("separate_extract", ok=ext["ok"])
    if not ext["ok"]:
        return {"status": "error", "error": "wav extract failed",
                "detail": ext["stderr"]}
    dem = run_demucs(wav, work)
    emit("separate_demucs", ok=dem["ok"], model=DEMUCS_MODEL,
         elapsed_s=dem["elapsed_s"])
    if not dem["ok"]:
        return {"status": "error", "error": "demucs separation failed",
                "detail": dem["stderr"]}
    mix = remix(video_in, dem, residual_db, video_out)
    emit("separate_remix", ok=mix["ok"], residual_db=residual_db)
    if not mix["ok"]:
        return {"status": "error", "error": "remix failed",
                "detail": mix["stderr"]}
    return {"status": "ok", "preset": "separate", "model": DEMUCS_MODEL,
            "residual_db": residual_db, "demucs_elapsed_s": dem["elapsed_s"],
            "out": video_out}


def main() -> None:
    ap = argparse.ArgumentParser(description="Demucs dialogue separation")
    ap.add_argument("video_in")
    ap.add_argument("video_out")
    ap.add_argument("--residual-db", type=float, default=RESIDUAL_DB_DEFAULT,
                    help="non-vocal stem level in dB (default -60 ≈ mute)")
    args = ap.parse_args()
    report = run_separate(args.video_in, args.video_out, args.residual_db)
    emit("audio_separate", **report)
    if report.get("status") != "ok":
        sys.exit(1)


if __name__ == "__main__":
    main()
