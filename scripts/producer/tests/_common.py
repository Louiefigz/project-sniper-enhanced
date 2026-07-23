#!/usr/bin/env python3
"""selftest — stdlib-only contract checks for the PRODUCER foundation.

No pytest, no new deps: ``python3 selftest.py`` runs the ``unittest`` suite and
exits 0 (pass) / 1 (fail). Covers the two correctness keystones that everything
downstream trusts:

* ``compile_timeline`` — multi-source ordering, speed math vs predicted
  duration, mapping cut material to None, output→source feedback resolution,
  ``remap_words`` boundary clamping + dropped words, dict round-trip.
* ``plan_lint`` — every editorial rule fires on a targeted mutation, and a
  known-good plan passes clean.

Fixtures are inline (small dicts). Run from ``scripts/producer/`` (or by
absolute path) so the flat imports resolve, matching the sibling scripts.
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import sys
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # producer pkg root on path
from motion import baseline_look as bl
from broll import broll_insert as bi
from broll import broll_pool as bp
from captions import captions_ass as cap
from captions import captions_minimal as cm
from captions import captions_whisper as cw
import compile_timeline as ct
from planner import free_space as fs
from planner import graphics_anchors as ga
import graphics_planner as gp
from planner import graphics_planner_boundaries as gpb
from planner import graphics_planner_density as gpd
from planner import graphics_planner_gauge as ggauge
from planner import graphics_planner_illustration as gillu
from planner import graphics_planner_rules as gpr
from planner import graphics_planner_sequences as gseq
from planner import graphics_reference as gref
from planner import graphics_planner_zoom as gpz
import graphics_copy as gcopy
from planner import motion_triggers as mt
from planner import pacing as pac
from graphics import exit_on_cut as eoc
from graphics import graphics_render as gr
from graphics import graphics_stage as gs
from graphics import stage_placement as spl
from graphics import pip_hole as phole
from graphics import pip_takeover as pipt
import plan_lint_nateherk as pln
import ingest_scan as iscan
import plan_lint as pl
import plan_lint_motion as plm
import plan_lint_reframe as plr
from motion import reframe_split as rsp
import assemble as asm
from audio import audio_enhance as aenh
from audio import music_stage as amus
from motion import punch_in as pin
from motion import transitions as tr
from motion import zoom_pull as zp
from broll import focus_ops as focp
import cut_speed as cs
from audio import sfx_library as sfxlib
from planner import icon_library as ilib
from planner import icon_lucide as ilu
import plan_lint_smooth as pls
from cut_speed import display_dims as ct_display_dims
from audit import audit_motion as amot

# The longform edit-brain tools (retake_scan / pause_scan) reuse study_edit_diff,
# which needs rapidfuzz. Keep selftest stdlib-runnable: skip their cases if it's
# absent rather than failing the whole suite at import.
try:
    from edit import pause_scan as ps
    import retake_scan as rs
    from edit.study_edit_diff import Utt, Word, norm
    _HAVE_RETAKE = True
except ImportError:
    _HAVE_RETAKE = False

# Half a frame at 30fps — the tolerance the renderer must hold to (§4.2).
HALF_FRAME_S = 1.0 / 60.0

MANIFEST = {
    "sources": [{"id": "raw-1", "duration": 60.0}, {"id": "raw-2", "duration": 60.0}],
    "broll": [{"id": "broll-1"}],
    "music": [{"id": "music-1"}],
}




def good_plan() -> dict:
    """A fresh, lint-clean short-mode plan (each test mutates its own copy)."""
    return {
        "planVersion": 1,
        "target": {"mode": "short", "durationTargetS": 30,
                   "platforms": ["tiktok", "reels", "shorts"]},
        "cutTrack": [{"sourceId": "raw-1", "start": 0.0, "end": 30.0, "speed": 1.0}],
        "reframe": {"strategy": "face"},
        "titleCards": [{"outStart": 0.0, "outEnd": 2.5, "text": "Zero sales this month",
                        "style": "hook", "position": "upper-safe"}],
        "captions": {"burn": True, "style": "karaoke"},
        "brollTrack": [{"outStart": 9.0, "outEnd": 10.5, "assetId": "broll-1",
                        "reason": "covers a jump cut"}],
        "music": {"enabled": True, "vibe": ["energetic"], "assetId": "music-1",
                  "variants": ["with", "without"]},
        "ending": {"loopStyle": "narrative", "ctaCaption": "More on the channel."},
        "chapters": None,
    }


def _mid_sentence(*pairs: tuple[str, float, float]) -> list[dict]:
    """Word list from (text, start, end) triples (the transcript shape)."""
    return [{"word": w, "start": s, "end": e} for w, s, e in pairs]


def _cand(start: float, end: float, conf: str = "high", kind: str = "chip-row",
          marks: list | None = None, trigger: str = "entity") -> dict:
    """A synthetic accepted-shape candidate for the density trim tests."""
    return {"outStart": start, "outEnd": end, "kind": kind, "confidence": conf,
            "trigger": trigger, "evidence": "x", "reason": "x", "spec": {},
            "anchor": "free-band", "_marks": marks or []}


_WORD_DUR_S, _WORD_GAP_S = 0.3, 0.05   # synthetic word cadence for the fixtures
def _mk_utt(idx: int, start: float, text: str) -> "Utt":
    """Build a study_edit_diff Utt from text, laying words out sequentially."""
    words, t = [], start
    for tk in text.split():
        words.append(Word(tk, round(t, 3), round(t + _WORD_DUR_S, 3),
                          (norm(tk) or [""])[0]))
        t += _WORD_DUR_S + _WORD_GAP_S
    return Utt(idx, start, round(words[-1].end, 3), text, words)


_HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
def _frame_yavg(path: str, n: int) -> float:
    """Mean luma (signalstats YAVG) of frame ``n`` of ``path``."""
    out = tr.run_ff(["ffprobe", "-v", "error", "-f", "lavfi",
                     f"movie={path},select='eq(n,{n})',signalstats",
                     "-show_entries", "frame_tags=lavfi.signalstats.YAVG",
                     "-of", "default=noprint_wrappers=1:nokey=1"])
    return float(out.strip().splitlines()[0])


def _tiny_marked_clip(path: str) -> None:
    """A 4s 640x360 solid-gray clip with a red 40x40 marker at (160,90) —
    box center (180,110). Solid background makes the marker probeable
    directly (no reference render needed)."""
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "color=c=gray:s=640x360:d=4:r=30",
         "-vf", "drawbox=x=160:y=90:w=40:h=40:color=red:t=fill",
         "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", path],
        check=True)


def _marker_center(path: str, t: float, w: int, h: int) -> tuple[float, float]:
    """Bbox center of the red marker in the frame at ``t`` (pure stdlib scan)."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(t), "-i", path, "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
        capture_output=True, check=True).stdout
    xs, ys = [], []
    for i in range(0, w * h * 3, 3):
        if raw[i] > 150 and raw[i + 1] < 100 and raw[i + 2] < 100:
            xs.append((i // 3) % w)
            ys.append((i // 3) // w)
    if not xs:
        raise AssertionError(f"marker not found in {path} at t={t}")
    return (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0


__all__ = [_n for _n in dir() if not _n.startswith("__")]
