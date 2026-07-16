"""OCR-text dedup — pick one *settled* representative per on-screen text state.

The visual/pHash path (``dedup.py``) keeps the FIRST frame of each similar run,
which at fade-in lands on a half-rendered frame ("NON-FICTIO") that Claude then
flags as a typo. This selector groups frames by their *OCR text* instead: it runs
tesseract locally (free, no API), walks frames in time order, and collapses
consecutive frames whose normalized text is fuzzy-equal into a run. Per run it
keeps the MODAL text frame (the settled state most frames agree on), folds lone
fade fragments into the neighbour they're a prefix/subset of, and never silently
drops a frame whose OCR is empty but whose neighbours had text.

Output is ``list[KeptFrame]`` — identical to ``dedup_frames`` — so the rest of the
pipeline (analyze loop, events, results.json, report.html) is unchanged. Tesseract
text is used ONLY to choose representatives; it is never sent to Claude.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import pytesseract
from PIL import Image
from rapidfuzz import fuzz as rf_fuzz

from .dedup import KeptFrame
from .extract import Frame
from .util import log

# Fewer than this many alphanumerics after normalization = "empty/near-empty".
MIN_ALNUM = 3

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")
_ALNUM = re.compile(r"[a-z0-9]")


def normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace — the grouping key."""
    t = _PUNCT.sub(" ", text.lower())
    return _WS.sub(" ", t).strip()


def _is_empty(norm: str) -> bool:
    return len(_ALNUM.findall(norm)) < MIN_ALNUM


@dataclass
class _OCRFrame:
    frame: Frame
    raw: str
    norm: str

    @property
    def empty(self) -> bool:
        return _is_empty(self.norm)


@dataclass
class _Run:
    frames: list[_OCRFrame] = field(default_factory=list)

    @property
    def t_start(self) -> float:
        return self.frames[0].frame.timestamp

    @property
    def t_end(self) -> float:
        return self.frames[-1].frame.timestamp

    @property
    def empty(self) -> bool:
        # A run is empty only if every frame in it is empty.
        return all(f.empty for f in self.frames)

    def rep_norm(self) -> str:
        return _pick_rep(self.frames).norm


def _ocr_one(fr: Frame) -> _OCRFrame:
    try:
        with Image.open(fr.path) as im:
            raw = pytesseract.image_to_string(im)
    except Exception as e:  # tesseract/PIL failure — treat as empty, don't crash
        log("ocr", f"failed for {os.path.basename(fr.path)}: {e}")
        raw = ""
    return _OCRFrame(frame=fr, raw=raw, norm=normalize(raw))


def _pick_rep(frames: list[_OCRFrame]) -> _OCRFrame:
    """Modal normalized text wins; tie-break by longest raw text."""
    counts = Counter(f.norm for f in frames)
    top = max(counts.values())
    modal = {n for n, c in counts.items() if c == top}
    cands = [f for f in frames if f.norm in modal]
    return max(cands, key=lambda f: len(f.raw))


def _is_fragment_of(frag_norm: str, whole_norm: str) -> bool:
    """True if ``frag_norm`` looks like a partial render of ``whole_norm``.

    Two ways: a literal prefix (truncated fade-in like "non fictio" → "non
    fiction"), or a strict token-subset (every word of the fragment appears in
    the whole). Requires the fragment to be strictly shorter so equal text —
    which would already have grouped — isn't folded.
    """
    if not frag_norm or len(frag_norm) >= len(whole_norm):
        return False
    if whole_norm.startswith(frag_norm):
        return True
    frag_tokens, whole_tokens = set(frag_norm.split()), set(whole_norm.split())
    return bool(frag_tokens) and frag_tokens < whole_tokens


def _build_runs(ocr: list[_OCRFrame], fuzz_threshold: int) -> list[_Run]:
    """Group consecutive frames whose normalized text is fuzzy-equal.

    Boundary rules vs the previous frame: empty↔empty stays together (blank
    held); empty↔text always breaks; text↔text joins when token_set_ratio meets
    the threshold.
    """
    runs: list[_Run] = []
    for f in ocr:
        if not runs:
            runs.append(_Run([f]))
            continue
        prev = runs[-1].frames[-1]
        if f.empty or prev.empty:
            same = f.empty and prev.empty
        else:
            same = rf_fuzz.token_set_ratio(f.norm, prev.norm) >= fuzz_threshold
        if same:
            runs[-1].frames.append(f)
        else:
            runs.append(_Run([f]))
    return runs


def _merge_fragments(runs: list[_Run]) -> list[_Run]:
    """Fold single-frame fade fragments into the neighbour they're a part of.

    Prefer folding into the *next* run (a fade-in fragment precedes its settled
    slide); otherwise fold into the previous run (a fade-out trailing fragment).
    """
    merged: list[_Run] = []
    i = 0
    while i < len(runs):
        r = runs[i]
        is_fragment_candidate = (not r.empty) and len(r.frames) == 1
        if is_fragment_candidate and i + 1 < len(runs):
            nxt = runs[i + 1]
            if not nxt.empty and _is_fragment_of(r.rep_norm(), nxt.rep_norm()):
                nxt.frames = r.frames + nxt.frames  # extend span backwards
                i += 1
                continue
        if is_fragment_candidate and merged and not merged[-1].empty:
            prev = merged[-1]
            if _is_fragment_of(r.rep_norm(), prev.rep_norm()):
                prev.frames = prev.frames + r.frames  # extend span forwards
                i += 1
                continue
        merged.append(r)
        i += 1
    return merged


def select_representatives(
    frames: list[Frame],
    fuzz: int = 90,
    workers: int | None = None,
) -> list[KeptFrame]:
    """OCR every frame, group by text, return one settled rep per run.

    ``fuzz`` is the rapidfuzz token_set_ratio threshold (0–100) for two frames'
    text to count as the same on-screen state. ``workers`` parallelizes the
    tesseract pass (the slow-but-free stage); defaults to a CPU-based pool.
    """
    if not frames:
        return []

    workers = workers or min(8, (os.cpu_count() or 4))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        ocr = list(pool.map(_ocr_one, frames))  # order preserved (== time order)

    runs = _merge_fragments(_build_runs(ocr, fuzz))

    kept: list[KeptFrame] = []
    for idx, run in enumerate(runs):
        rep = _pick_rep(run.frames)
        is_blank = empty_kept = False
        if run.empty:
            prev_has_text = idx > 0 and not runs[idx - 1].empty
            next_has_text = idx + 1 < len(runs) and not runs[idx + 1].empty
            if prev_has_text or next_has_text:
                empty_kept = True   # rule #6: real slide tesseract couldn't read — keep & send
            else:
                is_blank = True     # genuinely blank — kept for the report, skippable when paid
        kept.append(KeptFrame(
            index=rep.frame.index,
            path=rep.frame.path,
            t_start=run.t_start,
            t_end=run.t_end,
            duplicates=len(run.frames) - 1,
            raw_text=rep.raw.strip(),
            is_blank=is_blank,
            empty_kept=empty_kept,
        ))

    log("ocr",
        f"{len(frames)} frame(s) → {len(runs)} run(s)/representative(s) (fuzz={fuzz})")
    return kept
