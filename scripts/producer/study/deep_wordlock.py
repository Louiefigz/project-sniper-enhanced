#!/usr/bin/env python3
"""deep_wordlock — P5: every event's distance to the nearest word boundary.

The NATEHERK finding (word-locked seams) as a MEASUREMENT: for each detected
event, how far is it from the nearest spoken-word boundary? A pro edit reads
median |dt| near zero with most events inside 150ms; a sloppy one drifts.
Boundary arithmetic is REUSED from ``planner/word_lock.py`` (the exact code
the producer's own seam-snapper runs) — study and production can't diverge.

Words come from (in order): an explicit ``--transcript`` (word-timing JSON
or a YouTube-style ``.vtt`` with ``<c>`` word tags), an existing
``<out_dir>/transcript.json``, a SIBLING ``.vtt`` auto-discovered next to
the video (``<stem>*.vtt`` — no API needed; LL-013), or a fresh run of
``scripts/transcribe.py`` (Deepgram — the ONLY off-machine step, taken only
when DEEPGRAM_API_KEY is set, mirroring study_transcribe). With no source
available the stats carry a loud ``skipped`` reason instead of failing the
deterministic passes.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from planner.word_lock import off_boundary_s, word_boundaries  # noqa: E402
from study.deep_config import DEEP  # noqa: E402
from study.study_transcribe import (  # noqa: E402
    _flatten_words, _parse_done_line, _transcribe_script)


_VTT_TAG = re.compile(r"(<[^>]*>)")   # format tokenizer, not semantics


def _vtt_ts(token: str) -> float:
    """``HH:MM:SS.mmm`` → seconds (arithmetic split)."""
    hours, minutes, seconds = token.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _is_ts_tag(piece: str) -> bool:
    """True for an inline ``<HH:MM:SS.mmm>`` word-timing tag."""
    if not (piece.startswith("<") and piece.endswith(">")):
        return False
    inner = piece[1:-1]
    return inner.count(":") == 2 and \
        inner.replace(":", "").replace(".", "").isdigit()


def _vtt_line_words(line: str, t0: float, t1: float) -> list[dict]:
    """Words of one ``<c>``-tagged payload line.

    Grammar: ``word<t><c> word</c><t><c> word</c>…`` — a leading word starts
    at the cue start, each inline timestamp starts the next word and ends
    the previous one, and the cue end closes the last word.
    """
    words: list[dict] = []
    t = t0
    for piece in _VTT_TAG.split(line):
        if _is_ts_tag(piece):
            t = _vtt_ts(piece[1:-1])
            if words:
                words[-1]["end"] = t
            continue
        if piece.startswith("<"):
            continue                     # <c> / </c> markup
        for token in piece.split():
            words.append({"word": token, "start": t, "end": t})
    if words:
        words[-1]["end"] = t1
    return words


def parse_vtt_words(path: str) -> list[dict]:
    """Word timings from a YouTube-style VTT (inline ``<c>`` word tags).

    Only lines carrying inline word timing contribute — the roll-up repeat
    lines (the previous cue re-printed as static text) hold no NEW words.
    Fails loudly when the file carries no word-level tags at all: cue-level
    captions cannot feed a WORD lock (no fallback matching).
    """
    words: list[dict] = []
    t0 = t1 = None
    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if "-->" in line:
                head, _, tail = line.partition("-->")
                t0 = _vtt_ts(head.strip().split()[0])
                t1 = _vtt_ts(tail.strip().split()[0])
                continue
            if "<c>" in line and t0 is not None:
                words.extend(_vtt_line_words(line, t0, t1))
    if not words:
        raise ValueError(
            f"no <c> word timings found in VTT {path} — the word lock "
            "needs word-level cues (YouTube 'auto' VTT format)")
    return words


def _sibling_vtt(video: str) -> "str | None":
    """The first ``<stem>*.vtt`` sitting next to the video (sorted), or None."""
    stem = os.path.splitext(os.path.basename(video))[0]
    folder = os.path.dirname(os.path.abspath(video))
    names = sorted(n for n in os.listdir(folder)
                   if n.startswith(stem) and n.endswith(".vtt"))
    return os.path.join(folder, names[0]) if names else None


def _words_from_payload(payload) -> list[dict]:
    """Words from either a transcript payload dict or a bare word list."""
    if isinstance(payload, dict):
        return _flatten_words(payload.get("transcript") or [])
    if isinstance(payload, list) and payload and "words" in payload[0]:
        return _flatten_words(payload)
    if isinstance(payload, list):
        return [w for w in payload if isinstance(w, dict) and "start" in w]
    return []


def _transcribe(video: str, cache_path: str) -> "dict | None":
    """Run the Deepgram worker and cache its payload next to the study."""
    script = _transcribe_script()
    if not os.path.exists(script):
        return None
    proc = subprocess.run([sys.executable, script, video],
                          capture_output=True, text=True, timeout=1800)
    payload = _parse_done_line(proc.stdout)
    if payload is None:
        return None
    with open(cache_path, "w") as handle:
        json.dump(payload, handle)
    return payload


def _words_from_file(path: str) -> list[dict]:
    """Words from an explicit transcript file — VTT by extension, else JSON."""
    if path.endswith(".vtt"):
        return parse_vtt_words(path)
    with open(path) as handle:
        words = _words_from_payload(json.load(handle))
    if not words:
        raise ValueError(f"no words found in transcript {path}")
    return words


def load_words(video: str, out_dir: str,
               transcript_path: "str | None") -> tuple[list[dict], dict]:
    """(words, meta) for P5 — see the module docstring for the source order."""
    cache = os.path.join(out_dir, "transcript.json")
    path = transcript_path or (cache if os.path.isfile(cache) else None)
    if path is not None:
        return _words_from_file(path), \
            {"transcriptPath": os.path.abspath(path)}
    vtt = _sibling_vtt(video)
    if vtt is not None:
        return parse_vtt_words(vtt), \
            {"transcriptPath": os.path.abspath(vtt), "source": "vtt-sibling"}
    if not os.environ.get("DEEPGRAM_API_KEY"):
        return [], {"skipped": "no transcript, no sibling .vtt and "
                               "DEEPGRAM_API_KEY not set"}
    payload = _transcribe(video, cache)
    if payload is None:
        return [], {"skipped": "transcribe worker returned no transcript"}
    return _words_from_payload(payload), {"transcriptPath": cache}


def word_lock_stats(events: list[dict], words: list[dict],
                    meta: dict) -> dict:
    """Per-event |dt| to the nearest word boundary + the summary stats."""
    if not words:
        return {**meta, "events": [], "medianAbsDtS": None,
                "within150msPct": None}
    boundaries = word_boundaries(words)
    tol = DEEP["word_lock_tol_s"]
    rows, dts = [], []
    for ev in events:
        dt = off_boundary_s(float(ev["t"]), boundaries)
        dts.append(dt)
        rows.append({"eventId": ev["id"], "t": ev["t"], "type": ev["type"],
                     "dtS": round(dt, 4)})
    return {**meta, "words": len(words), "toleranceS": tol, "events": rows,
            "medianAbsDtS": round(statistics.median(dts), 4) if dts else None,
            "within150msPct": round(
                100.0 * sum(1 for d in dts if d <= tol) / len(dts), 1)
            if dts else None}
