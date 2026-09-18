"""Retained real-media proof for the exact P3 phase demo."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from _caption_fixtures import caption_range, resolved_words
from captions.caption_fingerprints import diff_caption_compilations
from captions.caption_operations import (
    new_caption_track,
    new_correction_ledger,
    upsert_caption_correction,
    upsert_caption_range,
)
from captions.caption_shard_composite import apply_caption_shards
from captions.caption_shards import materialize_caption_shards
from fingerprints import file_sha256
from test_caption_shards import (
    _base,
    _compilation,
    _frame_md5,
    _plan,
    _stream_hash,
)


def _style(active: str) -> dict:
    return {
        "font": "Inter", "size": 24, "fill": "#ffffff",
        "activeFill": active, "outline": "#000000",
        "outlinePx": 2, "maxCharsPerLine": 18,
    }


def _before_track(words: list[dict]) -> dict:
    track = new_caption_track("off")
    ranges = (
        caption_range(
            [row["wordId"] for row in words[:2]],
            mode="line", style_id="line"),
        caption_range([words[2]["wordId"]], mode="line", style_id="line"),
        caption_range([words[4]["wordId"]], mode="line", style_id="line"),
        caption_range([words[5]["wordId"]], mode="line", style_id="line"),
    )
    for request in ranges:
        track = upsert_caption_range(track, request)
    return track


def _after_plan(words: list[dict], before_track: dict) -> dict:
    karaoke = upsert_caption_range(
        before_track,
        caption_range(
            [row["wordId"] for row in words[:2]],
            mode="karaoke-phrase"))
    ledger = upsert_caption_correction(new_correction_ledger(), {
        "sourceWordIds": [words[4]["wordId"]],
        "displayTokens": ["John"],
    })
    plan = _plan("short", karaoke, ledger)
    plan["captionStyles"] = {
        "line": _style("#ffffff"),
        "karaoke": _style("#ffe34f"),
    }
    return plan


def _media_keys(manifest: dict) -> dict[str, str]:
    return {
        row["cueId"]: row["mediaKey"]
        for row in manifest["entries"]
    }


def _output_invariants(
    base: str, base_hash: str, incremental: str, forced: str,
) -> dict:
    audio = _stream_hash(base, "0:a:0")
    return {
        "baseUnchanged": file_sha256(base) == base_hash,
        "audioUnchanged": (
            audio == _stream_hash(incremental, "0:a:0")
            == _stream_hash(forced, "0:a:0")),
        "dirtyMatchesForcedFull": (
            _frame_md5(incremental) == _frame_md5(forced)),
    }


def phase_demo_trace(root: str) -> dict:
    """Karaoke one phrase and correct one repeated name, with exact reuse."""
    words = resolved_words(
        ["Project", "Sniper", "Jon", "met", "Jon", "today"], spacing=12)
    before_plan = _plan("short", _before_track(words))
    before_plan["captionStyles"] = {"line": _style("#ffffff")}
    after_plan = _after_plan(words, before_plan["captionsTrack"])
    before = _compilation(before_plan, words)
    after = _compilation(after_plan, words)
    incremental, forced = os.path.join(root, "incremental"), \
        os.path.join(root, "forced")
    os.makedirs(incremental)
    os.makedirs(forced)
    cold = materialize_caption_shards(before_plan, before, incremental)
    warm = materialize_caption_shards(after_plan, after, incremental)
    fresh = materialize_caption_shards(after_plan, after, forced)
    invalidation = diff_caption_compilations(before, after)
    cold_keys, warm_keys = _media_keys(cold.manifest), \
        _media_keys(warm.manifest)
    base = os.path.join(root, "base.mp4")
    _base(base, "short", frames=75)
    base_hash = file_sha256(base)
    incremental_final = os.path.join(incremental, "final.mp4")
    forced_final = os.path.join(forced, "final.mp4")
    shutil.copyfile(base, incremental_final)
    shutil.copyfile(base, forced_final)
    apply_caption_shards(incremental_final, warm.manifest)
    apply_caption_shards(forced_final, fresh.manifest)
    changed = sorted(invalidation["captionCueNodes"])
    unchanged = sorted(set(cold_keys) - set(changed))
    return {
        "mode": "short", "coldRendered": cold.rendered,
        "incrementalCacheHits": warm.cache_hits,
        "incrementalRendered": warm.rendered,
        "forcedRendered": fresh.rendered,
        "dirtyCueNodes": changed,
        "dirtyContentNodes": invalidation["captionContentNodes"],
        "unchangedCueNodes": unchanged,
        "unchangedShardsReused": all(
            cold_keys[cue_id] == warm_keys[cue_id] for cue_id in unchanged),
        "changedShardsRebuilt": all(
            cold_keys[cue_id] != warm_keys[cue_id] for cue_id in changed),
        **_output_invariants(
            base, base_hash, incremental_final, forced_final),
    }


class P3CaptionPhaseDemoTests(unittest.TestCase):
    def test_retained_karaoke_and_repeated_name_demo(self) -> None:
        expected_path = Path(__file__).parent / "fixtures" / \
            "p3-caption-shard-traces.json"
        expected = json.loads(expected_path.read_text())["phaseDemo"]
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(phase_demo_trace(root), expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
