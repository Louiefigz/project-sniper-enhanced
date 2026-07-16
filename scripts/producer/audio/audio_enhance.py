#!/usr/bin/env python3
"""audio_enhance — voice-focus dialogue cleanup (plan.audioEnhance).

"Zone in on my voice and mute the background": a deterministic ffmpeg filter
chain (preset catalog in ``producer_config.AUDIO_ENHANCE``) applied to the
dialogue bus BEFORE the editorial gain windows and the loudnorm master, so the
cleaned signal is what gets leveled. The video stream is COPIED bit-identical —
this stage re-encodes audio only (seconds, not minutes).

Honesty note (also in the preset catalog): ``afftdn`` subtracts the STEADY
background — room tone, hum, AC, fan. ``voice-rnn`` (RNNoise via ``arnndn``,
model vendored in ``audio/models/``) handles messier noise. For truly
non-stationary noise (music bleed, chatter) the ``separate`` preset routes to
``audio/audio_separate.py`` (Demucs source separation) — this module stays the
single entry point the renderer calls, whatever the preset.

CLI: audio_enhance.py <video_in> <preset> <video_out>
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audio.master import has_audio
from producer_config import AUDIO_ENHANCE, ENCODE

MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
_DISPATCH_SENTINEL = "@"   # catalog values starting with this are not ffmpeg chains
# Characters ffmpeg's filtergraph parser treats as syntax — a models path
# containing one would break arnndn with a misleading parse error.
_FILTERGRAPH_UNSAFE = (",", "'", ":", "\\")


def emit(event: str, **fields) -> None:
    """Emit one NDJSON status line to stdout (worker convention)."""
    print(json.dumps({"event": event, **fields}, default=str), flush=True)


def build_filter(preset: str) -> str:
    """Resolve a preset name to its ffmpeg filter chain.

    Substitutes the literal ``{models}`` token with the vendored-model
    directory's absolute path. Raises ``ValueError`` on an unknown preset, a
    dispatch-only preset (``separate`` is source separation, not a chain), or
    a models dir containing filtergraph syntax characters (``, ' : \\``) —
    substituted unescaped, those would break arnndn with a misleading error,
    so fail loudly with the real cause instead.
    """
    chain = AUDIO_ENHANCE.get(preset)
    if not chain:
        raise ValueError(f"unknown audioEnhance preset {preset!r} "
                         f"(have: {', '.join(sorted(AUDIO_ENHANCE))})")
    if chain.startswith(_DISPATCH_SENTINEL):
        raise ValueError(f"preset {preset!r} is dispatch-only ({chain}) — "
                         "run_audio_enhance routes it; it has no ffmpeg chain")
    if "{models}" in chain:
        bad = [c for c in _FILTERGRAPH_UNSAFE if c in MODELS_DIR]
        if bad:
            raise ValueError(
                f"models dir {MODELS_DIR!r} contains filtergraph syntax "
                f"character(s) {' '.join(repr(c) for c in bad)} — it is "
                "substituted unescaped into the ffmpeg -af chain and would "
                "break arnndn; move the repo to a path without , ' : or \\")
    return chain.replace("{models}", MODELS_DIR)


def apply_enhance(video_in: str, preset: str, video_out: str) -> dict:
    """Run the preset chain on ``video_in``'s audio → ``video_out``.

    Copies the video stream and rebuilds only the audio stream. Returns a
    status dict; reports ffmpeg failure instead of raising (worker convention).
    """
    afilter = build_filter(preset)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-nostats", "-i", video_in,
           "-map", "0:v:0", "-c:v", "copy",
           "-map", "0:a:0", "-af", afilter,
           "-c:a", ENCODE["acodec"], "-b:a", ENCODE["audio_bitrate"],
           "-ar", str(ENCODE["audio_rate"]), "-ac", str(ENCODE["audio_channels"]),
           "-movflags", ENCODE["movflags"], video_out]
    res = subprocess.run(cmd, capture_output=True, text=True)
    ok = res.returncode == 0 and os.path.exists(video_out)
    return {"ok": ok, "preset": preset, "filter": afilter,
            "stderr": "" if ok else res.stderr[-800:]}


def run_audio_enhance(video_in: str, preset: str, video_out: str) -> dict:
    """Validate and apply; returns a status dict for the orchestrator.

    ``separate`` (the ``@`` dispatch sentinel in the catalog) routes to the
    Demucs pipeline in ``audio/audio_separate.py``; every other preset is an
    ffmpeg filter chain applied here. Single entry point for the renderer.
    """
    if not has_audio(video_in):
        return {"status": "error", "error": "input has no audio stream to enhance"}
    if str(AUDIO_ENHANCE.get(preset, "")).startswith(_DISPATCH_SENTINEL):
        from audio.audio_separate import run_separate
        return run_separate(video_in, video_out)
    try:
        result = apply_enhance(video_in, preset, video_out)
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}
    if not result["ok"]:
        return {"status": "error", "error": "ffmpeg enhance pass failed",
                "detail": result["stderr"]}
    return {"status": "ok", "preset": preset, "filter": result["filter"]}


def main() -> None:
    if len(sys.argv) != 4:
        emit("error", error="usage: audio_enhance.py <video_in> <preset> <video_out>")
        sys.exit(2)
    report = run_audio_enhance(sys.argv[1], sys.argv[2], sys.argv[3])
    emit("audio_enhance", **report)
    if report.get("status") != "ok":
        sys.exit(1)


if __name__ == "__main__":
    main()
