"""Pure proof-channel adversaries; no FFmpeg, sources, media or consent."""
from __future__ import annotations

import hashlib
import unittest

from captions.caption_page_proof import page_alpha, page_frame_md5, page_progress
from _caption_page_proof_fixture import alpha_text, expected, md5_text, progress_text


class CaptionPageProofTests(unittest.TestCase):
    """Exact channel/count checks independent of any media process."""

    def test_exact_frame_md5_bytes_are_not_normalized(self) -> None:
        """Whitespace and muxer headers remain part of the old byte hash domain."""
        facts = expected()
        raw = md5_text(facts)
        self.assertEqual(page_frame_md5(raw, facts), hashlib.sha256(raw.encode()).hexdigest())
        changed = raw.replace("        1,", " 1,")
        self.assertNotEqual(page_frame_md5(changed, facts), page_frame_md5(raw, facts))

    def test_integer_ntsc_and_single_frame_clocks(self) -> None:
        """One-frame zero progress time remains count-bound for both rational rates."""
        for rate in ("24/1", "30/1", "30000/1001"):
            facts = expected(1, rate)
            page_frame_md5(md5_text(facts), facts)
            page_progress(progress_text(1), 1)
            self.assertEqual(page_alpha(alpha_text(facts), facts)["framesMeasured"], 1)

    def test_whole_frame_rows_reject_missing_duplicate_or_changed_fields(self) -> None:
        """No missing frame, reordered PTS, partial RGBA payload or foreign header passes."""
        facts, raw = expected(), md5_text(expected())
        mutations = ["\n".join(raw.splitlines()[:-1]) + "\n", raw + raw.splitlines()[-1] + "\n",
                     raw.replace("#tb 0: 1/30", "#tb 0: 1/24"),
                     raw.replace("#tb 0: 1/30", "#tb 0: 1/0"),
                     raw.replace("#dimensions 0: 8x4", "#dimensions 0: 4x8"),
                     raw.replace("     128,", "     127,"), raw.replace("        1,", "        2,"),
                     raw + "#hash: MD5\n", raw.replace("a" * 32, "z" * 32),
                     raw.replace("#hash: MD5", "#hash: SHA256"),
                     raw.replace("#version: 2", "#version: 2\n#version: 2")]
        for changed in mutations:
            with self.subTest(changed=changed[-150:]), self.assertRaises(RuntimeError):
                page_frame_md5(changed, facts)

    def test_alpha_keeps_transparent_frames_and_float_maximum(self) -> None:
        """Every frame is counted, even when a page has transparent gaps."""
        result = page_alpha(alpha_text(expected()), expected())
        self.assertEqual(result, {"alphaMax": 255.0, "framesMeasured": 3})
        self.assertIs(type(result["alphaMax"]), float)

    def test_alpha_rejects_missing_duplicate_bad_pairing_and_nonfinite(self) -> None:
        """No sparse extraction, error line, invalid numeric or transparent-only proof passes."""
        facts, raw = expected(), alpha_text(expected())
        mutations = [raw.split("frame:2")[0], raw + raw, raw + "decoder error\n",
                     raw.replace("frame:1", "frame:0"), raw.replace("pts:1", "pts:-1"),
                     raw.replace("pts:1", "pts:0"), raw.replace("0.033333", "0.000000"),
                     raw.replace("YMAX=255", "YMAX=0"), raw.replace("YMAX=255", "YMAX=256")]
        mutations += [raw.replace("YMAX=255", f"YMAX={value}")
                      for value in ("NaN", "Inf", "1e999", "1..2", "-1")]
        mutations += [raw.replace("pts_time:0.000000", f"pts_time:{value}")
                      for value in ("NaN", "-0.1", "1e999")]
        for changed in mutations:
            with self.subTest(changed=changed[-100:]), self.assertRaises(RuntimeError):
                page_alpha(changed, facts)

    def test_progress_requires_one_final_complete_exact_count(self) -> None:
        """Progress cannot bless partial, duplicated, dropped or torn channel output."""
        raw = progress_text(3)
        mutations = ["", raw + raw, raw + "frame=3\n", raw.replace("end", "continue"),
                     raw.replace("frame=3", "frame=2"), raw.replace("frame=3", "frame=3\nframe=3"),
                     raw.replace("dup_frames=0", "dup_frames=1"),
                     raw.replace("drop_frames=0", "drop_frames=1"), raw.replace("out_time_us=66666", "out_time_us=-1"),
                     progress_text(4, "continue") + raw, raw.replace("end", "unknown")]
        for changed in mutations:
            with self.subTest(changed=changed), self.assertRaises(RuntimeError):
                page_progress(changed, 3)

    def test_progress_accepts_current_nondecreasing_reports(self) -> None:
        """Several equal or advancing reports still require the exact terminal count."""
        page_progress(progress_text(0, "continue") + progress_text(2, "continue") + progress_text(3), 3)

    def test_channels_have_explicit_byte_bounds(self) -> None:
        """Oversized channels fail without a valid-looking truncated result."""
        with self.assertRaisesRegex(RuntimeError, "bound"):
            page_progress("a" * (64 * 1024 + 1), 3)
        for reader in (page_alpha, page_frame_md5):
            with self.subTest(reader=reader.__name__), self.assertRaisesRegex(RuntimeError, "bound"):
                reader("a" * (16 * 1024 * 1024 + 1), expected())


if __name__ == "__main__":
    unittest.main()
