"""Occurrence-aware stable-word resolver regressions."""
from __future__ import annotations

from dataclasses import replace
import unittest

from captions.caption_words import stable_word_id
from edit.target_resolver import (
    PhraseTarget,
    TargetAmbiguousError,
    TargetNotFoundError,
    TargetResolutionError,
    build_word_refs,
    protected_word_ranges,
    resolve_phrase,
)

TIMING_HASH = "a" * 64


def _rows() -> list[dict]:
    texts = (
        ("We", 0, 1_000, "host"),
        ("need", 1_200, 2_000, "host"),
        ("automation.", 2_200, 4_000, "host"),
        ("Then", 5_000, 6_000, "host"),
        ("we", 6_200, 7_000, "host"),
        ("test", 7_200, 8_000, "host"),
        ("automation", 8_200, 10_000, "host"),
        ("again", 10_200, 11_000, "guest"),
    )
    return [
        {
            "word": text,
            "startSample": start,
            "endSampleExclusive": end,
            "speaker": speaker,
        }
        for text, start, end, speaker in texts
    ]


class StableWordTests(unittest.TestCase):
    def test_ids_match_caption_authority_and_timing_hash_stays_separate(self) -> None:
        first = build_word_refs("raw-1", _rows(), TIMING_HASH)
        second = build_word_refs("raw-1", _rows(), TIMING_HASH)
        changed = build_word_refs("raw-1", _rows(), "b" * 64)
        self.assertEqual(
            [word.word_id for word in first],
            [word.word_id for word in second])
        self.assertEqual(first[0].word_id, changed[0].word_id)
        self.assertNotEqual(
            first[0].transcript_timing_hash,
            changed[0].transcript_timing_hash)
        self.assertEqual(first[0].word_id, stable_word_id("raw-1", 0))
        self.assertRegex(first[0].word_id, r"^w-[0-9a-f]{16}$")

    def test_non_integer_sample_authority_fails_instead_of_coercing(self) -> None:
        with self.assertRaises(TargetResolutionError):
            build_word_refs("raw-1", [{
                "word": "automation",
                "startSample": False,
                "endSampleExclusive": 10,
            }], TIMING_HASH)


class PhraseResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.words = build_word_refs("raw-1", _rows(), TIMING_HASH)

    def test_repeated_phrase_requires_disambiguation(self) -> None:
        with self.assertRaises(TargetAmbiguousError):
            resolve_phrase(self.words, PhraseTarget("automation"))

    def test_occurrence_selects_exact_word_and_samples(self) -> None:
        resolved = resolve_phrase(
            self.words, PhraseTarget("automation", occurrence=2))
        self.assertEqual(resolved.occurrence, 2)
        self.assertEqual(resolved.first_word_index, 6)
        self.assertEqual(
            resolved.samples.to_dict(),
            {"startSample": 8_200, "endSampleExclusive": 10_000})
        self.assertEqual(resolved.to_dict()["wordIds"], [self.words[6].word_id])

    def test_boolean_occurrence_is_not_occurrence_one(self) -> None:
        with self.assertRaises(TargetResolutionError):
            resolve_phrase(
                self.words, PhraseTarget("automation", occurrence=True))

    def test_context_and_approximate_sample_resolve_without_guessing(self) -> None:
        by_context = resolve_phrase(
            self.words,
            PhraseTarget("automation", before_context="we test"))
        self.assertEqual(by_context.occurrence, 2)
        by_time = resolve_phrase(
            self.words,
            PhraseTarget(
                "automation",
                approximate_source_sample=3_000,
                tolerance_samples=1_200,
            ))
        self.assertEqual(by_time.occurrence, 1)

    def test_phrase_spans_words_and_preserves_occurrence(self) -> None:
        resolved = resolve_phrase(
            self.words, PhraseTarget("we test automation"))
        self.assertEqual(
            resolved.word_ids,
            tuple(word.word_id for word in self.words[4:7]))
        self.assertEqual(resolved.text, "we test automation")

    def test_phrase_cannot_match_only_part_of_one_transcript_word(self) -> None:
        words = build_word_refs("raw-1", [{
            "word": "can't",
            "startSample": 0,
            "endSampleExclusive": 1_000,
            "speaker": "host",
        }], TIMING_HASH)
        with self.assertRaises(TargetNotFoundError):
            resolve_phrase(words, PhraseTarget("can"))
        self.assertEqual(
            resolve_phrase(words, PhraseTarget("can't")).word_ids,
            (words[0].word_id,))

    def test_speaker_mismatch_fails_instead_of_falling_back(self) -> None:
        with self.assertRaises(TargetNotFoundError):
            resolve_phrase(
                self.words,
                PhraseTarget("automation", occurrence=2, speaker="guest"))

    def test_occurrence_is_scoped_to_the_explicit_source(self) -> None:
        other = build_word_refs("raw-2", [{
            "word": "automation",
            "startSample": 20_000,
            "endSampleExclusive": 22_000,
            "speaker": "host",
        }], TIMING_HASH)
        resolved = resolve_phrase(
            [*self.words, *other],
            PhraseTarget("automation", source_id="raw-2", occurrence=1))
        self.assertEqual(resolved.source_id, "raw-2")
        self.assertEqual(resolved.occurrence, 1)

    def test_occurrence_without_source_remains_ambiguous_across_sources(self) -> None:
        other = build_word_refs("raw-2", [{
            "word": "automation",
            "startSample": 20_000,
            "endSampleExclusive": 22_000,
            "speaker": "host",
        }], TIMING_HASH)
        with self.assertRaisesRegex(TargetAmbiguousError, "source-local"):
            resolve_phrase(
                [*self.words, *other],
                PhraseTarget("automation", occurrence=1))

    def test_context_cannot_cross_a_source_boundary(self) -> None:
        other = build_word_refs("raw-2", [{
            "word": "automation",
            "startSample": 20_000,
            "endSampleExclusive": 22_000,
            "speaker": "host",
        }], TIMING_HASH)
        with self.assertRaises(TargetNotFoundError):
            resolve_phrase(
                [*self.words, *other],
                PhraseTarget(
                    "automation", source_id="raw-2",
                    before_context="again"))

    def test_mixed_timing_authority_for_one_source_fails_closed(self) -> None:
        drifted = list(self.words)
        drifted[1] = replace(
            drifted[1], transcript_timing_hash="b" * 64)
        with self.assertRaisesRegex(TargetResolutionError, "timing drift"):
            resolve_phrase(drifted, PhraseTarget("need"))

    def test_protected_ranges_exclude_only_selected_word_ids(self) -> None:
        resolved = resolve_phrase(
            self.words, PhraseTarget("automation", occurrence=2))
        protected = protected_word_ranges(self.words, resolved)
        self.assertEqual(len(protected), len(self.words) - 1)
        self.assertNotIn(resolved.samples, protected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
