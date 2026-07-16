#!/usr/bin/env python3
"""music_stage — assemble-time music application (plan.music contract).

plan.music = ``{"enabled": true, "path": "/abs/track" OR "assetId": id,
"duck": true (default), "gapDb": N (optional)}`` is applied at ASSEMBLE time —
post-master, audio-only, video stream copied — and is therefore EXCLUDED from
the base fingerprint (``assemble._NON_BASE_KEYS``): a music edit never costs a
base rebuild. The heavy lifting (bed pre-norm, length fit, sidechain duck,
two-pass loudnorm) is ``audio_mix.py``; this module only resolves the track
and swaps the mixed result over the assembled output in place.
"""
from __future__ import annotations

import json
import os


def emit(**fields) -> None:
    """One NDJSON status line on stdout (matches the render stages)."""
    print(json.dumps(fields), flush=True)


def _locate_manifest(fingerprint_path: str | None,
                     manifest_path: str | None) -> str:
    """The manifest that resolves ``music.assetId``.

    An explicit ``manifest_path`` (the CLI's --manifest) WINS over the
    fingerprint lookup; otherwise the manifestPath recorded in
    base.fingerprint.json is used. Any miss fails loudly — no fallback.
    """
    if manifest_path:
        if not os.path.exists(manifest_path):
            raise RuntimeError(f"--manifest {manifest_path!r} does not exist")
        return manifest_path
    if not fingerprint_path or not os.path.exists(fingerprint_path):
        raise RuntimeError("music.assetId needs --manifest or --fingerprint "
                           "(its manifestPath locates the manifest that "
                           "resolves the asset)")
    with open(fingerprint_path) as f:
        recorded = json.load(f).get("manifestPath")
    if not recorded or not os.path.exists(recorded):
        raise RuntimeError("base.fingerprint.json has no usable manifestPath — "
                           "pass --manifest, re-render the base once, or use "
                           "music.path")
    return recorded


def resolve_music_track(music: dict, fingerprint_path: str | None,
                        manifest_path: str | None = None) -> str:
    """plan.music → an on-disk track: ``path`` (absolute) or manifest assetId.

    The assetId route reads an explicit manifest (``manifest_path``, wins) or
    the one recorded in base.fingerprint.json (manifest music entries carry
    file paths). Any miss fails loudly — no fallback matching.
    """
    path = music.get("path")
    if path:
        if not (os.path.isabs(str(path)) and os.path.isfile(str(path))):
            raise RuntimeError(f"music.path {path!r} is not an absolute "
                               "existing file")
        return str(path)
    asset = music.get("assetId")
    if not asset:
        raise RuntimeError("music.enabled needs music.path or music.assetId")
    resolved = _locate_manifest(fingerprint_path, manifest_path)
    with open(resolved) as f:
        entry = {m["id"]: m for m in json.load(f).get("music", [])}.get(asset)
    if not entry or not entry.get("path") or not os.path.isfile(entry["path"]):
        raise RuntimeError(f"music.assetId {asset!r} does not resolve to an "
                           f"existing file in {resolved}")
    return entry["path"]


def apply_music(plan: dict, out: str, fingerprint_path: str | None,
                manifest_path: str | None = None) -> dict | None:
    """Assemble-time music: lay plan.music under ``out``'s dialogue in place.

    Runs AFTER the graphics composite + YDIF check (audio-only; the video
    stream is copied by audio_mix). ``manifest_path`` (the CLI's --manifest)
    is the preferred assetId resolver over the fingerprint lookup. Returns
    the mix summary, or None when music is absent/disabled.
    """
    music = plan.get("music") or {}
    if not music.get("enabled"):
        return None
    from audio.audio_mix import MixSpec, run_audio_mix
    track = resolve_music_track(music, fingerprint_path, manifest_path)
    duck = bool(music.get("duck", True))
    gap_db = music.get("gapDb")
    emit(status="music_start", track=track, duck=duck, gapDb=gap_db)
    tmp = out + ".music.mp4"
    spec = MixSpec(video_in=out, music=track, out_with=tmp, duck=duck,
                   gap_db=float(gap_db) if gap_db is not None else None)
    result = run_audio_mix(spec)
    if result.get("status") != "done":
        raise RuntimeError(f"music mix failed: {result.get('error')} "
                           f"{result.get('detail', '')}")
    os.replace(tmp, out)
    emit(status="music_done", track=track, duck=duck,
         duck_depth=result.get("duck_depth"), final_lufs=result.get("final_lufs"))
    return result
