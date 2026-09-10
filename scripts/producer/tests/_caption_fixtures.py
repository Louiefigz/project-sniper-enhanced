"""Small deterministic fixtures for CaptionTrackV1 tests."""
from __future__ import annotations

from captions.caption_compile import CaptionCompileContext, compile_caption_track
from captions.caption_fingerprints import canonical_digest
from captions.caption_operations import (
    new_caption_track,
    new_correction_ledger,
    upsert_caption_range,
)
from captions.caption_words import CaptionFrameRate, stable_word_id

RATE = CaptionFrameRate(30, 1)
DESTINATION = {
    "profileId": "short-9x16",
    "width": 1080,
    "height": 1920,
    "safeZones": {"top": 180, "bottom": 280, "left": 80, "right": 80},
}
STYLES = {
    "default": {"font": "Inter", "size": 72, "fill": "#ffffff"},
    "plain": {"font": "Inter", "size": 64, "fill": "#ffffff"},
    "karaoke": {
        "font": "Inter",
        "size": 76,
        "fill": "#ffffff",
        "activeFill": "#ffe34f",
    },
}


def resolved_words(texts: list[str], spacing: int = 10,
                   duration: int = 8) -> list[dict]:
    """Make ordered resolved words with controller-stable identities."""
    return [{
        "wordId": stable_word_id("raw-a", index),
        "text": text,
        "sourceId": "raw-a",
        "sourceStart": index / 3,
        "sourceEnd": index / 3 + 0.25,
        "startFrame": index * spacing,
        "endFrameExclusive": index * spacing + duration,
    } for index, text in enumerate(texts)]


def caption_range(word_ids: list[str], mode: str = "karaoke-word",
                  style_id: str = "karaoke",
                  **options: object) -> dict:
    """Make one exact stable-word range request."""
    unknown = set(options) - {"placement", "scene_ids", "language"}
    if unknown:
        raise ValueError(f"unknown caption fixture options: {sorted(unknown)}")
    request = {
        "wordIds": word_ids,
        "styleId": style_id,
        "mode": mode,
        "placement": options.get("placement", "bottom-center"),
    }
    scene_ids = options.get("scene_ids")
    if scene_ids is not None:
        request["suppressUnderSceneIds"] = scene_ids
    if "language" in options:
        request["language"] = options["language"]
    return request


def explicit_track(words: list[dict], ranges: list[list[int]]) -> dict:
    """Build an off-by-default track with explicit karaoke groups."""
    track = new_caption_track("off")
    for indices in ranges:
        word_ids = [words[index]["wordId"] for index in indices]
        track = upsert_caption_range(track, caption_range(word_ids))
    return track


def slices(words: list[dict], salt: str = "a") -> dict[str, str]:
    """Make independently mutable per-word timeline slice digests."""
    return {
        row["wordId"]: canonical_digest(
            "caption-test-slice-v1", [salt, row["wordId"]])
        for row in words
    }


def compile_fixture(track: dict, words: list[dict], ledger: dict | None = None,
                    **overrides: object) -> dict:
    """Compile with immutable fixture inputs and optional overrides."""
    values = {
        "track": track,
        "ledger": ledger or new_correction_ledger(),
        "words": words,
        "rate": RATE,
        "timeline_map_hash": canonical_digest(
            "caption-test-map-v1", "map-a"),
        "timeline_slices": slices(words),
        "style_inputs": STYLES,
        "destination": DESTINATION,
        "scene_windows": [],
        "segment_versions": {},
        "max_shard_frames": 120,
        "toolchain": {"chromium": "fixture-1"},
    }
    values.update(overrides)
    return compile_caption_track(CaptionCompileContext(**values))
