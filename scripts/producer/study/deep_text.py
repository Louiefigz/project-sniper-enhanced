#!/usr/bin/env python3
"""deep_text — P4: tesseract OCR over graphic events + fingerprint states.

For every detected graphic/panel-in event this reads the CHANGED REGION only
(the event's bbox, padded), per frame across the event window:

* text content + refined bbox + text height as a fraction of frame height,
* dominant text / background colours (pixel sampling: bg = the bbox border
  ring's median colour; text pixels = far-from-bg pixels inside),
* per-word appearance timing — the OCR diff between consecutive frames names
  the first frame each word is readable on (karaoke/typewriter builds).

Also OCRs each fingerprint state representative once (full frame), so every
distinct on-screen state carries its readable text. tesseract is local and
deterministic; a missing binary fails loudly (FRAME.IO REVIEW's dependency).
"""

from __future__ import annotations

import os
import shutil
import sys

import numpy as np
import pytesseract
from pytesseract import Output

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2  # noqa: E402

from study.deep_config import DEEP  # noqa: E402
from study.deep_frames import VideoInfo, Window, decode_window  # noqa: E402


def require_tesseract() -> None:
    """Fail loudly before any OCR pass when the binary is absent."""
    if shutil.which("tesseract") is None:
        raise RuntimeError(
            "tesseract not found on PATH — P4 text extraction needs it "
            "(brew install tesseract); same dependency as FRAME.IO REVIEW")


