#!/usr/bin/env python3
"""cover_select — deterministic slip-cover window scoring (LL-008).

The v2 showpiece's 45.3-47.8s wide slip-cover read as an OUTTAKE: the subject
sat silent, mouth closed, motionless (operator review 2026-07-10,
``docs/findings/FAILURE_LEDGER.md`` LL-008). Cover footage only reads
INTENTIONAL when the subject is actively DOING something — gesturing, working,
moving. This module gives the edit brain's cover lane a deterministic score
for every candidate SOURCE window:

* MOTION ENERGY — MEDIAN per-pixel luma frame-diff across the window (ffmpeg
  grayscale downscale → abs diff): "is something happening the WHOLE time".
  Median, not mean — one flash must not buy a half-frozen window a score.
* GESTURE PRESENCE — the same diff over the LOWER HALF of the frame (hands
  live below the face in a talking-head crop): the deterministic gesture
  proxy; no pose model, no LLM.
* HARD EXCLUDES — a window overlapping a ``retake_scan`` cut span
  (± ``retake_pad_s``) is outtake footage BY CONSTRUCTION; a window with
  more than ``lip_flap_max_s`` SECONDS of spoken words is excluded
  ("lip-flap", LL-010: a slip-cover shows the SAME speaker, so visible
  on-camera speech mouths words that are not the underlying audio — the
  operator read it as an AV-sync error); a window whose transcript is empty
  for more than ``1 - speech_min_share`` of its seconds is excluded UNLESS
  its motion clears ``silent_motion_floor`` (silent + static =
  outtake-looking; silent + visibly working is legal).

``score_windows`` is PURE (motion profile + words + retake spans in, scored
rows out) so tests drive synthetic motion profiles; ``motion_profile`` is the
ffmpeg wire; ``score_cover_windows(manifest, span)`` is the brain's entry
point. When no candidate clears ``score_floor`` the result says to cover the
seam with a GRAPHIC TAKEOVER instead (LESSON-008) — never ship a dead stare.
Deterministic code owns the WHERE (scores, excludes); the brain owns the
WHAT (which surviving window tells the story). Knobs:
``producer_config.COVER_SELECT``.

CLI: cover_select.py <manifest.json> <start> <end> [--source-id ID]
                     [--no-retakes]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from producer_config import COVER_SELECT  # noqa: E402


@dataclass
class MotionProfile:
    """Frame-diff samples of one source region (each entry is one DIFF)."""
    times: list[float]   # source-time instant of each diff sample
    full: list[float]    # mean |Δluma| per pixel, whole frame (0..255)
    lower: list[float]   # mean |Δluma| per pixel, LOWER HALF (hands band)


# --------------------------------------------------------------------------- #
# Pure scoring — synthetic-profile testable, no I/O.
# --------------------------------------------------------------------------- #
def speech_share(words: list[dict], s: float, e: float) -> float:
    """Fraction of ``[s, e)`` covered by spoken words (clamped union)."""
    if e <= s:
        return 0.0
    spans = sorted((max(s, float(w["start"])), min(e, float(w["end"])))
                   for w in words
                   if float(w["end"]) > s and float(w["start"]) < e)
    covered, cursor = 0.0, s
    for a, b in spans:
        a = max(a, cursor)
        if b > a:
            covered += b - a
            cursor = b
    return covered / (e - s)


def _median(values: list[float]) -> float:
    """Median (mean of the two middles for even counts)."""
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0


def _window_means(profile: MotionProfile, s: float,
                  e: float) -> tuple[float, float]:
    """MEDIAN full/lower diff of the profile samples strictly inside (s, e).

    Median, not mean: LESSON-008 wants the subject doing something for the
    WHOLE cover, and a mean lets one flash (a hard content flip, a camera
    bump) buy a half-frozen window a passing score — measured on the
    synthetic static→moving verification clip, where a straddling window
    scored 1.0 off a single boundary spike. Strict bounds: a diff sample at
    instant ``t`` measures the change INTO the frame shown at ``t``, so a
    sample at exactly ``e`` is a change the window never displays.
    """
    idx = [i for i, t in enumerate(profile.times) if s < t < e]
    if not idx:
        return 0.0, 0.0
    return (_median([profile.full[i] for i in idx]),
            _median([profile.lower[i] for i in idx]))


def _norm(value: float, ref: float) -> float:
    """0..1 normalization against the config reference level."""
    return min(1.0, value / ref) if ref > 0 else 0.0


def _overlaps_retake(s: float, e: float, retake_spans: list,
                     pad: float) -> bool:
    """True when [s, e] touches any retake cut span padded by ``pad``."""
    return any(s < float(re) + pad and float(rs) - pad < e
               for rs, re in retake_spans)


def score_windows(profile: MotionProfile, words: list[dict],
                  retake_spans: list, windows: list) -> list[dict]:
    """Score each ``(start, end)`` candidate window (PURE — the LL-008 core).

    Args:
        profile: Motion samples covering the candidates (``motion_profile``).
        words: Flat transcript words ``{word, start, end}`` in source time.
        retake_spans: ``(cutStartS, cutEndS)`` pairs from ``retake_scan``.
        windows: Candidate ``(start, end)`` source windows.

    Returns:
        One row per candidate: ``{start, end, score, motion, gesture,
        speechShare, excluded}`` — ``excluded`` is None, "retake-overlap",
        "lip-flap", or "silent-static". Excluded rows keep their score for
        transparency but must never be picked (``best_cover`` enforces it).
    """
    cfg = COVER_SELECT
    out: list[dict] = []
    for s, e in windows:
        s, e = float(s), float(e)
        full, lower = _window_means(profile, s, e)
        motion = _norm(full, cfg["motion_ref"])
        gesture = _norm(lower, cfg["gesture_ref"])
        share = speech_share(words, s, e)
        excluded = None
        if _overlaps_retake(s, e, retake_spans, cfg["retake_pad_s"]):
            excluded = "retake-overlap"
        elif share * (e - s) > cfg["lip_flap_max_s"]:
            # LL-010: visible same-speaker speech mismatches the underlying
            # audio — the c0679 cover carried 0.49s (share 0.19) and the
            # operator read it as "the sound did not sync for a moment".
            excluded = "lip-flap"
        elif share < cfg["speech_min_share"] \
                and motion < cfg["silent_motion_floor"]:
            excluded = "silent-static"
        out.append({
            "start": round(s, 3), "end": round(e, 3),
            "score": round(cfg["motion_weight"] * motion
                           + cfg["gesture_weight"] * gesture, 4),
            "motion": round(motion, 4), "gesture": round(gesture, 4),
            "speechShare": round(share, 4), "excluded": excluded,
        })
    return out


def best_cover(scored: list[dict]) -> dict:
    """The best legal window above the floor — or the LESSON-008 verdict.

    Returns ``{best, note, candidates}``: ``best`` is None when nothing
    survives, and ``note`` then says to cover the seam with a graphic
    takeover instead (never ship a dead stare).
    """
    floor = COVER_SELECT["score_floor"]
    legal = [r for r in scored
             if r["excluded"] is None and r["score"] >= floor]
    best = max(legal, key=lambda r: r["score"], default=None)
    note = None
    if best is None:
        note = (f"no cover window clears the {floor:g} score floor — cover "
                "the seam with a graphic takeover instead (LESSON-008: "
                "silent staring reads as an outtake)")
    return {"best": best, "note": note, "candidates": scored}


def candidate_windows(span: tuple, duration: float) -> list[tuple]:
    """Span-length windows slid across ± ``search_s`` around the seam span."""
    s0, e0 = float(span[0]), float(span[1])
    win = e0 - s0
    if win <= 0:
        raise ValueError(f"cover span must have start < end (got {span!r})")
    lo = max(0.0, s0 - COVER_SELECT["search_s"])
    hi = min(duration - win, e0 + COVER_SELECT["search_s"] - win)
    out: list[tuple] = []
    t = lo
    while t <= hi + 1e-9:
        out.append((round(t, 3), round(t + win, 3)))
        t += COVER_SELECT["hop_s"]
    if not out:
        raise ValueError(f"no candidate windows fit span {span!r} inside a "
                         f"{duration:.2f}s source")
    return out


# --------------------------------------------------------------------------- #
# ffmpeg wire — the only I/O between the source file and the pure scorer.
# --------------------------------------------------------------------------- #
def motion_profile(path: str, s: float, e: float) -> MotionProfile:
    """Grayscale low-res frame-diff profile of ``[s, e]`` of ``path``."""
    cfg = COVER_SELECT
    w, h, fps = cfg["sample_w"], cfg["sample_h"], cfg["sample_fps"]
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{max(0.0, s):.3f}",
         "-t", f"{max(0.0, e - s):.3f}", "-i", path,
         "-vf", f"fps={fps},scale={w}:{h},format=gray",
         "-f", "rawvideo", "pipe:1"],
        capture_output=True, check=True).stdout
    n = len(raw) // (w * h)
    if n < 2:
        raise ValueError(f"cover_select: {path!r} yielded {n} frame(s) in "
                         f"[{s:.2f},{e:.2f}] — cannot measure motion")
    px, half = w * h, w * h // 2
    frames = [raw[i * px:(i + 1) * px] for i in range(n)]
    times, full, lower = [], [], []
    for i in range(1, n):
        a, b = frames[i - 1], frames[i]
        diff = [abs(x - y) for x, y in zip(a, b)]
        times.append(round(s + i / fps, 3))
        full.append(sum(diff) / px)
        lower.append(sum(diff[half:]) / (px - half))
    return MotionProfile(times, full, lower)


# --------------------------------------------------------------------------- #
# Manifest wire — resolve source/transcript, then run the pure scorer.
# --------------------------------------------------------------------------- #
def _resolve_source(manifest, source_id: str | None) -> dict:
    """Manifest (path or dict) → ``{id, path, duration, transcript}``.

    Fails loudly on a missing source / path / transcript — a cover lane
    without ground truth must not guess (no fallback matching).
    """
    base = os.getcwd()
    if isinstance(manifest, str):
        base = os.path.dirname(os.path.abspath(manifest))
        with open(manifest) as f:
            manifest = json.load(f)
    sources = manifest.get("sources") or []
    if not sources:
        raise ValueError("manifest has no sources")
    if source_id is None:
        src = sources[0]
    else:
        by_id = {s["id"]: s for s in sources}
        if source_id not in by_id:
            raise ValueError(f"sourceId {source_id!r} not in manifest "
                             f"(have: {sorted(by_id)})")
        src = by_id[source_id]
    path = src.get("path")
    if not path or not os.path.isfile(path):
        raise ValueError(f"source {src.get('id')!r} has no readable path "
                         f"({path!r})")
    transcript = src.get("transcriptPath")
    if not transcript:
        raise ValueError(f"source {src['id']!r} has no transcriptPath — "
                         "cover scoring needs the speech map (LL-008)")
    if not os.path.isabs(transcript):
        transcript = os.path.join(base, transcript)
    if not os.path.isfile(transcript):
        raise ValueError(f"transcript not found: {transcript}")
    return {"id": src["id"], "path": path,
            "duration": float(src["duration"]), "transcript": transcript}


def _load_words(transcript_path: str) -> list[dict]:
    """Flat ``{word, start, end}`` rows from a transcribe.py transcript."""
    with open(transcript_path) as f:
        obj = json.load(f)
    utts = obj["transcript"] if isinstance(obj, dict) else obj
    return [w for u in utts for w in (u.get("words") or [])]


def _retake_spans(transcript_path: str) -> list[tuple]:
    """``(cutStartS, cutEndS)`` spans from retake_scan on the transcript."""
    import retake_scan  # deferred: pulls rapidfuzz only when actually needed
    report = retake_scan.analyze(transcript_path)
    return [(r["cutStartS"], r["cutEndS"]) for r in report["retakes"]]


def score_cover_windows(manifest, span: tuple, source_id: str | None = None,
                        retake_spans: list | None = None) -> dict:
    """Score every candidate cover window around ``span`` — the brain's API.

    Args:
        manifest: ``asset_manifest.json`` path or the loaded dict.
        span: ``(start, end)`` of the seam to cover, in SOURCE seconds.
        source_id: Manifest source to draw the cover from (default: first).
        retake_spans: ``(cutStartS, cutEndS)`` pairs to hard-exclude; None
            runs ``retake_scan`` on the source transcript (pass ``[]`` to
            skip exclusion explicitly).

    Returns:
        ``best_cover``'s dict plus ``sourceId`` and ``span``.
    """
    src = _resolve_source(manifest, source_id)
    if retake_spans is None:
        retake_spans = _retake_spans(src["transcript"])
    windows = candidate_windows(span, src["duration"])
    lo = min(w[0] for w in windows)
    hi = max(w[1] for w in windows)
    profile = motion_profile(src["path"], lo, hi)
    scored = score_windows(profile, _load_words(src["transcript"]),
                           retake_spans, windows)
    result = best_cover(scored)
    result["sourceId"] = src["id"]
    result["span"] = [round(float(span[0]), 3), round(float(span[1]), 3)]
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Score slip-cover candidate "
                                             "windows for a seam (LL-008).")
    ap.add_argument("manifest")
    ap.add_argument("start", type=float)
    ap.add_argument("end", type=float)
    ap.add_argument("--source-id", help="manifest source id (default: first)")
    ap.add_argument("--no-retakes", action="store_true",
                    help="skip the retake_scan exclusion pass")
    args = ap.parse_args()
    result = score_cover_windows(
        args.manifest, (args.start, args.end), args.source_id,
        [] if args.no_retakes else None)
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
