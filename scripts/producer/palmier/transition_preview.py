"""Verified alpha-overlay previews for Palmier transition checkpoints.

Palmier has no transition primitive.  Two of Sniper's measured seam covers can
still be shown honestly while a governed plan is being reviewed:

* ``white-flash`` is representable as a three-frame white alpha overlay.  A
  normal alpha composite to white is the same screen-to-white equation used by
  ``motion.transitions`` for this visual lane.
* ``light-leak`` is only an approximation: the final renderer uses a
  luma-screen blend plus a stronger chroma wash, while Palmier currently gives
  the checkpoint executor only a normal alpha overlay.  The asset is therefore
  labeled approximate and never presented as final parity.

``zoom-pull`` is deliberately not mapped here.  Its whip variant requires a
blur-masked peak across two clips, and blindly writing scale keyframes can
overwrite authored punch tracks.  Until Palmier exposes a transition primitive
or the translator owns a verified multi-track keyframe merge, omission is safer
than a false preview.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass

from graphics.asset_proof import AssetProofRequest, prove_rendered_asset
from graphics.graphics_render import DEFAULT_CACHE_DIR

_VERSION = 1
_KINDS = {"white-flash", "light-leak"}
_FLASH_ALPHA = 0.60
_LEAK_SECONDS = 0.375
_LEAK_ATTACK_FRAC = 0.40
_LEAK_PEAK = 0.78 * (210.0 / 255.0)
_MAX_RENDER_AXIS = 1920


@dataclass(frozen=True)
class TransitionPreview:
    """One verified overlay plus its explicit checkpoint limitation."""

    entry: dict
    path: str
    proof: dict
    fidelity: str
    limitation: str


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _frame_window(event: dict, fps: float) -> tuple[int, int, int]:
    seam = round(float(event["outTime"]) * fps)
    if event["kind"] == "white-flash":
        return seam - 1, seam + 2, 3
    frames = max(3, round(_LEAK_SECONDS * fps))
    attack = max(1, round((frames - 1) * _LEAK_ATTACK_FRAC))
    return seam - attack, seam - attack + frames, frames


def _render_dimensions(width: int, height: int) -> tuple[int, int]:
    scale = min(1.0, _MAX_RENDER_AXIS / max(width, height))
    def even(value: int) -> int:
        return max(2, int(round(value * scale)) // 2 * 2)
    return even(width), even(height)


def _alpha_expr(kind: str, frames: int) -> str:
    if kind == "white-flash":
        first = round(255 * _FLASH_ALPHA)
        return f"if(eq(N,0),{first},if(eq(N,1),255,0))"
    attack = max(1, round((frames - 1) * _LEAK_ATTACK_FRAC))
    decay = max(1, frames - 1 - attack)
    peak = round(255 * _LEAK_PEAK)
    return (f"{peak}*min(clip(N/{attack},0,1),"
            f"clip(({frames - 1}-N)/{decay},0,1))")


def _source(kind: str, width: int, height: int, fps: float,
            frames: int) -> str:
    duration = frames / fps
    alpha = _alpha_expr(kind, frames)
    if kind == "white-flash":
        chroma = "cb='cb(X,Y)':cr='cr(X,Y)'"
    else:
        denom = max(1, frames - 1)
        chroma = (f"cb='64+76*N/{denom}':"
                  f"cr='193+4*N/{denom}'")
    return (f"color=c=white:s={width}x{height}:r={fps:g}:d={duration:.9f},"
            "format=yuva444p,"
            f"geq=lum='lum(X,Y)':{chroma}:a='{alpha}'")


def _cache_key(event: dict, fps: float, width: int, height: int) -> str:
    value = {"version": _VERSION, "kind": event.get("kind"), "fps": fps,
             "width": width, "height": height}
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _render(path: str, event: dict, fps: float, width: int,
            height: int, frames: int) -> None:
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i",
           _source(event["kind"], width, height, fps, frames),
           "-frames:v", str(frames), "-an", "-c:v", "prores_ks",
           "-profile:v", "4", "-pix_fmt", "yuva444p10le", path]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()[-6:]
        raise RuntimeError("transition preview render failed: " + "\n".join(detail))
    if not os.path.isfile(path) or os.path.getsize(path) <= 0:
        raise RuntimeError("transition preview render produced no asset")


def _alpha_values(path: str) -> list[float]:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", path,
           "-vf", ("alphaextract,signalstats,metadata=print:"
                   "key=lavfi.signalstats.YAVG:file=-"),
           "-an", "-f", "null", "-"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("transition preview alpha probe failed: "
                           + proc.stderr.strip()[-240:])
    lines = (proc.stdout + proc.stderr).splitlines()
    return [float(line.rsplit("=", 1)[1]) for line in lines
            if "lavfi.signalstats.YAVG=" in line]


def _alpha_profile(kind: str, path: str, frames: int) -> dict:
    values = _alpha_values(path)
    if len(values) != frames:
        raise RuntimeError(
            f"transition alpha proof saw {len(values)} frames, expected {frames}")
    low, high = min(values), max(values)
    if high - low < 50:
        raise RuntimeError("transition alpha proof found no visible envelope")
    normalized = [(value - low) / (high - low) for value in values]
    if kind == "white-flash":
        valid = (normalized.index(max(normalized)) == 1
                 and 0.50 <= normalized[0] <= 0.70
                 and normalized[-1] <= 0.05)
    else:
        peak = normalized.index(max(normalized))
        valid = 0 < peak < frames - 1 \
            and normalized[0] <= 0.05 and normalized[-1] <= 0.05
    if not valid:
        raise RuntimeError(f"transition alpha envelope is malformed: {normalized}")
    return {"frameCount": frames, "min": low, "max": high,
            "normalized": [round(value, 4) for value in normalized]}


def _persist_proof(proof: dict) -> None:
    sidecar = proof.get("sidecar")
    if not isinstance(sidecar, str):
        raise RuntimeError("transition preview proof has no sidecar path")
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=os.path.dirname(sidecar),
        delete=False, prefix=os.path.basename(sidecar) + ".", suffix=".tmp")
    try:
        with handle:
            json.dump(proof, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(handle.name, sidecar)
    finally:
        if os.path.exists(handle.name):
            os.remove(handle.name)


def _synthetic_entry(event: dict, start: int, end: int,
                     fps: float) -> dict:
    return {"kind": f"checkpoint-transition-{event['kind']}",
            "anchor": "free-band", "outStart": start / fps,
            "outEnd": end / fps, "spec": {"transition": event}}


def render_transition_preview(event: dict, fps: float, width: int,
                              height: int,
                              cache_dir: str | None = None) -> TransitionPreview:
    """Render and prove one supported transition preview; raise on bad input."""
    kind, seam = event.get("kind"), event.get("outTime")
    if kind not in _KINDS:
        raise ValueError(f"transition kind {kind!r} has no checkpoint preview")
    if not _number(seam) or float(seam) < 0:
        raise ValueError("transition preview requires a non-negative outTime")
    if not _number(fps) or fps <= 0 or width <= 0 or height <= 0:
        raise ValueError("transition preview requires positive canvas/fps facts")
    start, end, frames = _frame_window(event, float(fps))
    if start < 0:
        raise ValueError("transition preview begins before the timeline")
    render_width, render_height = _render_dimensions(width, height)
    entry = _synthetic_entry(event, start, end, float(fps))
    key = _cache_key(event, float(fps), render_width, render_height)
    directory = cache_dir or DEFAULT_CACHE_DIR
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"transition-preview-{key}.mov")
    if not os.path.isfile(path):
        _render(path, event, float(fps), render_width, render_height, frames)
    proof = prove_rendered_asset(AssetProofRequest(
        path, entry, "mov", (render_width, render_height),
        frames / float(fps), key, float(fps)))
    proof["alphaProfile"] = _alpha_profile(kind, path, frames)
    _persist_proof(proof)
    exact = kind == "white-flash"
    limitation = ("visual-equivalent baked alpha overlay; no native editable "
                  "transition or checkpoint SFX" if exact else
                  "approximate baked alpha overlay; final luma-screen blend, "
                  "stronger chroma wash, and SFX remain render-only")
    return TransitionPreview(entry, path, proof,
                             "baked" if exact else "approximate", limitation)


def supported_transition_kinds() -> tuple[str, ...]:
    """Stable public vocabulary for checkpoint preparation and tests."""
    return tuple(sorted(_KINDS))
