"""Shared caption plan and transcript fixtures for legacy integration."""
from __future__ import annotations

from captions.caption_operations import (
    new_caption_track,
    upsert_caption_range,
)
from captions.caption_words import stable_word_id


def plan() -> dict:
    words = [stable_word_id("raw-a", index) for index in range(3)]
    track = upsert_caption_range(new_caption_track("off"), {
        "wordIds": words, "styleId": "karaoke",
        "mode": "karaoke-word", "placement": "bottom-center",
    })
    return {
        "planVersion": 1,
        "target": {"mode": "short", "scope": "light"},
        "cutTrack": [{"sourceId": "raw-a", "start": 0, "end": 2}],
        "captions": {"burn": True, "style": "karaoke"},
        "captionsTrack": track,
    }


def transcript() -> dict:
    return {"transcript": [{"words": [
        {"word": "Project", "start": 0.1, "end": 0.4},
        {"word": "Sniper", "start": 0.45, "end": 0.8},
        {"word": "works", "start": 0.85, "end": 1.2},
    ]}]}
