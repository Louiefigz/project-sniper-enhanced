#!/usr/bin/env python3
"""deep_captions — P4: the reference's CAPTION SYSTEM, measured.

Samples the whole video at a fixed low fps, OCRs each sampled frame, buckets
words into three vertical bands and calls the band whose text CHANGES most the
caption band (captions turn over constantly; titles/logos hold). From the band
observations it measures the numbers a caption doctrine needs:

* cues/min + words per cue (consecutive similar texts merge into one cue —
  stdlib difflib ratio, OCR noise tolerant),
* position band (top / middle / bottom),
* KARAOKE detection — within a cue whose text is stable, a word whose sampled
  colour shifts frame-over-frame is an active-word highlight.

Colour sampling is pixel arithmetic (bright-quartile median per word box);
the karaoke verdict is a pure function over those observations, unit-testable
without any video.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from difflib import SequenceMatcher

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from study.deep_config import DEEP, UI_CHROME_TOKENS  # noqa: E402
from study.deep_frames import VideoInfo, Window, iter_frames  # noqa: E402
from study.deep_text import _norm, ocr_words  # noqa: E402

BANDS = ("top", "middle", "bottom")


def _cue_tokens(text: str) -> list[str]:
    """Lowercased alphanumeric tokens (punctuation stripped by arithmetic)."""
    cleaned = "".join(ch if ch.isalnum() else " " for ch in text.lower())
    return cleaned.split()


def cue_is_chrome(text: str) -> bool:
    """True when a cue text reads as UI chrome / a file path, not speech.

    Two arithmetic signals (LL-012 — token membership + path-char check,
    never regex semantics): path characters (``/``, ``\\``, ``_`` — spoken
    captions practically never carry them; file paths and filenames always
    do) and membership of any token in the UI-chrome wordlist.
    """
    if "/" in text or "\\" in text or "_" in text:
        return True
    return any(tok in UI_CHROME_TOKENS for tok in _cue_tokens(text))


def chrome_cue_fraction(cue_texts: list[str]) -> float:
    """Fraction of cue texts that read as UI chrome (0.0 on an empty list)."""
    if not cue_texts:
        return 0.0
    return sum(1 for t in cue_texts if cue_is_chrome(t)) / len(cue_texts)


@dataclass
class BandObs:
    """One sampled frame's reading of one band."""

    t: float
    text: str
    words: dict = field(default_factory=dict)   # word key → (r, g, b)


def word_color(frame: np.ndarray, box: tuple) -> tuple:
    """(r, g, b) median of the word box's bright quartile — the glyph colour."""
    x, y, w, h = box
    crop = frame[max(0, y):y + h, max(0, x):x + w]
    if crop.size == 0:
        return (0, 0, 0)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    bright = crop[gray >= np.percentile(gray, 75)]
    if len(bright) == 0:
        return (0, 0, 0)
    b, g, r = np.median(bright, axis=0)
    return (int(r), int(g), int(b))


def _observe_frame(frame: np.ndarray, t: float) -> dict[str, BandObs]:
    """OCR one sampled frame into per-band observations.

    Each band is OCR'd as its own slice with the sparse-text PSM — a single
    full-frame auto-layout pass reads NOTHING off text over busy footage
    (measured on the synthetic clip), while per-band sparse OCR recovers it.
    The stricter caption confidence gate keeps footage junk from faking
    caption turnover.
    """
    height = frame.shape[0]
    obs = {}
    for bi, band in enumerate(BANDS):
        y0, y1 = bi * height // 3, (bi + 1) * height // 3
        slice_ = frame[y0:y1]
        entry = BandObs(t=t, text="")
        for w in ocr_words(slice_, psm=DEEP["ocr_psm_band"],
                           conf_min=DEEP["caption_conf_min"]):
            entry.text = (entry.text + " " + w["text"]).strip()
            key = _norm(w["text"])
            if key:
                entry.words[key] = word_color(slice_, w["box"])
        obs[band] = entry
    return obs


