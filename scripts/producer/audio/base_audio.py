#!/usr/bin/env python3
"""base_audio — the AUDIO-ONLY base fast path (assemble.py --auto-base).

An audioGain/audioEnhance edit used to flip the single base fingerprint and
cost a full ~98s base rebuild, ~88s of which re-encoded IDENTICAL video (cut
16.7 + punch 24.1 + transitions 21.8 + master ~27) even though the audio
stages themselves already ``-c:v copy``. With the split fingerprints
(fingerprints.py) a video-match/audio-mismatch dispatches HERE instead: the
existing base_final.mp4's video stream is kept and only its audio bus is
rebuilt — enhance → gain → two-pass loudnorm re-master, ``-c:v copy`` at
every step (~seconds).

HONESTY (the whoosh question). The full pipeline's audio order is
enhance → transitions(whoosh amix) → gain → master (render.py). The base's
audio already carries the whooshes at exactly the amix point, so:

* ``audioGain`` runs AFTER the amix in pipeline order — applying it to the
  mastered bus reproduces the order exactly (a gain window scales dialogue +
  whoosh alike, same as a full render). Gain-only edits stay fast even with
  sfx transitions.
* ``audioEnhance`` runs BEFORE the amix — on the base bus it would process
  the baked-in whooshes (afftdn/RNNoise/Demucs can eat authored SFX, the
  exact bug the stage order prevents). Re-applying the amix is impossible
  without the whoosh-free dialogue, so enhance edits on plans with sfx
  transitions FALL BACK loudly to the full rebuild — correctness over speed.
* An audio field that was ALREADY baked into the base cannot be un-baked
  (re-applying would stack old×new) — also a loud full-rebuild fallback.
"""
from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # run-by-path: producer pkg root on sys.path
from audio.audio_enhance import run_audio_enhance
from audio.audio_gain import apply_gain, overlap_error, parse_windows
from audio.master import build_pass2_afilter, dead_channel_prefix, measure_loudness
from producer_config import ENCODE


def _has_sfx_transitions(plan: dict) -> bool:
    """True when a plan transition explicitly opts into sound."""
    return any(ev.get("sfx", False) for ev in (plan.get("transitions") or []))


def audio_fast_path_block(old_plan: dict | None, new_plan: dict) -> str | None:
    """Why the audio-only fast path must NOT run — or None when it may.

    Pure decision function (unit-tested): the caller emits the reason as
    ``audio_fast_path_skipped`` and takes the full rebuild instead.
    """
    if old_plan is None:
        return ("no base_plan.json snapshot — cannot prove the base audio "
                "bus is pristine")
    if old_plan.get("audioEnhance") or old_plan.get("audioGain"):
        return ("base audio already carries baked-in audioEnhance/audioGain — "
                "re-applying would stack old and new processing")
    if not (new_plan.get("audioEnhance") or new_plan.get("audioGain")):
        return "no audioEnhance/audioGain in the edited plan to apply"
    if new_plan.get("audioEnhance") and _has_sfx_transitions(new_plan):
        return ("audioEnhance with sfx transitions: enhance runs BEFORE the "
                "whoosh amix in the pipeline, but the whooshes are baked into "
                "the base audio — enhance would process them")
    return None


def _run_ff(cmd: list[str], what: str) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"{what} failed: {proc.stderr.strip()[-400:]}")


def _remaster_audio(src: str, out: str) -> str | None:
    """Two-pass loudnorm on ``src``'s audio → ``out`` (video stream copied).

    Reuses master.py's mastering intelligence via its public
    ``build_pass2_afilter`` seam (linear / static-gain / dynamic dispatch) —
    never duplicates the private helpers. Returns the builder's warning note.
    """
    prefix, _warn = dead_channel_prefix(src)   # mastered bus: normally None
    measured = measure_loudness(src, prefix)
    afilter, note = build_pass2_afilter(src, prefix, measured)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-nostats", "-i", src,
           "-map", "0:v:0", "-c:v", "copy", "-map", "0:a:0", "-af", afilter,
           "-c:a", ENCODE["acodec"], "-b:a", ENCODE["audio_bitrate"],
           "-ar", str(ENCODE["audio_rate"]), "-ac", str(ENCODE["audio_channels"]),
           "-movflags", ENCODE["movflags"], out]
    _run_ff(cmd, "audio-only re-master")
    return note


def rebuild_audio_bus(base: str, plan: dict, work: str) -> tuple[str, dict]:
    """Rebuild the base's audio bus per the plan: enhance → gain → re-master.

    Every step copies the video stream bit-identical; only the audio
    re-encodes (AAC 256k — two/three generations at this bitrate are
    transparent). Returns (new base path inside ``work``, step summary).
    Eligibility (``audio_fast_path_block``) is the CALLER's gate.
    """
    os.makedirs(work, exist_ok=True)
    src, steps = base, {}
    preset = (plan.get("audioEnhance") or {}).get("preset")
    if preset:
        out = os.path.join(work, "bus_enhanced.mp4")
        rep = run_audio_enhance(src, preset, out)
        if rep.get("status") != "ok":
            raise RuntimeError(f"audio-only enhance failed: {rep.get('error')}")
        src, steps["enhance"] = out, preset
    gains = plan.get("audioGain") or []
    if gains:
        windows = parse_windows([{k: v for k, v in g.items() if k != "rationale"}
                                 for g in gains])
        overlap = overlap_error(windows)
        if overlap:
            raise RuntimeError(f"audio-only gain: {overlap}")
        out = os.path.join(work, "bus_gained.mp4")
        rep = apply_gain(src, windows, out)
        if not rep["ok"]:
            raise RuntimeError(f"audio-only gain failed: {rep['stderr'][-300:]}")
        src, steps["gain_windows"] = out, len(windows)
    mastered = os.path.join(work, "bus_mastered.mp4")
    note = _remaster_audio(src, mastered)
    if note:
        steps["remaster_note"] = note
    return mastered, steps


def mux_audio(video_src: str, audio_src: str, out: str) -> None:
    """Mux ``audio_src``'s audio onto ``video_src``'s video → ``out`` (all copy).

    The audio-only composite skip: when the video fingerprint AND the
    graphicsTrack are unchanged, the existing final.mp4's composited video is
    reused verbatim and only the (new) base audio is swapped in. Writes via a
    sibling temp so ``out`` may equal ``video_src``.
    """
    tmp = out + ".mux.mp4"
    _run_ff(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
             "-i", video_src, "-i", audio_src, "-map", "0:v:0", "-map", "1:a:0",
             "-c", "copy", "-movflags", ENCODE["movflags"], tmp],
            "audio-only mux")
    os.replace(tmp, out)
