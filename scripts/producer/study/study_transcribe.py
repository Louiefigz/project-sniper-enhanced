#!/usr/bin/env python3
"""study_transcribe — optional speech fingerprint for the STUDY verb.

When ``--transcribe`` is passed, the reference's own words become part of the
fingerprint: the *rate* it's delivered at (words/min — a huge stylistic tell,
fast-cut shorts often run 180-220 wpm) and the *hook* (the exact words in the
first few seconds, the line the brain will study for opening cadence).

This shells out to the existing ``scripts/transcribe.py`` worker rather
than re-implementing transcription — it emits a final ``{"status":"done",
"transcript":[...],"duration":..}`` NDJSON line we parse. Requires
an installed local Whisper runtime by default. Local failure is reported as
skipped, never paid fallback. Paid ASR additionally requires explicit invocation
authorization; a key or ``--transcribe`` alone never authorizes an upload.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Callable

HOOK_WINDOW_S = 3.0     # words spoken within this many seconds = the "hook"


def _transcribe_script() -> str:
    """Absolute path to scripts/transcribe.py (one level up from producer/)."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(os.path.dirname(here)), "transcribe.py")


sys.path.insert(0, os.path.dirname(_transcribe_script()))
from asr_policy import (add_asr_arguments, child_asr_arguments,  # noqa: E402,F401
                        invocation_from_options, transcription_environment,
                        use_asr_invocation, transcription_provider, LOCAL_PROVIDER)
from local_asr_deadline import LocalAsrDeadline, use_local_asr_deadline  # noqa: E402
from producer.headless.process_runner import ProcessRequest, run_text  # noqa: E402
from transcribe_output import parse_transcription_output  # noqa: E402

STUDY_TIMEOUT_SECONDS = 1800
MAX_WORKER_OUTPUT_BYTES = 16 * 1024 * 1024


def study_deadline(parent: LocalAsrDeadline | None = None) -> LocalAsrDeadline:
    """Retain the existing study ceiling and any tighter caller/active expiry."""
    expires = time.monotonic() + STUDY_TIMEOUT_SECONDS
    if parent is not None and type(parent) is not LocalAsrDeadline:
        raise RuntimeError("study local ASR requires a LocalAsrDeadline parent")
    if parent is not None:
        expires = min(expires, parent.expires_at)
    return LocalAsrDeadline.start(parent_expires_at=expires)


def _local_worker(video_path: str, deadline: LocalAsrDeadline) -> subprocess.CompletedProcess:
    """Own the whole local worker session; leaves explicitly share its group."""
    script = _transcribe_script()
    deadline.guard()
    args = (sys.executable, script, video_path, *child_asr_arguments(),
            "--local-asr-expires-at", repr(deadline.expires_at), "--local-asr-owned-worker")
    request = ProcessRequest(args, "", os.path.dirname(script), transcription_environment(),
                             deadline.remaining(), max_output_bytes=MAX_WORKER_OUTPUT_BYTES)
    result = run_text(request)
    deadline.guard()
    return result


def _parse_done_line(stdout: str, guard: Callable[[], None] | None = None) -> dict | None:
    """Accept exactly one terminal payload only after the entire stream validates."""
    try:
        return parse_transcription_output(stdout, guard)
    except RuntimeError:
        return None


def _flatten_words(transcript: list[dict]) -> list[dict]:
    """All word dicts across every utterance, in time order."""
    words: list[dict] = []
    for entry in transcript:
        words.extend(entry.get("words") or [])
    return words


def _local_payload(video_path: str, deadline: LocalAsrDeadline | None) -> dict:
    """Hold one study clock through owned cleanup and final response parsing."""
    with use_local_asr_deadline(study_deadline(deadline)) as held:
        proc = _local_worker(video_path, held)
        payload = _worker_payload(proc, held.guard)
        held.guard()
        return payload


def run_transcribe_worker(video_path: str, deadline: LocalAsrDeadline | None = None) -> dict:
    """Shared local-default study worker; failures never select a paid provider."""
    try:
        if transcription_provider() == LOCAL_PROVIDER:
            return _local_payload(video_path, deadline)
        proc = subprocess.run([sys.executable, _transcribe_script(), video_path, *child_asr_arguments()],
                              capture_output=True, text=True, timeout=STUDY_TIMEOUT_SECONDS,
                              env=transcription_environment())
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        return {"skipped": f"transcription unavailable: {exc}"}
    return _worker_payload(proc)


def _worker_payload(proc: subprocess.CompletedProcess, guard: Callable[[], None] | None = None) -> dict:
    """Never accept partial or failed worker output as a transcript."""
    if proc.returncode != 0:
        return {"skipped": f"transcription failed (exit {proc.returncode})",
                "stderrTail": proc.stderr[-300:], "workerTail": proc.stdout[-1000:]}
    payload = _parse_done_line(proc.stdout, guard)
    if payload is None:
        return {"skipped": "no transcript returned", "stderrTail": proc.stderr[-300:]}
    return payload


def transcribe_profile(video_path: str, deadline: LocalAsrDeadline | None = None) -> dict | None:
    """Summarize local words or an explicit unavailable reason, without fallback."""
    try:
        held = study_deadline(deadline) if transcription_provider() == LOCAL_PROVIDER else None
        payload = run_transcribe_worker(video_path, held)
        result = payload if "skipped" in payload else _summarize(payload)
        if held is not None:
            held.guard()
        return result
    except (OSError, RuntimeError, ValueError) as exc:
        return {"skipped": f"transcription unavailable: {exc}"}


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