def collect_band_obs(video: str, info: VideoInfo) -> dict[str, list[BandObs]]:
    """Stream the video at caption fps → per-band observation series."""
    width = min(DEEP["caption_ocr_width"], info.width)
    win = Window(t0=0.0, t1=info.duration, fps=DEEP["caption_fps"], width=width)
    series: dict[str, list[BandObs]] = {band: [] for band in BANDS}
    for k, frame in enumerate(iter_frames(video, win, info, "bgr24")):
        obs = _observe_frame(frame, round(k / DEEP["caption_fps"], 3))
        for band in BANDS:
            series[band].append(obs[band])
    return series


def pick_caption_band(series: dict[str, list[BandObs]]) -> "str | None":
    """The band with the most DISTINCT non-empty texts (turnover = captions)."""
    turnover = {band: len({o.text for o in obs if o.text})
                for band, obs in series.items()}
    best = max(turnover, key=lambda b: turnover[b])
    return best if turnover[best] >= 2 else None


def _similar(a: str, b: str) -> bool:
    return SequenceMatcher(None, a, b).ratio() >= DEEP["caption_merge_ratio"]


def cues_from_obs(obs: list[BandObs]) -> list[dict]:
    """Merge consecutive similar band texts into cues (empty text = a gap)."""
    cues: list[dict] = []
    for o in obs:
        if not o.text:
            continue
        prev = cues[-1] if cues else None
        if prev is not None and o.t - prev["tEnd"] <= 1.5 / DEEP["caption_fps"] \
                and _similar(prev["text"], o.text):
            prev["tEnd"] = o.t
            prev["frames"].append(o.words)
            if len(o.text) > len(prev["text"]):
                prev["text"] = o.text
            continue
        cues.append({"tStart": o.t, "tEnd": o.t, "text": o.text,
                     "frames": [o.words]})
    return cues


def detect_karaoke(frames: list[dict]) -> bool:
    """True when a stable word's colour shifts across a cue's frames."""
    first_color: dict[str, tuple] = {}
    for words in frames:
        for key, color in words.items():
            base = first_color.setdefault(key, color)
            delta = max(abs(color[i] - base[i]) for i in range(3))
            if delta > DEEP["karaoke_color_delta"]:
                return True
    return False


def caption_stats(video: str, info: VideoInfo) -> dict:
    """The full caption-system readout for the deep study JSON."""
    series = collect_band_obs(video, info)
    band = pick_caption_band(series)
    if band is None:
        return {"detected": False, "sampledFps": DEEP["caption_fps"]}
    cues = cues_from_obs(series[band])
    if not cues:
        return {"detected": False, "sampledFps": DEEP["caption_fps"]}
    # UI-CHROME GATE (LL-012): a screen-share app churns menu/file text
    # exactly like captions turn over, so the turnover pick alone false-
    # positives on screen-share footage (two reference deep studies read
    # "detected" caption systems out of editor chrome + file paths).
    # Reject LOUDLY, keeping the evidence in the readout.
    chrome_frac = chrome_cue_fraction([c["text"] for c in cues])
    if chrome_frac >= DEEP["caption_chrome_max_frac"]:
        return {"detected": False, "rejected": "ui-chrome",
                "chromeCueFrac": round(chrome_frac, 3),
                "positionBand": band, "cues": len(cues),
                "sampledFps": DEEP["caption_fps"],
                "cueTexts": [c["text"] for c in cues[:40]]}
    words_per_cue = [len(c["text"].split()) for c in cues]
    return {
        "detected": True,
        "positionBand": band,
        "cues": len(cues),
        "cuesPerMin": round(len(cues) / (info.duration / 60.0), 2),
        "wordsPerCueMean": round(float(np.mean(words_per_cue)), 2),
        "karaoke": any(detect_karaoke(c["frames"]) for c in cues),
        "sampledFps": DEEP["caption_fps"],
        "cueTexts": [c["text"] for c in cues[:40]],
    }
