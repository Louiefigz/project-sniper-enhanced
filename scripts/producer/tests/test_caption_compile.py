"""Caption cue compilation, suppression, and invalidation tests."""
from __future__ import annotations

import copy
import unittest

from captions.caption_contract import CaptionContractError
from captions.caption_fingerprints import (
    caption_compiler_hash,
    canonical_digest,
    diff_caption_compilations,
)
from captions.caption_operations import (
    new_caption_track,
    new_correction_ledger,
    upsert_caption_correction,
    upsert_caption_range,
)
from _caption_fixtures import (
    caption_range,
    compile_fixture,
    explicit_track,
    resolved_words,
    slices,
)


class CaptionCompilationTests(unittest.TestCase):
    def test_arbitrary_phrase_range_can_enable_karaoke_only_there(self) -> None:
        words = resolved_words(
            ["before", "make", "this", "sing", "after"])
        track = upsert_caption_range(
            new_caption_track("line"),
            caption_range(
                [row["wordId"] for row in words[1:4]],
                mode="karaoke-phrase"))
        result = compile_fixture(track, words)
        rows = {
            tuple(cue["sourceWordIds"]): cue["mode"]
            for cue in result["cues"]
        }
        self.assertEqual(rows[(words[0]["wordId"],)], "line")
        self.assertEqual(
            rows[tuple(row["wordId"] for row in words[1:4])],
            "karaoke-phrase")
        self.assertEqual(rows[(words[4]["wordId"],)], "line")

    def test_off_policy_omits_unselected_words_without_ghosts(self) -> None:
        words = resolved_words(["omit", "keep", "these", "omit"])
        track = explicit_track(words, [[1, 2]])
        result = compile_fixture(track, words)
        self.assertEqual(
            result["coverage"]["renderedWordIds"],
            sorted([words[1]["wordId"], words[2]["wordId"]]))
        self.assertEqual(
            result["coverage"]["omittedWordIds"],
            sorted([words[0]["wordId"], words[3]["wordId"]]))

    def test_tiny_scene_overlap_suppresses_one_word_not_whole_cue(self) -> None:
        words = resolved_words(["visible", "covered", "visible"])
        track = upsert_caption_range(
            new_caption_track(),
            caption_range(
                [row["wordId"] for row in words],
                scene_ids=["takeover"]))
        result = compile_fixture(track, words, scene_windows=[{
            "sceneId": "takeover",
            "startFrame": 17,
            "endFrameExclusive": 18,
        }])
        self.assertEqual(
            result["coverage"]["suppressedWordIds"],
            [words[1]["wordId"]])
        self.assertEqual(len(result["cues"]), 2)
        self.assertEqual(
            [cue["sourceWordIds"] for cue in result["cues"]],
            [[words[0]["wordId"]], [words[2]["wordId"]]])

    def test_multi_token_correction_suppresses_and_shards_atomically(self) -> None:
        words = resolved_words(["ProjectSniper", "works"], duration=12)
        ledger = upsert_caption_correction(new_correction_ledger(), {
            "sourceWordIds": [words[0]["wordId"]],
            "displayTokens": ["Project", "Sniper"],
        })
        track = upsert_caption_range(
            new_caption_track(),
            caption_range(
                [row["wordId"] for row in words],
                scene_ids=["cover"]))
        result = compile_fixture(
            track, words, ledger, max_shard_frames=15,
            scene_windows=[{
                "sceneId": "cover",
                "startFrame": 7,
                "endFrameExclusive": 8,
            }])
        self.assertEqual(
            result["coverage"]["suppressedWordIds"],
            [words[0]["wordId"]])
        self.assertEqual(
            result["cues"][0]["sourceWordIds"], [words[1]["wordId"]])

    def test_bounded_shards_split_only_at_word_boundaries(self) -> None:
        words = resolved_words(["one", "two", "three"])
        track = explicit_track(words, [[0, 1, 2]])
        result = compile_fixture(track, words, max_shard_frames=18)
        self.assertEqual(len(result["cues"]), 2)
        self.assertTrue(all(
            cue["endFrameExclusive"] - cue["startFrame"] <= 18
            for cue in result["cues"]))
        self.assertEqual(
            [ident for cue in result["cues"]
             for ident in cue["sourceWordIds"]],
            [row["wordId"] for row in words])

    def test_oversized_indivisible_correction_fails_closed(self) -> None:
        words = resolved_words(["New", "York"], spacing=10, duration=8)
        ledger = upsert_caption_correction(new_correction_ledger(), {
            "sourceWordIds": [row["wordId"] for row in words],
            "displayTokens": ["New", "York"],
        })
        with self.assertRaisesRegex(CaptionContractError, "shard bound"):
            compile_fixture(
                explicit_track(words, [[0, 1]]), words, ledger,
                max_shard_frames=15)


