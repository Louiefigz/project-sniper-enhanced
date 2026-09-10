#!/usr/bin/env python3
"""plan_lint_audio — audio-field lint (called from plan_lint, mirrors _motion).

Validates the three audio plan contracts before a render is attempted:

* ``plan.audioEnhance`` — ``{"preset": ...}``; the preset must exist in the
  ``producer_config.AUDIO_ENHANCE`` catalog (identifier contract — the brain
  never invents preset names).
* ``plan.audioGain`` — ``[{outStart, outEnd, dB}]`` OUTPUT-time windows;
  reuses ``audio/audio_gain.parse_windows`` (numeric fields, ``outStart <
  outEnd``, dB within ±12) + its overlap check, and bounds every window inside
  the predicted output duration.
* ``plan.music`` source — ``path`` (absolute, existing file) OR ``assetId``
  (must resolve in the manifest); plus ``duck``/``gapDb`` sanity. Called from
  ``plan_lint._check_music_and_misc`` only when music is enabled.
"""
from __future__ import annotations

import os

from audio.audio_gain import overlap_error, parse_windows
from producer_config import AUDIO_ENHANCE

# At 0 dB the bed may equal dialogue. Keep even the hottest supported style
# packs at least 3 dB below voice; the default mixer still targets ~11 dB.
GAP_DB_MIN, GAP_DB_MAX = 3.0, 40.0


def check_audio(plan: dict, out_dur: float, rep) -> None:
    """Validate ``plan.audioEnhance`` + ``plan.audioGain`` (base-side fields)."""
    _check_enhance(plan.get("audioEnhance"), rep)
    _check_gain(plan.get("audioGain"), out_dur, rep)
    _check_authority_mode(plan.get("audioAuthorityMode"), rep)


def _check_authority_mode(value: object, rep) -> None:
    if value is None:
        return
    if value not in {"editable-stems", "mastered-stereo"}:
        rep.error(
            "audioAuthorityMode must be editable-stems or mastered-stereo")


def _check_enhance(enhance: object, rep) -> None:
    """``audioEnhance.preset`` must name a catalog preset."""
    if enhance is None:
        return
    if not isinstance(enhance, dict):
        rep.error("audioEnhance must be an object {\"preset\": ...}")
        return
    preset = enhance.get("preset")
    if preset not in AUDIO_ENHANCE:
        rep.error(f"audioEnhance.preset {preset!r} not in "
                  f"{sorted(AUDIO_ENHANCE)}")


def _check_gain(raw: object, out_dur: float, rep) -> None:
    """``audioGain`` windows: shape via ``parse_windows``, overlap, in-bounds."""
    if raw is None:
        return
    try:
        windows = parse_windows(raw)
    except ValueError as exc:
        rep.error(f"audioGain: {exc}")
        return
    overlap = overlap_error(windows)
    if overlap:
        rep.error(f"audioGain: {overlap}")
    for i, w in enumerate(windows):
        if w.out_end > out_dur + 0.05 or w.out_start < 0:
            rep.error(f"audioGain[{i}]: window [{w.out_start},{w.out_end}] "
                      f"outside output duration {out_dur:.1f}s")


def check_music_source(music: dict, manifest: dict, rep) -> None:
    """Music track resolution + knob sanity (music already known enabled).

    ``path`` (absolute existing file) is accepted as an alternative to
    ``assetId``; when ``path`` is absent the assetId-in-manifest check (or the
    ``vibe`` request for the brain to pick) still applies.
    """
    path = music.get("path")
    if path is not None:
        if not (isinstance(path, str) and os.path.isabs(path)
                and os.path.isfile(path)):
            rep.error(f"music.path {path!r} must be an absolute path to an "
                      "existing audio file")
    else:
        asset = music.get("assetId")
        music_ids = {m["id"] for m in manifest.get("music", [])}
        if asset and asset not in music_ids:
            rep.error(f"music.assetId {asset!r} not in manifest")
        if not asset and not music.get("vibe"):
            rep.error("music enabled but neither path, assetId nor vibe given")
    _check_music_knobs(music, rep)


def _check_music_knobs(music: dict, rep) -> None:
    """Require valid ducking controls and a voice-dominant rest-level gap."""
    duck = music.get("duck")
    if duck is not None and not isinstance(duck, bool):
        rep.error("music.duck must be a boolean")
    elif duck is False:
        rep.error("music.duck=false is not allowed for voice-first output; "
                  "omit it or use true")
    gap = music.get("gapDb")
    if gap is None:
        return
    if not isinstance(gap, (int, float)) or isinstance(gap, bool) \
            or not (GAP_DB_MIN <= float(gap) <= GAP_DB_MAX):
        rep.error(f"music.gapDb must be a number in "
                  f"[{GAP_DB_MIN}, {GAP_DB_MAX}] (got {gap!r})")
