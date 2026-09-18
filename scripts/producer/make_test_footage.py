#!/usr/bin/env python3
"""make_test_footage — generate REAL-SPEECH test footage for the PRODUCER e2e.

macOS-only (uses the built-in ``say`` TTS). Renders a scripted ~45s monologue —
a strong opening claim, three distinct topic beats separated by deliberate
``[[slnc]]`` pauses, filler words + a false start, and a closing payoff — to
narration audio, then muxes it over a ``testsrc2`` 1280x720@30 video of matching
length. Also writes ``<out>.ground_truth.json`` with APPROXIMATE beat/pause
timings (derived from the ``[[slnc]]`` markers + ``say``'s word rate) so the
Phase-1 e2e has something to assert against; Deepgram supplies exact word
timings when the footage is ingested.

Usage:
    make_test_footage.py [--out footage.mp4] [--text-file script.txt]
                         [--voice Samantha] [--rate 165]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ingest_probe import run_command, status, warn

# One narration string with inline ``[[slnc N]]`` pause markers (N = ms). ``say``
# renders the pauses; ``parse_script`` splits on the same markers for timing.
DEFAULT_SCRIPT = (
    "Most people completely misunderstand how consistency actually works. "
    "[[slnc 1500]] "
    "Um, so the first thing you need to know is that showing up on your worst "
    "day counts far more than being perfect on your best day. "
    "[[slnc 1200]] "
    "I was going to say willpower, but — uh, so the second thing is that your "
    "environment quietly shapes your behavior more than motivation ever will. "
    "[[slnc 1200]] "
    "And the third thing, the part almost nobody talks about, is that simply "
    "measuring your progress changes the outcome you get. "
    "[[slnc 1500]] "
    "So if you remember one thing from all of this, remember that small systems, "
    "repeated every single day, are what actually move the needle."
)

DEFAULT_VOICE = "Samantha"
DEFAULT_RATE = 165          # words/min; explicit so ground-truth timing is derivable
VIDEO_SIZE = "1280x720"
VIDEO_FPS = 30
_SLNC_RE = re.compile(r"\[\[slnc\s+(\d+)\]\]")


@dataclass
class Beat:
    """One speakable chunk of the monologue plus the pause that follows it."""

    index: int
    text: str
    pause_ms: int


def fail(msg: str) -> None:
    """Emit an ``{"error": ...}`` line and exit 1 (sibling-worker contract)."""
    print(json.dumps({"error": msg}), flush=True)
    sys.exit(1)


def parse_script(script: str) -> list[Beat]:
    """Split a script on ``[[slnc N]]`` markers into ordered beats.

    Args:
        script: Narration text with inline pause markers.

    Returns:
        Beats in order; ``pause_ms`` is the marker following each beat (0 for
        the last). Empty text fragments are dropped.
    """
    parts = _SLNC_RE.split(script)          # [text, ms, text, ms, ..., text]
    beats: list[Beat] = []
    for i in range(0, len(parts), 2):
        text = parts[i].strip()
        pause = int(parts[i + 1]) if i + 1 < len(parts) else 0
        if text:
            beats.append(Beat(index=len(beats), text=text, pause_ms=pause))
    return beats


def estimate_ground_truth(beats: list[Beat], rate_wpm: int) -> tuple[list[dict], float]:
    """Approximate each beat's output-time window from word count + pauses.

    Returns ``(entries, total_s)``. Timings are estimates: real speech has
    per-utterance overhead ``say`` does not expose, so the measured duration
    will run a little longer.
    """
    sec_per_word = 60.0 / rate_wpm
    cursor = 0.0
    entries: list[dict] = []
    for beat in beats:
        words = len(beat.text.split())
        speak_s = words * sec_per_word
        entries.append({
            "beat": beat.index,
            "text": beat.text,
            "words": words,
            "approxStartS": round(cursor, 2),
            "approxEndS": round(cursor + speak_s, 2),
            "pauseAfterS": round(beat.pause_ms / 1000.0, 3),
        })
        cursor += speak_s + beat.pause_ms / 1000.0
    return entries, cursor


def _voice_available(voice: str) -> bool:
    """True if ``say`` lists a voice whose name matches ``voice`` exactly."""
    try:
        out = run_command(["say", "-v", "?"])
    except RuntimeError:
        return False
    return any(line.split() and line.split()[0] == voice
               for line in out.splitlines())


def synth_audio(script: str, voice: Optional[str], rate: int, aiff_path: str) -> None:
    """Render the narration to an AIFF via ``say`` (system voice if None)."""
    cmd = ["say"]
    if voice:
        cmd += ["-v", voice]
    cmd += ["-r", str(rate), "-o", aiff_path, script]
    run_command(cmd)


def ffprobe_duration(path: str) -> float:
    """Container duration in seconds via ffprobe."""
    out = run_command([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=nokey=1:noprint_wrappers=1", path,
    ])
    return float(out.strip())


def build_video(aiff_path: str, out_path: Path, duration: float) -> None:
    """Mux the narration over a testsrc2 clip of ``duration`` → 48k stereo AAC."""
    run_command([
        "ffmpeg", "-v", "error",
        "-f", "lavfi",
        "-i", f"testsrc2=size={VIDEO_SIZE}:rate={VIDEO_FPS}:duration={duration:.3f}",
        "-i", aiff_path,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(VIDEO_FPS),
        "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "192k",
        "-shortest", str(out_path), "-y",
    ])


def _load_script(text_file: Optional[str]) -> str:
    """Return the override script (if a --text-file is given) else the default."""
    if not text_file:
        return DEFAULT_SCRIPT
    path = Path(text_file).expanduser()
    if not path.exists():
        fail(f"text file not found: {path}")
    return path.read_text()


def _resolve_voice(requested: str) -> Optional[str]:
    """Requested voice if installed, else None (system default) with a warning."""
    if _voice_available(requested):
        return requested
    warn(f"voice {requested!r} unavailable; using system default")
    return None


def _render(script: str, voice: Optional[str], rate: int, out_path: Path) -> float:
    """Synthesize + mux; returns the measured audio duration. Cleans the AIFF."""
    fd, aiff = tempfile.mkstemp(suffix=".aiff", prefix="producer-say-")
    os.close(fd)
    try:
        status(status="synthesizing", voice=voice or "default", rate=rate)
        synth_audio(script, voice, rate, aiff)
        audio_dur = ffprobe_duration(aiff)
        status(status="muxing", audioDurationS=round(audio_dur, 2))
        build_video(aiff, out_path, audio_dur)
    finally:
        if os.path.exists(aiff):
            os.unlink(aiff)
    return audio_dur


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate real-speech PRODUCER test footage")
    parser.add_argument("--out", default="footage.mp4", help="output mp4 path")
    parser.add_argument("--text-file", default=None, help="override script (with [[slnc]] markers)")
    parser.add_argument("--voice", default=DEFAULT_VOICE, help="`say` voice name")
    parser.add_argument("--rate", type=int, default=DEFAULT_RATE, help="speech words/min")
    args = parser.parse_args()

    if sys.platform != "darwin":
        fail("make_test_footage requires macOS (uses the `say` command)")
    if shutil.which("say") is None:
        fail("`say` not found on PATH (macOS text-to-speech)")

    script = _load_script(args.text_file)
    beats = parse_script(script)
    if not beats:
        fail("no speakable text found in script")

    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    measured = _render(script, _resolve_voice(args.voice), args.rate, out_path)

    entries, est_total = estimate_ground_truth(beats, args.rate)
    gt_path = out_path.parent / f"{out_path.stem}.ground_truth.json"
    gt_path.write_text(json.dumps({
        "approximate": True,
        "note": ("Timings estimated from say word-rate + [[slnc]] pauses; "
                 "Deepgram provides exact word timings at ingest."),
        "voice": args.voice,
        "rateWpm": args.rate,
        "estimatedTotalS": round(est_total, 2),
        "measuredDurationS": round(measured, 2),
        "beats": entries,
    }, indent=2))

    status(status="done", footage=str(out_path), groundTruth=str(gt_path),
           measuredDurationS=round(measured, 2), beats=len(entries))


if __name__ == "__main__":
    main()
