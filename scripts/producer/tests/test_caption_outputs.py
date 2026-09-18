"""One-authority SRT, burned, Palmier, and chapter projection tests."""
from __future__ import annotations

import copy
import unittest

from captions.caption_contract import CaptionContractError
from captions.caption_ass_projection import build_compiled_ass
from captions.caption_operations import (
    new_correction_ledger,
    upsert_caption_correction,
)
from captions.caption_outputs import (
    PalmierCaptionCapabilities,
    assert_srt_burned_parity,
    build_semantic_chapters,
    build_srt,
    burned_caption_projection,
    compile_chapters,
    cue_text,
    project_captions_to_palmier,
    srt_records,
)
from _caption_fixtures import (
    RATE,
    STYLES,
    compile_fixture,
    explicit_track,
    resolved_words,
)


class CaptionSidecarTests(unittest.TestCase):
    def test_srt_and_burned_share_exact_semantics_and_frame_ranges(self) -> None:
        words = resolved_words(["Hello", ",", "world", "!"], spacing=10)
        compilation = compile_fixture(
            explicit_track(words, [[0, 1, 2, 3]]), words)
        assert_srt_burned_parity(compilation)
        burned = burned_caption_projection(compilation)
        srt = srt_records(compilation)
        self.assertEqual(cue_text(compilation["cues"][0]), "Hello, world!")
        self.assertEqual(
            [(row["text"], row["startFrame"], row["endFrameExclusive"])
             for row in burned],
            [(row["text"], row["startFrame"], row["endFrameExclusive"])
             for row in srt])
        self.assertIn("00:00:00,000 --> 00:00:01,267", build_srt(compilation))

    def test_correction_and_suppression_flow_to_every_projection(self) -> None:
        words = resolved_words(["Jon", "hidden", "speaks"])
        ledger = upsert_caption_correction(new_correction_ledger(), {
            "sourceWordIds": [words[0]["wordId"]],
            "displayTokens": ["John"],
        })
        track = explicit_track(words, [[0, 1, 2]])
        group = track["groups"][0]
        group["suppressUnderSceneIds"] = ["card"]
        compilation = compile_fixture(
            track, words, ledger, scene_windows=[{
                "sceneId": "card",
                "startFrame": 10,
                "endFrameExclusive": 11,
            }])
        texts = [row["text"] for row in srt_records(compilation)]
        self.assertEqual(texts, ["John", "speaks"])
        alpha = project_captions_to_palmier(
            compilation,
            PalmierCaptionCapabilities(False, False, False))
        self.assertEqual(
            [row["elementId"] for row in alpha["entries"]],
            [row["cueId"] for row in compilation["cues"]])

    def test_cjk_language_uses_compact_token_joining(self) -> None:
        words = resolved_words(["你", "好", "，", "世界", "！"])
        track = explicit_track(words, [[0, 1, 2, 3, 4]])
        track["groups"][0]["language"] = "zh-Hans"
        compilation = compile_fixture(track, words)
        self.assertEqual(cue_text(compilation["cues"][0]), "你好，世界！")

    def test_ass_uses_the_same_punctuation_and_cjk_separators(self) -> None:
        words = resolved_words(["Hello", ",", "world"])
        track = explicit_track(words, [[0, 1, 2]])
        track["groups"][0].update(mode="line", styleId="plain")
        compilation = compile_fixture(track, words)
        ass = build_compiled_ass(compilation, STYLES)
        self.assertIn("Hello, world", ass)
        self.assertNotIn("Hello ,", ass)
        cjk = resolved_words(["你", "好"])
        track = explicit_track(cjk, [[0, 1]])
        track["groups"][0].update(
            language="zh-Hans", mode="line", styleId="plain")
        ass = build_compiled_ass(compile_fixture(track, cjk), STYLES)
        self.assertIn("你好", ass)
        self.assertNotIn("你 好", ass)


class PalmierCaptionProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.words = resolved_words(["karaoke", "works"])
        self.compilation = compile_fixture(
            explicit_track(self.words, [[0, 1]]), self.words)

    def test_unproven_fidelity_defaults_to_regenerable_alpha(self) -> None:
        capability = PalmierCaptionCapabilities(
            exact_word_timing=True,
            exact_style=False,
            complete_readback=True,
        )
        result = project_captions_to_palmier(
            self.compilation, capability)
        self.assertEqual(result["kind"], "regenerable-alpha-captions")
        self.assertTrue(result["entries"][0]["regenerable"])

    def test_native_projection_requires_all_facts_and_complete_rows(self) -> None:
        capability = PalmierCaptionCapabilities(True, True, True)
        result = project_captions_to_palmier(
            self.compilation, capability)
        self.assertEqual(result["kind"], "native-caption-cues")
        entry = result["entries"][0]
        self.assertEqual(entry["mode"], "karaoke-word")
        self.assertEqual(
            len(entry["tokens"]), len(self.compilation["cues"][0]["tokens"]))
        self.assertEqual(
            entry["expectedFingerprint"],
            self.compilation["cues"][0]["captionCueFingerprint"])

    def test_detail_row_cap_forces_alpha_instead_of_truncation(self) -> None:
        words = resolved_words(["one", "two"])
        compilation = compile_fixture(
            explicit_track(words, [[0], [1]]), words)
        result = project_captions_to_palmier(
            compilation,
            PalmierCaptionCapabilities(True, True, True, max_detail_rows=1))
        self.assertEqual(result["kind"], "regenerable-alpha-captions")
        self.assertEqual(len(result["entries"]), 2)

    def test_malformed_capability_facts_fail_closed(self) -> None:
        with self.assertRaises(CaptionContractError):
            PalmierCaptionCapabilities(1, True, True)
        with self.assertRaises(CaptionContractError):
            PalmierCaptionCapabilities(True, True, True, max_detail_rows=0)


class ChapterProjectionTests(unittest.TestCase):
    def test_title_uses_code_points_and_explicit_whitespace(self) -> None:
        words = resolved_words(["intro"])

        def chapters(title: str) -> list[dict]:
            return [{
                "chapterId": "chapter-intro",
                "title": title,
                "wordId": words[0]["wordId"],
            }]

        boundary = "😀" * 500
        result = compile_chapters(chapters(boundary), words, RATE)
        self.assertEqual(result["chapters"][0]["title"], boundary)
        padded = "\u0085\ufeffIntro\ufeff\u0085"
        result = compile_chapters(chapters(padded), words, RATE)
        self.assertEqual(result["chapters"][0]["title"], "Intro")
        for title in ("😀" * 501, "\u0085", "\ufeff"):
            with self.subTest(title=repr(title)):
                with self.assertRaises(CaptionContractError):
                    compile_chapters(chapters(title), words, RATE)

    def test_semantic_anchor_moves_with_word_without_changing_identity(self) -> None:
        words = resolved_words(["intro", "topic", "finish"])
        chapters = [{
            "chapterId": "chapter-topic",
            "title": "The Topic",
            "wordId": words[1]["wordId"],
        }]
        before = compile_chapters(chapters, words, RATE)
        moved = copy.deepcopy(words)
        for word in moved[1:]:
            word["startFrame"] += 15
            word["endFrameExclusive"] += 15
        after = compile_chapters(chapters, moved, RATE)
        left, right = before["chapters"][0], after["chapters"][0]
        self.assertEqual(left["chapterId"], right["chapterId"])
        self.assertEqual(left["title"], right["title"])
        self.assertEqual(left["sourceWordId"], right["sourceWordId"])
        self.assertEqual(right["startFrame"] - left["startFrame"], 15)
        self.assertEqual(right["timestampMs"] - left["timestampMs"], 500)
        self.assertEqual(build_semantic_chapters(after), "0:00 The Topic\n")

    def test_non_kept_anchor_and_duplicate_identity_fail(self) -> None:
        words = resolved_words(["intro"])
        missing = [{
            "chapterId": "missing",
            "title": "Missing",
            "wordId": "w-0000000000000000",
        }]
        with self.assertRaisesRegex(CaptionContractError, "non-kept"):
            compile_chapters(missing, words, RATE)
        duplicate = [{
            "chapterId": "same",
            "title": title,
            "wordId": words[0]["wordId"],
        } for title in ("One", "Two")]
        with self.assertRaisesRegex(CaptionContractError, "unique"):
            compile_chapters(duplicate, words, RATE)

    def test_duplicate_word_anchor_fails(self) -> None:
        words = resolved_words(["intro"])
        duplicate = [{
            "chapterId": f"chapter-{index}",
            "title": title,
            "wordId": words[0]["wordId"],
        } for index, title in enumerate(("One", "Two"), start=1)]
        with self.assertRaisesRegex(CaptionContractError, "word anchors"):
            compile_chapters(duplicate, words, RATE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
