"""Real alpha-shard cache, composite, and dirty/full caption proofs."""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from _caption_fixtures import (
    compile_fixture,
    explicit_track,
    resolved_words,
)
from captions.caption_contract import CaptionContractError
from captions.caption_fingerprints import (
    canonical_digest,
    diff_caption_compilations,
)
from captions.caption_operations import (
    new_correction_ledger,
    upsert_caption_correction,
)
from captions.caption_plan_pipeline import caption_styles
from captions.caption_shard_composite import apply_caption_shards
from captions.caption_shard_contract import validate_caption_shard_manifest
from captions.caption_shards import materialize_caption_shards
from captions.caption_words import CaptionFrameRate
from fingerprints import file_sha256

_RATE_BY_MODE = {
    "short": CaptionFrameRate(30_000, 1001),
    "longform": CaptionFrameRate(24_000, 1001),
}
_DESTINATION_BY_MODE = {
    "short": {
        "profileId": "trace-short-9x16", "width": 180, "height": 320,
        "safeZones": {"top": 20, "bottom": 40, "left": 10, "right": 10},
    },
    "longform": {
        "profileId": "trace-long-16x9", "width": 320, "height": 180,
        "safeZones": {"top": 10, "bottom": 20, "left": 20, "right": 20},
    },
}


def _plan(mode: str, track: dict, ledger: dict | None = None) -> dict:
    return {
        "target": {"mode": mode}, "captionsTrack": track,
        "captionCorrectionLedger": ledger or new_correction_ledger(),
        "captionStyles": {
            "karaoke": {
                "font": "Inter", "size": 28, "fill": "#ffffff",
                "activeFill": "#ffe34f", "outline": "#000000",
                "outlinePx": 2, "maxCharsPerLine": 18,
            },
        },
    }


def _compilation(plan: dict, words: list[dict]) -> dict:
    rate = _RATE_BY_MODE[plan["target"]["mode"]]
    return compile_fixture(
        plan["captionsTrack"], words,
        plan["captionCorrectionLedger"], rate=rate,
        destination=_DESTINATION_BY_MODE[plan["target"]["mode"]],
        style_inputs=caption_styles(plan, plan["captionsTrack"]),
        max_shard_frames=60)


def _base(path: str, mode: str, frames: int = 48) -> None:
    destination = _DESTINATION_BY_MODE[mode]
    rate = _RATE_BY_MODE[mode]
    token = f"{rate.numerator}/{rate.denominator}"
    command = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i",
        f"color=c=0x203050:s={destination['width']}x"
        f"{destination['height']}:r={token}",
        "-f", "lavfi", "-i",
        "sine=frequency=440:sample_rate=48000:d=3",
        "-frames:v", str(frames), "-c:v", "libx264",
        "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", path,
    ]
    subprocess.run(command, check=True)


def _stream_hash(path: str, stream: str) -> str:
    process = subprocess.run([
        "ffmpeg", "-v", "error", "-i", path, "-map", stream,
        "-c", "copy", "-f", "hash", "-hash", "sha256", "-",
    ], check=True, capture_output=True, text=True)
    return process.stdout.strip()


def _frame_md5(path: str) -> str:
    process = subprocess.run([
        "ffmpeg", "-v", "error", "-i", path, "-map", "0:v:0",
        "-f", "framemd5", "-",
    ], check=True, capture_output=True, text=True)
    return process.stdout


def _trace(mode: str, root: str) -> dict:
    words = resolved_words(["Project", "Sniper", "works"], spacing=14)
    track = explicit_track(words, [[0], [2]])
    before_plan = _plan(mode, track)
    before = _compilation(before_plan, words)
    incremental = os.path.join(root, "incremental")
    forced = os.path.join(root, "forced")
    os.makedirs(incremental)
    os.makedirs(forced)
    cold = materialize_caption_shards(before_plan, before, incremental)
    ledger = upsert_caption_correction(new_correction_ledger(), {
        "sourceWordIds": [words[2]["wordId"]],
        "displayTokens": ["WORKS"],
    })
    after_plan = _plan(mode, track, ledger)
    after = _compilation(after_plan, words)
    warm = materialize_caption_shards(after_plan, after, incremental)
    fresh = materialize_caption_shards(after_plan, after, forced)
    base = os.path.join(root, "base.mp4")
    _base(base, mode)
    before_base = file_sha256(base)
    incremental_final = os.path.join(incremental, "final.mp4")
    forced_final = os.path.join(forced, "final.mp4")
    shutil.copyfile(base, incremental_final)
    shutil.copyfile(base, forced_final)
    apply_caption_shards(incremental_final, warm.manifest)
    apply_caption_shards(forced_final, fresh.manifest)
    invalidation = diff_caption_compilations(before, after)
    return {
        "mode": mode, "fps": after["fps"],
        "coldRendered": cold.rendered,
        "incrementalCacheHits": warm.cache_hits,
        "incrementalRendered": warm.rendered,
        "forcedRendered": fresh.rendered,
        "dirtyCueNodes": len(invalidation["captionCueNodes"]),
        "baseUnchanged": file_sha256(base) == before_base,
        "audioUnchanged": (
            _stream_hash(base, "0:a:0")
            == _stream_hash(incremental_final, "0:a:0")
            == _stream_hash(forced_final, "0:a:0")),
        "dirtyMatchesForcedFull": (
            _frame_md5(incremental_final) == _frame_md5(forced_final)),
        "unchangedShardReused": (
            cold.manifest["entries"][0]["mediaKey"]
            == warm.manifest["entries"][0]["mediaKey"]),
        "changedShardRebuilt": (
            cold.manifest["entries"][1]["mediaKey"]
            != warm.manifest["entries"][1]["mediaKey"]),
    }