def ocr_words(image: np.ndarray, psm: "int | None" = None,
              conf_min: "float | None" = None) -> list[dict]:
    """Confidence-gated tesseract words: {text, conf, box(x,y,w,h) px}.

    PSM matters (measured on the synthetic clip): the default auto layout
    (PSM 3) reads NOTHING off a caption bar crop; PSM 6 (uniform block) is
    right for event-region crops, PSM 11 (sparse text) for band slices.
    """
    psm = DEEP["ocr_psm_region"] if psm is None else psm
    conf_min = DEEP["ocr_conf_min"] if conf_min is None else conf_min
    factor = DEEP["ocr_upscale"]
    if factor > 1:
        image = cv2.resize(image, None, fx=factor, fy=factor,
                           interpolation=cv2.INTER_CUBIC)
    data = pytesseract.image_to_data(image, output_type=Output.DICT,
                                     config=f"--psm {psm}")
    words = []
    for i, raw in enumerate(data["text"]):
        text = (raw or "").strip()
        conf = float(data["conf"][i])
        if not text or conf < conf_min:
            continue
        if not any(ch.isalnum() for ch in text):
            continue           # '—' / '|' / '=' artefacts, never real copy
        words.append({"text": text, "conf": conf,
                      "box": (data["left"][i] // factor,
                              data["top"][i] // factor,
                              max(1, data["width"][i] // factor),
                              max(1, data["height"][i] // factor))})
    return words


def _norm(token: str) -> str:
    """Case/punctuation-insensitive word key for appearance matching."""
    return "".join(ch for ch in token.upper() if ch.isalnum())


def _pad_rect(bbox_norm: list[float], dims: tuple[int, int]) -> tuple:
    """Event bbox (normalised) → padded pixel rect clamped to the frame."""
    w, h = dims
    pad = DEEP["ocr_bbox_pad_frac"]
    x0 = int((bbox_norm[0] - bbox_norm[2] * pad) * w)
    y0 = int((bbox_norm[1] - bbox_norm[3] * pad) * h)
    x1 = int((bbox_norm[0] + bbox_norm[2] * (1 + pad)) * w)
    y1 = int((bbox_norm[1] + bbox_norm[3] * (1 + pad)) * h)
    return max(0, x0), max(0, y0), min(w, x1), min(h, y1)


def _to_hex(bgr) -> str:
    return "#%02x%02x%02x" % (int(bgr[2]), int(bgr[1]), int(bgr[0]))


def text_bg_colors(crop: np.ndarray, words: list[dict],
                   inner: tuple) -> tuple[str, str]:
    """(#text, #bg) — anchored on the WORD BOXES, not the crop border.

    ``inner`` is the unpadded event bbox in crop coordinates: the bg is the
    median colour of the graphic's own chrome (inner region minus word
    boxes — the padded ring shows footage, never sample it), the text colour
    the median of word-box pixels standing far from that bg.
    """
    mask = np.zeros(crop.shape[:2], dtype=bool)
    for w in words:
        x, y, bw, bh = w["box"]
        mask[max(0, y):y + bh, max(0, x):x + bw] = True
    ix0, iy0, ix1, iy1 = inner
    region = crop[iy0:iy1, ix0:ix1]
    region_mask = mask[iy0:iy1, ix0:ix1]
    chrome = region[~region_mask]
    if chrome.size == 0:
        chrome = region.reshape(-1, 3)
    if chrome.size == 0:
        return "", ""
    bg = np.median(chrome, axis=0)
    boxed = crop[mask]
    dist = np.abs(boxed.astype(np.float32) - bg).sum(axis=1)
    glyphs = boxed[dist > DEEP["text_color_delta"]]
    text = np.median(glyphs, axis=0) if len(glyphs) else bg
    return _to_hex(text), _to_hex(bg)


def _bboxes_overlap(a: "list | None", b: "list | None") -> bool:
    """Normalised bbox intersection test (a missing bbox = global = True)."""
    if a is None or b is None:
        return True
    return (a[0] < b[0] + b[2] and b[0] < a[0] + a[2]
            and a[1] < b[1] + b[3] and b[1] < a[1] + a[3])


def _cap_t(event: dict, events: list[dict]) -> float:
    """First later boundary that destroys the region: a cut, or an
    overlapping graphic/panel-out — the OCR window must stop there."""
    caps = [other["t"] for other in events
            if other["t"] > event["t"]
            and (other["type"] == "cut"
                 or (other["type"].endswith("-out")
                     and _bboxes_overlap(event.get("bbox"),
                                         other.get("bbox"))))]
    return min(caps) if caps else float("inf")


def _window_for(event: dict, info: VideoInfo, fps: float,
                cap: float = float("inf")) -> Window:
    """Native-res OCR window for one event, frame-capped via the fps."""
    t0 = max(0.0, event["t"] - 1.0 / fps)
    t1 = min(info.duration, event["t"] + DEEP["text_window_s"], cap)
    t1 = max(t1, t0 + 2.5 / fps)     # always at least a couple of frames
    span = max(t1 - t0, 1.0 / fps)
    use_fps = min(fps, DEEP["max_ocr_frames"] / span)
    return Window(t0=t0, t1=t1, fps=use_fps, width=None)


def _first_seen(frames_words: list[list[dict]], t0: float,
                fps: float) -> dict[str, float]:
    """Word key → first timestamp it OCRs (the consecutive-frame diff)."""
    seen: dict[str, float] = {}
    for k, words in enumerate(frames_words):
        for w in words:
            key = _norm(w["text"])
            if key and key not in seen:
                seen[key] = round(t0 + k / fps, 3)
    return seen


def _settled_words(frames_words: list[list[dict]]) -> tuple[list[dict], int]:
    """(words, frame index) of the last non-empty OCR — the settled card."""
    for k in range(len(frames_words) - 1, -1, -1):
        if frames_words[k]:
            return frames_words[k], k
    return [], len(frames_words) - 1


def graphic_text(video: str, info: VideoInfo, event: dict,
                 window: "Window | None" = None) -> "dict | None":
    """The full P4 readout for one graphic/panel-in event (None: no bbox)."""
    if not event.get("bbox"):
        return None
    win = window or _window_for(event, info, 30.0)
    frames = decode_window(video, win, info, "bgr24")
    if not frames:
        raise RuntimeError(f"OCR window decode empty at t={event['t']}s")
    x0, y0, x1, y1 = _pad_rect(event["bbox"], (info.width, info.height))
    crops = [f[y0:y1, x0:x1] for f in frames]
    frames_words = [ocr_words(c) for c in crops]
    settled, settled_idx = _settled_words(frames_words)
    first = _first_seen(frames_words, win.t0, win.fps)
    words = [{"word": w["text"],
              "t": first.get(_norm(w["text"]), win.t0),
              "bbox": _box_norm(w["box"], (x0, y0), info)}
             for w in settled]
    heights = [w["box"][3] for w in settled]
    inner = (max(0, int(event["bbox"][0] * info.width) - x0),
             max(0, int(event["bbox"][1] * info.height) - y0),
             min(x1 - x0, int((event["bbox"][0] + event["bbox"][2])
                              * info.width) - x0),
             min(y1 - y0, int((event["bbox"][1] + event["bbox"][3])
                              * info.height) - y0))
    text_hex, bg_hex = (text_bg_colors(crops[settled_idx], settled, inner)
                        if crops[settled_idx].size else ("", ""))
    return {"eventId": event.get("id"), "t": event["t"],
            "text": " ".join(w["text"] for w in settled),
            "bbox": event["bbox"],
            "heightFracH": round(float(np.median(heights)) / info.height, 4)
            if heights else 0.0,
            "textColor": text_hex, "bgColor": bg_hex, "words": words}


def _box_norm(box: tuple, origin: tuple[int, int], info: VideoInfo) -> list:
    """Crop-relative pixel box → frame-normalised [x,y,w,h]."""
    x, y, w, h = box
    return [round((origin[0] + x) / info.width, 4),
            round((origin[1] + y) / info.height, 4),
            round(w / info.width, 4), round(h / info.height, 4)]


def states_text(fingerprint: dict) -> list[dict]:
    """One full-frame OCR per fingerprint state representative."""
    out = []
    for state in fingerprint.get("states") or []:
        rep = state.get("rep_path")
        if not rep or not os.path.isfile(rep):
            continue
        image = cv2.imread(rep)
        if image is None:
            continue
        words = ocr_words(image)
        out.append({"stateIndex": state.get("index"),
                    "tStart": state.get("t_start"),
                    "text": " ".join(w["text"] for w in words),
                    "wordCount": len(words)})
    return out


def graphics_text(video: str, info: VideoInfo, events: list[dict],
                  fps: float) -> list[dict]:
    """P4 over every graphic/panel-in event, in time order. Each event's OCR
    window is capped at the next boundary that destroys its region."""
    hits = []
    for ev in events:
        if ev["type"] not in ("graphic-in", "panel-in"):
            continue
        win = _window_for(ev, info, fps, cap=_cap_t(ev, events))
        readout = graphic_text(video, info, ev, window=win)
        if readout is not None:
            hits.append(readout)
    return hits
