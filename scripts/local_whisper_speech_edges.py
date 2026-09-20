"""Measured speech edges for locally transcribed words.

whisper.cpp is run one token per segment (``-ml 1 -sow``), and its token times are
contiguous by construction: every word's end is the next word's start. Nothing
downstream can then see a pause, because a pause is a GAP between words — so the
pause-tightening brain (``scripts/producer/edit/pause_scan.py``) proposes nothing
on a take full of real silence, and a trim-only edit removes no dead air.

This module measures where speech actually stops and pulls each word's bounds IN to
the measured speech. It never moves a bound outward, never reorders or drops a word,
and never touches the text: it only replaces whisper's padding with the silence that
was really there. A word the measurement says is entirely silent is left exactly as it
was (mis-timed tokens are not this module's to decide).

**The gate is measured, not chosen.** A fixed threshold (ffmpeg ``silencedetect``'s
usual ``-30dB``) calls a quietly spoken word silence: in the qualification take the word
"point." peaks near −31.6 dB over a −39 dB floor, and a trim built on that gate deleted
it. So each file's own noise floor is measured (its quietest frames) and speech is
anything ``FLOOR_MARGIN_DB`` above that, bounded so no take can gate louder than the old
constant or quieter than ``MIN_GATE_DB``.
"""

from __future__ import annotations

import math
import os
import subprocess
from typing import Iterable

FRAME_S = 0.02          # frame length for the level measurement
MIN_SILENCE_S = 0.08    # measure short gaps too; the trim brain keeps its own threshold
MIN_WORD_S = 0.04       # never shrink a word below this
FLOOR_MARGIN_DB = 8.0   # speech is this far above the file's own noise floor
MAX_GATE_DB = -30.0     # never gate louder than ffmpeg silencedetect's usual constant
MIN_GATE_DB = -55.0     # nor quieter than this, whatever the floor measures
FLOOR_PERCENTILE = 10   # the quietest tenth of the take is taken to be its floor


class SpeechEdgeError(RuntimeError):
    """The audio could not be read or measured."""


def _ffmpeg() -> str:
    """The ffmpeg this install runs (the launchers put Sniper's own first)."""
    return os.environ.get("HYPERFRAMES_FFMPEG_PATH") or "ffmpeg"


def _pcm(path: str):
    """Mono 16 kHz float samples of ``path``, decoded by Sniper's own ffmpeg.

    Raises:
        SpeechEdgeError: ffmpeg could not decode the audio.
    """
    import numpy as np
    cmd = [_ffmpeg(), "-nostdin", "-hide_banner", "-loglevel", "error", "-i", path,
           "-ac", "1", "-ar", "16000", "-f", "s16le", "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, check=False)
    except OSError as exc:
        raise SpeechEdgeError(f"ffmpeg could not be run to read the audio: {exc}") from exc
    if proc.returncode != 0 or not proc.stdout:
        raise SpeechEdgeError((proc.stderr or b"").decode("utf-8", "replace").strip()[-400:]
                              or "no audio could be decoded")
    return np.frombuffer(proc.stdout, dtype="<i2").astype("float32") / 32768.0


def frame_levels(path: str) -> tuple[list[float], float]:
    """(dBFS per ``FRAME_S`` frame, the gate in dBFS measured from this file's floor).

    Raises:
        SpeechEdgeError: The audio could not be read, or is shorter than one frame.
    """
    import numpy as np
    samples = _pcm(path)
    size = int(16000 * FRAME_S)
    usable = len(samples) - len(samples) % size
    if usable < size:
        raise SpeechEdgeError("the audio is shorter than one measurement frame")
    frames = samples[:usable].reshape(-1, size)
    rms = np.sqrt(np.maximum((frames ** 2).mean(axis=1), 1e-20))
    levels = (20 * np.log10(rms)).tolist()
    floor = float(np.percentile(levels, FLOOR_PERCENTILE))
    gate = min(MAX_GATE_DB, max(MIN_GATE_DB, floor + FLOOR_MARGIN_DB))
    return levels, gate


def measure_silences(path: str, offset: float = 0.0) -> list[tuple[float, float]]:
    """Silence intervals in ``path``, on the transcript's timeline.

    Silence is every run of at least ``MIN_SILENCE_S`` whose frames all sit below the
    gate measured from this file's own noise floor.

    Args:
        path: Any media Sniper's ffmpeg can decode.
        offset: Timeline offset already applied to the transcript's word times.

    Returns:
        ``(start, end)`` pairs, in time order.

    Raises:
        SpeechEdgeError: The audio could not be read or measured.
    """
    levels, gate = frame_levels(path)
    spans: list[tuple[float, float]] = []
    run_start: int | None = None
    for index, level in enumerate([*levels, math.inf]):      # a sentinel closes the last run
        if level < gate:
            run_start = index if run_start is None else run_start
            continue
        if run_start is not None and (index - run_start) * FRAME_S >= MIN_SILENCE_S:
            spans.append((run_start * FRAME_S + offset, index * FRAME_S + offset))
        run_start = None
    return spans


def audio_end(path: str, offset: float = 0.0) -> float | None:
    """Where the audio ends, on the transcript's timeline (None if unmeasurable).

    whisper's last token can run past the end of the file (23.48 s on a 22.33 s take),
    which then reads as a cut beyond the media.
    """
    probe = os.environ.get("HYPERFRAMES_FFPROBE_PATH") or "ffprobe"
    try:
        proc = subprocess.run([probe, "-v", "error", "-show_entries", "format=duration",
                               "-of", "default=nw=1:nk=1", path],
                              capture_output=True, text=True, check=False)
        return float(proc.stdout.strip()) + offset if proc.returncode == 0 else None
    except (OSError, ValueError):
        return None


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


def tighten_speech_edges(transcript: list[dict], path: str,
                         offset: float = 0.0) -> tuple[list[dict], dict]:
    """Refine a parsed transcript's word bounds to measured speech.

    Args:
        transcript: Utterances with ``words``; refined in place when it succeeds.
        path: The audio the transcription itself read.
        offset: Timeline offset already applied to the word times.

    Returns:
        The transcript and a report for the result's provenance. ``applied`` is False
        when nothing could be measured, and the transcript is then untouched.
    """
    report = {"method": "measured-noise-floor", "frameS": FRAME_S,
              "floorMarginDb": FLOOR_MARGIN_DB, "minSilenceS": MIN_SILENCE_S,
              "clampedToAudioEnd": True, "applied": False}
    try:
        _levels, gate = frame_levels(path)
        spans = measure_silences(path, offset)
    except (SpeechEdgeError, ImportError) as exc:
        return transcript, {**report, "reason": str(exc)[-200:]}
    report["gateDbfs"] = round(gate, 2)
    words = _words(transcript)
    if not spans or not words:
        return transcript, {**report, "reason": "no silence measured" if words else "no words"}
    before = [(float(w["start"]), float(w["end"])) for w in words]
    removed = sum(_tighten(word, spans) for word in words)
    limit = audio_end(path, offset)            # nothing can be spoken after the audio ends
    if limit is not None:
        for word in words:
            if word["end"] > limit >= word["start"] + MIN_WORD_S:
                removed += word["end"] - limit
                word["end"] = round(limit, 3)
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