class CaptionShardMediaTests(unittest.TestCase):
    def test_cache_is_alpha_proved_and_tampering_rebuilds_one_shard(self) -> None:
        words = resolved_words(["one", "two"], spacing=14)
        track = explicit_track(words, [[0], [1]])
        plan = _plan("short", track)
        compilation = _compilation(plan, words)
        with tempfile.TemporaryDirectory() as root:
            cold = materialize_caption_shards(plan, compilation, root)
            self.assertEqual((cold.rendered, cold.cache_hits), (2, 0))
            for row in cold.manifest["entries"]:
                self.assertEqual(row["proof"]["stream"]["pix_fmt"], "rgba")
                self.assertGreater(min(row["proof"]["edgeAlphaMax"]), 0)
                self.assertEqual(
                    row["proof"]["shapedSafeBounds"]["framesMeasured"],
                    int(row["proof"]["stream"]["nb_read_frames"]))
            closure = cold.manifest["fontClosure"]
            self.assertRegex(closure["authorityHash"], r"^[0-9a-f]{64}$")
            self.assertTrue(any(
                Path(row["path"]).name == "Inter-Bold.ttf"
                for row in closure["files"]))
            self.assertTrue(all(
                Path(row["path"]).is_file() and len(row["sha256"]) == 64
                for row in closure["files"]))
            warm = materialize_caption_shards(plan, compilation, root)
            self.assertEqual((warm.rendered, warm.cache_hits), (0, 2))
            name = warm.manifest["entries"][1]["media"]["name"]
            Path(root, name).write_bytes(b"tampered")
            repaired = materialize_caption_shards(plan, compilation, root)
            self.assertEqual((repaired.rendered, repaired.cache_hits), (1, 1))
            malformed = copy.deepcopy(cold.manifest)
            malformed["surprise"] = True
            payload = {key: value for key, value in malformed.items()
                       if key != "authorityHash"}
            malformed["authorityHash"] = canonical_digest(
                "sniper-caption-alpha-shard-manifest-v1", payload)
            with self.assertRaisesRegex(
                    CaptionContractError, "unknown or missing fields"):
                validate_caption_shard_manifest(malformed, root)
            stale_font = copy.deepcopy(cold.manifest)
            closure = stale_font["fontClosure"]
            closure["files"][0]["sha256"] = "0" * 64
            font_payload = {key: value for key, value in closure.items()
                            if key != "authorityHash"}
            closure["authorityHash"] = canonical_digest(
                "sniper-caption-font-closure-v1", font_payload)
            manifest_payload = {
                key: value for key, value in stale_font.items()
                if key != "authorityHash"
            }
            stale_font["authorityHash"] = canonical_digest(
                "sniper-caption-alpha-shard-manifest-v1",
                manifest_payload)
            with self.assertRaisesRegex(
                    CaptionContractError, "bytes are missing or stale"):
                validate_caption_shard_manifest(stale_font, root)

    def test_one_frame_cue_proves_its_single_shared_edge(self) -> None:
        words = resolved_words(["flash"], duration=1)
        track = explicit_track(words, [[0]])
        plan = _plan("short", track)
        compilation = _compilation(plan, words)
        with tempfile.TemporaryDirectory() as root:
            shards = materialize_caption_shards(plan, compilation, root)
        proof = shards.manifest["entries"][0]["proof"]
        self.assertEqual(proof["stream"]["nb_read_frames"], "1")
        self.assertEqual(len(proof["edgeAlphaMax"]), 1)
        self.assertEqual(proof["shapedSafeBounds"]["framesMeasured"], 1)

    def test_rtl_and_cjk_fallback_bytes_are_bound_and_safely_shaped(self) -> None:
        words = resolved_words(["مرحبا", "世界"], spacing=14)
        track = explicit_track(words, [[0], [1]])
        track["groups"][0]["language"] = "ar"
        track["groups"][1]["language"] = "zh"
        plan = _plan("short", track)
        compilation = _compilation(plan, words)
        with tempfile.TemporaryDirectory() as root:
            shards = materialize_caption_shards(plan, compilation, root)
        closure = shards.manifest["fontClosure"]
        codepoints = {
            value for row in closure["requests"]
            for value in row["codepoints"]
        }
        self.assertIn("U+0645", codepoints)
        self.assertIn("U+4E16", codepoints)
        self.assertNotIn(
            "lastresort.otf",
            {Path(row["path"]).name.casefold() for row in closure["files"]})
        self.assertTrue(all(
            row["proof"]["shapedSafeBounds"]["framesMeasured"] > 0
            for row in shards.manifest["entries"]))

    def test_retained_short_and_long_dirty_outputs_match_forced_full(self) -> None:
        expected_path = Path(__file__).parent / "fixtures" / \
            "p3-caption-shard-traces.json"
        expected = json.loads(expected_path.read_text())
        actual = []
        with tempfile.TemporaryDirectory() as root:
            for mode in ("short", "longform"):
                mode_root = os.path.join(root, mode)
                os.makedirs(mode_root)
                actual.append(_trace(mode, mode_root))
        self.assertEqual(actual, expected["traces"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
