"""Perceptual-hash dedup — collapse near-identical frames before the API.

A static slide held on screen for 12 seconds yields ~12 identical frames at
fps=1; we only want to pay for it once. We compute a perceptual hash (pHash)
per frame and keep a frame only when it differs from the last *kept* frame by
more than ``threshold`` Hamming bits. Each kept frame carries the time range it
stayed on screen (t_start..t_end) so a single flag can report "visible 4s–16s".
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import imagehash
from PIL import Image

from .extract import Frame
from .util import log


@dataclass
class KeptFrame:
    """A representative frame plus the span it was visible."""

    index: int                 # extraction index of the representative frame
    path: str                  # JPG analyzed by Claude
    t_start: float             # first second this image appeared
    t_end: float               # last second before it changed
    duplicates: int = 0        # frames collapsed into this one (excl. itself)
    phash: str = ""
    # OCR-selector mode (scripts/frameio/ocr_dedup.py) populates these; the
    # visual/pHash path leaves them at their defaults.
    raw_text: str = ""         # representative frame's raw tesseract text (ocr mode)
    is_blank: bool = False      # true-blank run (empty OCR, blank neighbors)
    empty_kept: bool = False    # non-blank empty-OCR frame kept via fallback (rule #6)

    @property
    def timestamp(self) -> float:
        """Canonical timestamp to report/seek to (start of the span)."""
        return self.t_start


def dedup_frames(frames: list[Frame], threshold: int = 5) -> list[KeptFrame]:
    """Collapse runs of visually-similar frames; return one KeptFrame per run.

    ``threshold`` is the max Hamming distance (in pHash bits) still considered
    "the same slide". 0 = only exact-hash matches collapse; higher = more
    aggressive. Default 5 per the spec; tune to trade cost vs. granularity.

    The representative is the **settled** frame of each run, NOT the first: we
    pick the **modal** pHash (the state most frames in the run agree on — a held
    slide), tie-breaking toward the run's temporal middle. This avoids landing on
    a mid-fade-in frame whose half-rendered text ("NON-FICTIO") reads as a typo.
    ``t_start``/``t_end`` still span the whole run for seeking.
    """
    kept: list[KeptFrame] = []
    run: list[tuple[Frame, imagehash.ImageHash]] = []  # current run of similar frames
    anchor: imagehash.ImageHash | None = None          # hash of the run's first frame

    def _flush() -> None:
        if not run:
            return
        counts = Counter(str(h) for _, h in run)
        top = max(counts.values())
        modal = {h for h, c in counts.items() if c == top}
        mid = (len(run) - 1) / 2
        # Settled rep: a modal-hash frame nearest the run's time-middle. When no
        # hash repeats (e.g. an all-distinct fade), every frame ties → middle frame.
        best = min(
            (i for i, (_, h) in enumerate(run) if str(h) in modal),
            key=lambda i: abs(i - mid),
        )
        rep_fr, rep_h = run[best]
        kept.append(KeptFrame(
            index=rep_fr.index, path=rep_fr.path,
            t_start=run[0][0].timestamp, t_end=run[-1][0].timestamp,
            duplicates=len(run) - 1, phash=str(rep_h),
        ))

    for fr in frames:
        try:
            with Image.open(fr.path) as im:
                h = imagehash.phash(im)
        except Exception as e:  # unreadable frame — keep it alone, let Claude decide
            log("dedup", f"hash failed for {fr.path}: {e}")
            _flush()
            run, anchor = [], None
            kept.append(KeptFrame(index=fr.index, path=fr.path,
                                  t_start=fr.timestamp, t_end=fr.timestamp))
            continue

        if anchor is not None and (h - anchor) <= threshold:
            run.append((fr, h))            # same slide — extend the run
        else:
            _flush()
            run, anchor = [(fr, h)], h     # start a new run

    _flush()
    log("dedup",
        f"{len(frames)} frame(s) → {len(kept)} kept (threshold={threshold}, settled-rep)")
    return kept
