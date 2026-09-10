"""Tiny native libass pixel oracle; no source media, audio, provider or approval."""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

STYLES = {"karaoke": {"font": "Inter", "size": 28, "fill": "#ffffff",
    "activeFill": "#ffe34f", "outline": "#000000", "outlinePx": 2,
    "maxCharsPerLine": 32}}


def compilation(rate: str = "30000/1001") -> dict:
    """Keep the reported FIVE/SIX frame windows on an inert small canvas."""
    numerator, denominator = rate.split("/")
    return {"fps": {"numerator": numerator, "denominator": denominator},
        "destination": {"width": 320, "height": 180,
            "safeZones": {"left": 10, "right": 10, "top": 10, "bottom": 10}},
        "cues": [{"cueId": "TEST-FIVE-SIX", "styleId": "karaoke",
            "mode": "karaoke-word", "placement": "bottom-center",
            "startFrame": 43, "endFrameExclusive": 69,
            "tokens": [{"text": "FIVE", "startFrame": 43, "endFrameExclusive": 54},
                {"text": "SIX", "startFrame": 58, "endFrameExclusive": 69}]}]}


def render(root: Path, ass: str, rate: str) -> np.ndarray:
    """Render 72 small frames with the installed ffmpeg/libass, bounded to 15s."""
    target = root / "TEST.ass"
    target.write_text(ass, encoding="utf8")
    result = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
        f"color=c=black:s=320x180:r={rate}", "-vf", f"format=rgb24,ass={target}",
        "-frames:v", "72", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"],
        capture_output=True, check=True, timeout=15)
    return np.frombuffer(result.stdout, dtype=np.uint8).reshape(72, 180, 320, 3)


def word_regions(reference: np.ndarray, wrapped: bool = False) -> list[tuple[slice, slice]]:
    """Find the verified inter-word/line gap from a separately rendered white phrase."""
    white = reference.min(axis=2) > 200
    occupied = np.flatnonzero(white.any(axis=1 if wrapped else 0))
    assert len(occupied) > 10, "TEST reference phrase has no shaped glyphs"
    gaps = np.diff(occupied)
    index = int(np.argmax(gaps))
    assert gaps[index] > 3, "TEST phrase does not have a distinct word/line gap"
    split = (int(occupied[index]) + int(occupied[index + 1])) // 2
    if wrapped:
        return [(slice(0, split), slice(None)), (slice(split, None), slice(None))]
    return [(slice(None), slice(0, split)), (slice(None), slice(split, None))]


def colors(pixels: np.ndarray, region: tuple[slice, slice]) -> dict[str, int]:
    """Count white and active glyph fills against the inert black background."""
    row = pixels[region]
    active = (row[:, :, 0] > 200) & (row[:, :, 1] > 180) & (row[:, :, 2] < 140)
    return {"white": int(np.sum(row.min(axis=2) > 200)), "active": int(np.sum(active))}


def cache_round(directory: str) -> dict:
    """Actual tiny compiler/shard cache with TEST timeline and real font/tool proofs."""
    from _caption_fixtures import compile_fixture, explicit_track, resolved_words
    from captions.caption_shards import materialize_caption_shards

    words = resolved_words(["FIVE", "SIX"])
    track = explicit_track(words, [[0, 1]])
    target = compilation()["destination"]
    target["profileId"] = "TEST-karaoke-cache"
    plan = {"captionsTrack": track, "captionStyles": STYLES}
    compiled = compile_fixture(track, words, destination=target, style_inputs=STYLES)
    result = materialize_caption_shards(plan, compiled, directory)
    return {"compilerHash": compiled["compilerHash"],
        "cues": compiled["cues"], "cacheHits": result.cache_hits,
        "rendered": result.rendered, "manifest": result.manifest}