class CaptionInvalidationTests(unittest.TestCase):
    def test_placement_only_reuses_content_and_never_dirties_base(self) -> None:
        words = resolved_words(["move", "this"])
        before_track = explicit_track(words, [[0, 1]])
        request = caption_range(
            [row["wordId"] for row in words],
            placement="top-center")
        after_track = upsert_caption_range(before_track, request)
        before = compile_fixture(before_track, words)
        after = compile_fixture(after_track, words)
        self.assertEqual(
            before["cues"][0]["captionContentDigest"],
            after["cues"][0]["captionContentDigest"])
        self.assertNotEqual(
            before["cues"][0]["captionCueFingerprint"],
            after["cues"][0]["captionCueFingerprint"])
        receipt = diff_caption_compilations(before, after)
        self.assertFalse(receipt["baseDirty"])
        self.assertEqual(receipt["captionContentNodes"], [])
        self.assertEqual(
            receipt["reusedContentNodes"], [before["cues"][0]["cueId"]])

    def test_timing_change_invalidates_only_owning_cue(self) -> None:
        words = resolved_words(["first", "second"])
        track = explicit_track(words, [[0], [1]])
        before = compile_fixture(track, words)
        changed = copy.deepcopy(words)
        changed[0]["endFrameExclusive"] -= 1
        after = compile_fixture(
            track, changed, timeline_slices=slices(changed))
        self.assertNotEqual(
            before["cues"][0]["captionCueFingerprint"],
            after["cues"][0]["captionCueFingerprint"])
        self.assertEqual(
            before["cues"][1]["captionCueFingerprint"],
            after["cues"][1]["captionCueFingerprint"])
        receipt = diff_caption_compilations(before, after)
        self.assertEqual(receipt["captionContentNodes"], [])
        self.assertEqual(receipt["captionCueNodes"], [
            before["cues"][0]["cueId"]])

    def test_map_slice_change_does_not_fan_out_to_other_cues(self) -> None:
        words = resolved_words(["local", "stable"])
        track = explicit_track(words, [[0], [1]])
        before_slices = slices(words)
        after_slices = dict(before_slices)
        after_slices[words[0]["wordId"]] = canonical_digest(
            "caption-test-slice-v1", "new-map-slice")
        before = compile_fixture(
            track, words, timeline_slices=before_slices)
        after = compile_fixture(
            track, words, timeline_slices=after_slices)
        self.assertNotEqual(
            before["cues"][0]["captionCueFingerprint"],
            after["cues"][0]["captionCueFingerprint"])
        self.assertEqual(
            before["cues"][1]["captionCueFingerprint"],
            after["cues"][1]["captionCueFingerprint"])

    def test_one_correction_dirties_only_its_occurrence_content(self) -> None:
        words = resolved_words(["Jon", "Jon"])
        track = explicit_track(words, [[0], [1]])
        before = compile_fixture(track, words)
        ledger = upsert_caption_correction(new_correction_ledger(), {
            "sourceWordIds": [words[1]["wordId"]],
            "displayTokens": ["John"],
        })
        after = compile_fixture(track, words, ledger)
        self.assertEqual(
            before["cues"][0]["captionContentDigest"],
            after["cues"][0]["captionContentDigest"])
        self.assertNotEqual(
            before["cues"][1]["captionContentDigest"],
            after["cues"][1]["captionContentDigest"])
        self.assertEqual(before["cues"][1]["cueId"], after["cues"][1]["cueId"])
        receipt = diff_caption_compilations(before, after)
        self.assertEqual(
            receipt["captionContentNodes"], [before["cues"][1]["cueId"]])
        self.assertFalse(receipt["baseDirty"])

    def test_non_rendering_correction_reason_does_not_dirty_content(self) -> None:
        words = resolved_words(["Jon"])
        track = explicit_track(words, [[0]])
        first = upsert_caption_correction(new_correction_ledger(), {
            "sourceWordIds": [words[0]["wordId"]],
            "displayTokens": ["John"],
            "reason": "proper name",
        })
        second = upsert_caption_correction(first, {
            "sourceWordIds": [words[0]["wordId"]],
            "displayTokens": ["John"],
            "reason": "operator confirmed spelling",
        })
        before = compile_fixture(track, words, first)
        after = compile_fixture(track, words, second)
        self.assertEqual(
            before["cues"][0]["captionContentDigest"],
            after["cues"][0]["captionContentDigest"])
        self.assertEqual(
            before["cues"][0]["captionCueFingerprint"],
            after["cues"][0]["captionCueFingerprint"])

    def test_non_kept_correction_does_not_invalidate_visible_cues(self) -> None:
        words = resolved_words(["visible"])
        track = explicit_track(words, [[0]])
        ledger = upsert_caption_correction(new_correction_ledger(), {
            "sourceWordIds": ["w-0000000000000000"],
            "displayTokens": ["cut-away"],
        })
        before = compile_fixture(track, words)
        after = compile_fixture(track, words, ledger)
        self.assertEqual(before["cues"], after["cues"])
        self.assertEqual(
            diff_caption_compilations(before, after)["captionCueNodes"], [])

    def test_cue_fingerprint_binds_exact_sample_range(self) -> None:
        words = resolved_words(["clock"], spacing=10, duration=8)
        result = compile_fixture(
            explicit_track(words, [[0]]), words, sample_rate=48_000)
        cue = result["cues"][0]
        self.assertEqual(cue["startSample"], 0)
        self.assertEqual(cue["endSampleExclusive"], 12_800)
        self.assertEqual(cue["sampleRate"], 48_000)

    def test_invalid_destination_safe_zone_fails_closed(self) -> None:
        words = resolved_words(["hidden"])
        destination = {
            "profileId": "broken", "width": 100, "height": 100,
            "safeZones": {"top": 50, "bottom": 50, "left": 0, "right": 0},
        }
        with self.assertRaisesRegex(CaptionContractError, "visible region"):
            compile_fixture(
                explicit_track(words, [[0]]), words,
                destination=destination)

    def test_invalid_global_clock_and_map_fail_even_with_no_cues(self) -> None:
        words = resolved_words(["omitted"])
        track = new_caption_track("off")
        with self.assertRaisesRegex(CaptionContractError, "sample rate"):
            compile_fixture(track, words, sample_rate=0)
        with self.assertRaisesRegex(CaptionContractError, "timeline map"):
            compile_fixture(track, words, timeline_map_hash="not-a-digest")

    def test_bound_global_correction_hash_rejects_wrong_ledger(self) -> None:
        words = resolved_words(["authority"])
        track = explicit_track(words, [[0]])
        track["transcriptCorrectionHash"] = "0" * 64
        with self.assertRaisesRegex(
                CaptionContractError, "different correction ledger"):
            compile_fixture(track, words)

    def test_compiler_hash_binds_declared_render_toolchain(self) -> None:
        first = caption_compiler_hash({
            "chromium": "123", "fontClosure": "font-a"})
        second = caption_compiler_hash({
            "chromium": "124", "fontClosure": "font-a"})
        self.assertRegex(first, r"^[0-9a-f]{64}$")
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main(verbosity=2)
