"""Measured speech edges for locally transcribed words.

whisper.cpp is run one token per segment (``-ml 1 -sow``), and its token times are
contiguous by construction: every word's end is the next word's start. Nothing
downstream can then see a pause, because a pause is a GAP between words — so the
pause-tightening brain (``scripts/producer/edit/pause_scan.py``) proposes nothing
on a take full of real silence, and a trim-only edit removes no dead air.

This module measures where speech actually stops, with the same ffmpeg
``silencedetect`` analyser the audio study already trusts
(``scripts/producer/study/study_audio.py``), and pulls each word's bounds IN to
the measured speech. It never moves a bound outward, never reorders or drops a
word, and never touches the text: it only replaces whisper's padding with the
silence that was really there. A word that the measurement says is entirely
silent is left exactly as it was (mis-timed tokens are not this module's to
decide), and if anything would invert a word the whole refinement is dropped.
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import Iterable

NOISE_DB = "-30dB"      # study_audio.SILENCE_NOISE_DB — the same amplitude gate
MIN_SILENCE_S = 0.08    # measure short gaps too; the trim brain keeps its own threshold
MIN_WORD_S = 0.04       # never shrink a word below this
_START = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?)")
_END = re.compile(r"silence_end:\s*(-?\d+(?:\.\d+)?)")


class SpeechEdgeError(RuntimeError):
    """The silence measurement could not be run or parsed."""


def _ffmpeg() -> str:
    """The ffmpeg this install runs (the launchers put Sniper's own first)."""
    return os.environ.get("HYPERFRAMES_FFMPEG_PATH") or "ffmpeg"


def measure_silences(wav_path: str, offset: float = 0.0) -> list[tuple[float, float]]:
    """Silence intervals in ``wav_path``, shifted onto the transcript's timeline.

    Args:
        wav_path: 16 kHz PCM extracted for transcription.
        offset: Timeline offset already applied to the transcript's word times.

    Returns:
        ``(start, end)`` pairs, in order. An unterminated final silence runs to
        the end of the file and is closed by the caller's last word bound.

    Raises:
        SpeechEdgeError: ffmpeg could not be run.
    """
    cmd = [_ffmpeg(), "-nostdin", "-hide_banner", "-i", wav_path,
           "-af", f"silencedetect=noise={NOISE_DB}:d={MIN_SILENCE_S}", "-f", "null", "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise SpeechEdgeError(f"ffmpeg could not be run for silence measurement: {exc}") from exc
    if proc.returncode != 0:
        raise SpeechEdgeError((proc.stderr or "").strip()[-500:] or "silencedetect failed")
    spans: list[tuple[float, float]] = []
    start: float | None = None
    for line in (proc.stderr or "").splitlines():
        found = _START.search(line)
        if found:
            start = float(found.group(1)) + offset
        found = _END.search(line)
        if found and start is not None:
            spans.append((start, float(found.group(1)) + offset))
            start = None
    if start is not None:
        spans.append((start, float("inf")))
    return spans


def _words(transcript: Iterable[dict]) -> list[dict]:
    """Every word of every utterance, in order."""
    return [word for utt in transcript for word in utt.get("words", [])]


def _tighten(word: dict, spans: list[tuple[float, float]]) -> float:
    """Pull one word's bounds in to measured speech; return the seconds removed."""
    start, end = float(word["start"]), float(word["end"])
    for span_start, span_end in spans:
        if span_end <= start or span_start >= end:
            continue
        if span_start <= start and span_end >= end:
            return 0.0          # measured as entirely silent: leave it alone
        if span_start > start:
            end = min(end, span_start)
        if span_end < end:
            start = max(start, span_end)
    if end - start < MIN_WORD_S:
        return 0.0
    removed = (float(word["end"]) - float(word["start"])) - (end - start)
    word["start"], word["end"] = round(start, 3), round(end, 3)
    return max(0.0, removed)


def tighten_speech_edges(transcript: list[dict], wav_path: str,
                         offset: float = 0.0) -> tuple[list[dict], dict]:
    """Refine a parsed transcript's word bounds to measured speech.

    Args:
        transcript: Utterances with ``words``; refined in place when it succeeds.
        wav_path: The PCM the transcription itself read.
        offset: Timeline offset already applied to the word times.

    Returns:
        The transcript and a report for the result's provenance. The report's
        ``applied`` is False when nothing could be measured, and the transcript
        is then returned untouched.
    """
    report = {"method": "ffmpeg-silencedetect", "noiseDb": NOISE_DB,
              "minSilenceS": MIN_SILENCE_S, "applied": False}
    try:
        spans = measure_silences(wav_path, offset)
    except SpeechEdgeError as exc:
        return transcript, {**report, "reason": str(exc)[-200:]}
    words = _words(transcript)
    if not spans or not words:
        return transcript, {**report, "reason": "no silence measured" if words else "no words"}
    before = [(float(w["start"]), float(w["end"])) for w in words]
    removed = sum(_tighten(word, spans) for word in words)
    for (start, end), word in zip(before, words):        # only ever pulled inward
        if word["start"] < start or word["end"] > end or word["end"] <= word["start"]:
            for (old_start, old_end), item in zip(before, words):
                item["start"], item["end"] = old_start, old_end
            return transcript, {**report, "reason": "refinement would move a bound outward"}
    gaps = sum(1 for a, b in zip(words, words[1:]) if b["start"] - a["end"] > 0)
    return transcript, {**report, "applied": True, "silenceSpans": len(spans),
                        "wordsTightened": sum(
                            1 for (start, end), word in zip(before, words)
                            if word["start"] != start or word["end"] != end),
                        "gapsOpened": gaps, "silenceExposedS": round(removed, 3)}
