#!/usr/bin/env python3
"""study_transcribe — optional speech fingerprint for the STUDY verb.

When ``--transcribe`` is passed, the reference's own words become part of the
fingerprint: the *rate* it's delivered at (words/min — a huge stylistic tell,
fast-cut shorts often run 180-220 wpm) and the *hook* (the exact words in the
first few seconds, the line the brain will study for opening cadence).

This shells out to the existing ``scripts/transcribe.py`` Deepgram worker rather
than re-implementing transcription — it emits a final ``{"status":"done",
"transcript":[...],"duration":..}`` NDJSON line we parse. Requires
``DEEPGRAM_API_KEY``; without it we skip gracefully (the fingerprint is still
fully useful without words). This is the ONLY part of STUDY that sends audio off
the machine, and only when explicitly opted in.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

HOOK_WINDOW_S = 3.0     # words spoken within this many seconds = the "hook"


def _transcribe_script() -> str:
    """Absolute path to scripts/transcribe.py (one level up from producer/)."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(os.path.dirname(here)), "transcribe.py")


def _parse_done_line(stdout: str) -> dict | None:
    """Return the transcribe worker's final ``done`` payload, or None."""
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("status") == "done" or "transcript" in obj:
            return obj
    return None


def _flatten_words(transcript: list[dict]) -> list[dict]:
    """All word dicts across every utterance, in time order."""
    words: list[dict] = []
    for entry in transcript:
        words.extend(entry.get("words") or [])
    return words


def transcribe_profile(video_path: str) -> dict | None:
    """Run Deepgram on ``video_path`` → {wpm, wordCount, hookText, ...}.

    Returns None (with a ``skipped`` reason folded in) when the key is missing or
    the worker fails — STUDY never hard-depends on transcription.
    """
    if not os.environ.get("DEEPGRAM_API_KEY"):
        return {"skipped": "DEEPGRAM_API_KEY not set"}
    script = _transcribe_script()
    if not os.path.exists(script):
        return {"skipped": f"transcribe worker not found: {script}"}
    try:
        proc = subprocess.run([sys.executable, script, video_path],
                              capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        return {"skipped": "transcription timed out (>30min)"}
    payload = _parse_done_line(proc.stdout)
    if payload is None:
        return {"skipped": "no transcript returned", "stderrTail": proc.stderr[-300:]}
    return _summarize(payload)


def _summarize(payload: dict) -> dict:
    """Words/min + hook text from a transcribe ``done`` payload."""
    transcript = payload.get("transcript") or []
    words = _flatten_words(transcript)
    duration = float(payload.get("duration") or 0.0)
    if not words:
        text = " ".join(e.get("text", "") for e in transcript).strip()
        return {"wordCount": len(text.split()), "wpm": None,
                "hookText": text[:180], "durationS": round(duration, 2)}
    count = len(words)
    speak_span = (words[-1].get("end", 0) or 0) - (words[0].get("start", 0) or 0)
    wpm = round(count / (speak_span / 60.0), 1) if speak_span > 0 else None
    hook = [w.get("word", "") for w in words
            if (w.get("start") or 0) < HOOK_WINDOW_S]
    return {
        "wordCount": count,
        "wpm": wpm,
        "speakingSpanS": round(speak_span, 2),
        "durationS": round(duration, 2),
        "hookText": " ".join(hook).strip(),
        "language": payload.get("language"),
    }
