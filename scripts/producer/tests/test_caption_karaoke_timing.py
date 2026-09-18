"""Pure event boundaries and cache source-binding tests; no media or provider."""
from __future__ import annotations

import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _caption_fixtures import compile_fixture, explicit_track, resolved_words
from _caption_karaoke_pixels import STYLES, compilation
from captions import caption_fingerprints as fingerprints
from captions.caption_ass_projection import build_compiled_ass, build_local_cue_ass


def events(document: str) -> list[list[str]]:
    """Read only event fields from the produced ASS text."""
    return [line.split(",", 9) for line in document.splitlines() if line.startswith("Dialogue:")]


class CaptionKaraokeTimingTests(unittest.TestCase):
    """Source timing and caption text must not be rewritten to correct highlighting."""

    def test_token_ends_split_silence_without_next_onset_or_cumulative_karaoke(self) -> None:
        """The three intervals are first word, silence, second word."""
        value = compilation("30/1")
        before = copy.deepcopy(value)
        rows = events(build_compiled_ass(value, STYLES))
        self.assertEqual([(row[1], row[2]) for row in rows],
                         [("0:00:01.43", "0:00:01.80"), ("0:00:01.80", "0:00:01.93"),
                          ("0:00:01.93", "0:00:02.30")])
        self.assertTrue(all("\\k" not in row[9] for row in rows))
        self.assertIn("{\\1c&H004FE3FF&}FIVE", rows[0][9])
        self.assertIn("{\\1c&H00FFFFFF&}SIX", rows[0][9])
        self.assertEqual(rows[1][9].count("&H00FFFFFF"), 2)
        self.assertIn("{\\1c&H00FFFFFF&}FIVE", rows[2][9])
        self.assertIn("{\\1c&H004FE3FF&}SIX", rows[2][9])
        self.assertEqual(value, before)

    def test_ntsc_and_local_shard_use_original_frame_boundaries(self) -> None:
        """No renewal or cumulative rounding when rebasing a local cue."""
        value = compilation()
        rows = events(build_compiled_ass(value, STYLES))
        local = events(build_local_cue_ass(value, value["cues"][0], STYLES))
        self.assertEqual([(row[1], row[2]) for row in rows],
                         [("0:00:01.43", "0:00:01.80"), ("0:00:01.80", "0:00:01.93"),
                          ("0:00:01.93", "0:00:02.30")])
        self.assertEqual([(row[1], row[2]) for row in local],
                         [("0:00:00.00", "0:00:00.36"), ("0:00:00.36", "0:00:00.50"),
                          ("0:00:00.50", "0:00:00.86")])
        self.assertEqual([row[9] for row in rows], [row[9] for row in local])

    def test_real_overlapping_word_spans_are_not_retimed_or_given_invented_priority(self) -> None:
        """Both genuinely concurrent tokens are active during their own overlap."""
        value = compilation()
        value["cues"][0]["tokens"][0]["endFrameExclusive"] = 61
        before = copy.deepcopy(value)
        rows = events(build_compiled_ass(value, STYLES))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1][9].count("&H004FE3FF"), 2)
        self.assertEqual(value, before)

    def _assert_dependency(self, name: str) -> None:
        """Inert TEMP code bytes, not modified live code, drive the actual hash path."""
        self.assertIn(name, fingerprints._COMPILER_SOURCES)
        words = resolved_words(["FIVE", "SIX"])
        track = explicit_track(words, [[0, 1]])
        with tempfile.TemporaryDirectory(prefix="TEST-caption-code-", dir="/private/tmp") as directory:
            source = Path(directory) / name
            source.write_text("# TEST original projection bytes\n")
            with patch.object(fingerprints, "_HERE", directory):
                before = compile_fixture(track, words)
                source.write_text("# TEST changed projection bytes\n")
                after = compile_fixture(track, words)
        self.assertNotEqual(before["compilerHash"], after["compilerHash"])
        for key in ("contentAssetKey", "placedShardKey"):
            self.assertNotEqual(before["cues"][0][key], after["cues"][0][key])
        self.assertEqual(before["cues"][0]["tokens"], after["cues"][0]["tokens"])

    def test_actual_projection_and_shared_formatter_hashes_invalidate_both_cache_keys(self) -> None:
        """Each actual direct dependency participates, including the formerly missing formatter."""
        for name in ("caption_ass_projection.py", "captions_ass.py"):
            self._assert_dependency(name)

    def test_line_and_phrase_documents_preserve_original_exact_bytes(self) -> None:
        """Pre-repair document hashes; phrase remains unchanged, not newly qualified."""
        expected = {"line": "b1f96a00cf7400cad10f11f0357656af3a573731e7747f8fc6919c717c42cacd",
                    "karaoke-phrase": "b832f20974c5c0271a6b2690a8454cb3aa4059cb9363af79f43181512bfdb069"}
        value = compilation()
        for mode, digest in expected.items():
            value["cues"][0]["mode"] = mode
            actual = hashlib.sha256(build_compiled_ass(value, STYLES).encode()).hexdigest()
            self.assertEqual(actual, digest)

    def test_leading_and_trailing_cue_holds_are_white_without_retiming_tokens(self) -> None:
        """Display padding does not imply active speech."""
        value = compilation()
        value["cues"][0].update(startFrame=41, endFrameExclusive=72)
        before = copy.deepcopy(value)
        rows = events(build_compiled_ass(value, STYLES))
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0][9].count("&H00FFFFFF"), 2)
        self.assertEqual(rows[-1][9].count("&H00FFFFFF"), 2)
        self.assertEqual(value, before)


if __name__ == "__main__":
    unittest.main()
