"""RTL text and simultaneous-speaker caption edge cases."""
from __future__ import annotations

import unittest

from _caption_fixtures import (
    STYLES,
    compile_fixture,
    explicit_track,
    resolved_words,
)
from captions.caption_ass_projection import build_compiled_ass
from captions.caption_contract import CaptionContractError
from captions.caption_operations import (
    new_correction_ledger,
    upsert_caption_correction,
)
from captions.caption_outputs import cue_text


def _overlapping_speakers() -> list[dict]:
    words = resolved_words(["first", "second"])
    words[0].update(
        speaker="speaker-a", startFrame=0, endFrameExclusive=12)
    words[1].update(
        speaker="speaker-b", startFrame=6, endFrameExclusive=18)
    return words


class RtlCaptionTests(unittest.TestCase):
    def test_arabic_text_and_punctuation_preserve_projection_parity(self) -> None:
        words = resolved_words(["مرحبا", "،", "بالعالم", "؟"])
        track = explicit_track(words, [[0, 1, 2, 3]])
        track["groups"][0].update(
            language="ar", mode="line", styleId="plain")
        compilation = compile_fixture(track, words)
        self.assertEqual(cue_text(compilation["cues"][0]), "مرحبا، بالعالم؟")
        ass = build_compiled_ass(compilation, STYLES)
        self.assertIn("مرحبا، بالعالم؟", ass)
        self.assertNotIn("مرحبا ،", ass)

    def test_bidi_override_controls_fail_closed(self) -> None:
        words = resolved_words(["safe\u202edanger"])
        with self.assertRaisesRegex(
                CaptionContractError, "invalid display text"):
            compile_fixture(explicit_track(words, [[0]]), words)
        clean = resolved_words(["safe"])
        with self.assertRaisesRegex(
                CaptionContractError, "caption control characters"):
            upsert_caption_correction(new_correction_ledger(), {
                "sourceWordIds": [clean[0]["wordId"]],
                "displayTokens": ["safe\u2066hidden\u2069"],
            })


class SpeakerCollisionTests(unittest.TestCase):
    def test_simultaneous_speakers_in_one_band_fail_closed(self) -> None:
        words = _overlapping_speakers()
        with self.assertRaisesRegex(
                CaptionContractError, "speakers collide"):
            compile_fixture(explicit_track(words, [[0], [1]]), words)

    def test_simultaneous_speakers_in_separate_bands_are_allowed(self) -> None:
        words = _overlapping_speakers()
        track = explicit_track(words, [[0], [1]])
        track["groups"][1]["placement"] = "top-center"
        compilation = compile_fixture(track, words)
        self.assertEqual(
            [cue["placement"] for cue in compilation["cues"]],
            ["bottom-center", "top-center"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
