"""edit tests (split from selftest.py)."""
import unittest

from _common import *  # noqa: F401,F403


@unittest.skipUnless(_HAVE_RETAKE, "rapidfuzz not installed")
class RetakeScanTests(unittest.TestCase):
    """Raw-only retake detection: later-take default, guards, clean-take safety."""

    def test_retake_keeps_the_later_take(self) -> None:
        # A flubbed take, a marker, then the clean re-delivery — keep the later.
        utts = [_mk_utt(0, 0.0, "I built this in a single weekend."),
                _mk_utt(1, 3.0, "let me try that again."),
                _mk_utt(2, 6.0, "I built this whole thing in a single weekend.")]
        retakes = rs.build_retakes(utts, rs.find_losers(utts, 10))
        self.assertEqual(len(retakes), 1)
        self.assertEqual(retakes[0].keepStartS, 6.0)          # later take wins
        self.assertAlmostEqual(retakes[0].cutStartS, 0.0)     # cut from the first take
        self.assertFalse(retakes[0].needsOperator)

    def test_clean_takes_find_no_retake(self) -> None:
        # Distinct sentences never re-delivered → nothing to remove.
        utts = [_mk_utt(0, 0.0, "Today we drove up the coast."),
                _mk_utt(1, 4.0, "The weather was perfect the whole way."),
                _mk_utt(2, 8.0, "We stopped for lunch near the lighthouse.")]
        self.assertEqual(rs.build_retakes(utts, rs.find_losers(utts, 10)), [])

    def test_continuation_fragment_is_not_a_retake(self) -> None:
        # An unterminated fragment completed by its very next line is continuous
        # speech, not a re-delivery (the "then it's gonna be" false-positive).
        utts = [_mk_utt(0, 0.0, "then it's gonna be"),
                _mk_utt(1, 1.4, "it's gonna be a total waste.")]
        self.assertEqual(rs.find_losers(utts, 10), {})

    def test_leadin_stumble_absorbed_into_cut(self) -> None:
        # A marker before the matched anchor (not itself a valid take) is pulled
        # backward into the cut span by the lead-in absorber.
        utts = [_mk_utt(0, 0.0, "Oh wait."),
                _mk_utt(1, 1.5, "So here's the plan you run every week."),
                _mk_utt(2, 8.0, "So here's the plan you run every single week.")]
        retakes = rs.build_retakes(utts, rs.find_losers(utts, 10))
        self.assertEqual(len(retakes), 1)
        self.assertEqual(retakes[0].keepStartS, 8.0)
        self.assertAlmostEqual(retakes[0].cutStartS, 0.0)     # absorbed the lead-in

    def test_later_take_worse_is_flagged_not_flipped(self) -> None:
        # The later take stumbles ("built built") and hedges; the winner is still
        # it (never flip), but the proposal raises needsOperator for a human.
        utts = [_mk_utt(0, 0.0, "I built this whole thing in a single weekend."),
                _mk_utt(1, 6.0, "I built built this whole thing in like a "
                                "single weekend you know.")]
        retakes = rs.build_retakes(utts, rs.find_losers(utts, 10))
        self.assertEqual(len(retakes), 1)
        self.assertEqual(retakes[0].keepStartS, 6.0)          # later, still
        self.assertTrue(retakes[0].needsOperator)

    def test_partial_falsestart_is_confident_not_flagged(self) -> None:
        # A short abandoned opening retaken by the full clean line. The long take
        # carries more RAW hedge/markers ONLY because it is long — it must resolve
        # as a confident later-wins, not pull an operator in (the C0679 opening).
        utts = [_mk_utt(0, 0.0, "you run content for clients"),
                _mk_utt(1, 4.0, "if you run a content for clients you lead a "
                                "small media team or a one person shop doing "
                                "every single thing you know")]
        retakes = rs.build_retakes(utts, rs.find_losers(utts, 10))
        self.assertEqual(len(retakes), 1)
        self.assertEqual(retakes[0].keepStartS, 4.0)          # clean take wins
        self.assertEqual(retakes[0].verdict, "later-wins")
        self.assertFalse(retakes[0].needsOperator)            # confident, no human


@unittest.skipUnless(_HAVE_RETAKE, "rapidfuzz not installed")
class PauseScanTests(unittest.TestCase):
    """Pause tightening: over-threshold trims, protected questions, marker dead air."""

    def _report(self, utts):
        return ps.propose(utts, threshold=1.2, residual=0.35, recover_floor=0.5)

    def test_sentence_boundary_gap_proposed(self) -> None:
        # A 1.5s gap after a long (non-thesis) sentence is proposed for
        # tightening, not kept — below the thesis-protect multiple so it isn't
        # mistaken for a deliberate emphasis beat.
        utts = [_mk_utt(0, 0.0, "This is really the whole entire point of what "
                                "we are building here."),
                _mk_utt(1, 6.0, "So let me show you.")]
        report = self._report(utts)
        self.assertEqual(report["proposedTrimCount"], 1)
        self.assertEqual(report["protectedCount"], 0)
        self.assertGreater(report["proposedTrims"][0]["trim_s"], 1.0)

    def test_pause_after_question_is_protected(self) -> None:
        # A rhetorical-question pause is flagged KEEP (car3 precedent).
        utts = [_mk_utt(0, 0.0, "So what is your real priority?"),
                _mk_utt(1, 3.5, "It is not what you think.")]
        report = self._report(utts)
        self.assertEqual(report["protectedCount"], 1)
        self.assertIn("question", report["protectedPauses"][0]["reason"])

    def test_pause_after_marker_is_not_protected(self) -> None:
        # A big pause after a filler line ("Okay.") is dead air to cut, never a
        # protected thesis beat.
        utts = [_mk_utt(0, 0.0, "Okay."),
                _mk_utt(1, 2.5, "Here is the next section.")]
        report = self._report(utts)
        self.assertEqual(report["protectedCount"], 0)
        self.assertEqual(report["proposedTrimCount"], 1)


@unittest.skipUnless(_HAVE_RETAKE, "rapidfuzz not installed")
class RetakeScanV2Tests(unittest.TestCase):
    """Study-pair-2 paths: long-range lookback, restart exception, verdicts."""

    def _spacers(self, first_idx: int, first_start: float) -> list["Utt"]:
        # 11 distinct sentences pushing a re-delivery beyond the 10-utt window.
        lines = ["The weather turned cold near the harbor today.",
                 "Sales numbers doubled after the spring launch.",
                 "Nobody expected the printer to catch fire.",
                 "Our neighbor plays trumpet at midnight sometimes.",
                 "The recipe needs three cups of flour exactly.",
                 "Traffic on the bridge was brutal this morning.",
                 "Her thesis covered medieval trade routes extensively.",
                 "The gym smells like fresh paint this week.",
                 "Migration patterns shifted after the dam opened.",
                 "That documentary about volcanoes won several awards.",
                 "My cousin restores antique clocks for a living."]
        return [_mk_utt(first_idx + i, first_start + 6.0 * i, s)
                for i, s in enumerate(lines)]

    def test_long_range_redelivery_found_and_flagged(self) -> None:
        # A content-heavy failed take re-delivered ~70s later, far beyond the
        # 10-utt window — found by the seconds pass, and ALWAYS flagged for the
        # operator (never auto-cut a minute of footage on fuzzy evidence).
        utts = [_mk_utt(0, 0.0, "You fill out the workbook file once and "
                                "paste the answers into Claude desktop.")]
        utts += self._spacers(1, 8.0)
        utts.append(_mk_utt(12, 78.0, "So you fill out the workbook file once "
                                      "and you paste the answers into Claude "
                                      "desktop, right?"))
        retakes = rs.build_retakes(utts, rs.find_losers(utts, 10, 120.0), 10)
        self.assertEqual(len(retakes), 1)
        self.assertEqual(retakes[0].keepStartS, 78.0)
        self.assertAlmostEqual(retakes[0].cutStartS, 0.0)
        self.assertTrue(retakes[0].longRange)
        self.assertTrue(retakes[0].needsOperator)
        self.assertEqual(retakes[0].verdict, "later-wins")
        # the unrelated contiguous predecessor was NOT absorbed into the keep
        self.assertAlmostEqual(retakes[0].cutEndS, 78.0)

    def test_long_range_beyond_lookback_s_is_ignored(self) -> None:
        # Same shape, but the re-delivery starts past the seconds budget —
        # a distant callback, not a retake.
        utts = [_mk_utt(0, 0.0, "You fill out the workbook file once and "
                                "paste the answers into Claude desktop.")]
        utts += self._spacers(1, 8.0)
        utts.append(_mk_utt(12, 200.0, "So you fill out the workbook file "
                                       "once and you paste the answers into "
                                       "Claude desktop, right?"))
        self.assertEqual(rs.find_losers(utts, 10, 120.0), {})

    def test_long_range_block_winner_walks_back(self) -> None:
        # The failed block's opener ("the angle engine" setup) is re-delivered
        # as its own short utterance BEFORE the matched winner line; the cut
        # must end at the kept block's true start, never mid-block.
        utts = [_mk_utt(0, 0.0, "the angle engine"),
                _mk_utt(1, 2.0, "you fill out the workbook file once and "
                                "paste the answers into Claude desktop")]
        utts += self._spacers(2, 10.0)
        utts.append(_mk_utt(13, 80.0, "the angle engine file."))
        utts.append(_mk_utt(14, 82.0, "So you fill out the workbook file once "
                                      "and you paste the answers into Claude "
                                      "desktop, right?"))
        retakes = rs.build_retakes(utts, rs.find_losers(utts, 10, 120.0), 10)
        self.assertEqual(len(retakes), 1)
        self.assertTrue(retakes[0].longRange)
        self.assertEqual(retakes[0].keepStartS, 80.0)     # walked back to u13
        self.assertAlmostEqual(retakes[0].cutStartS, 0.0)  # lead-in absorbed
        self.assertAlmostEqual(retakes[0].cutEndS, 80.0)

    def test_verbatim_restart_is_a_retake(self) -> None:
        # A consecutive unterminated fragment whose next line re-opens with
        # the SAME full token sequence is a restart (pair-2 "So to make this
        # easy"), not a protected continuation.
        utts = [_mk_utt(0, 0.0, "So to make this easy"),
                _mk_utt(1, 2.0, "So to make this easy, I made a free "
                                "workbook for you.")]
        retakes = rs.build_retakes(utts, rs.find_losers(utts, 10))
        self.assertEqual(len(retakes), 1)
        self.assertEqual(retakes[0].keepStartS, 2.0)
        self.assertAlmostEqual(retakes[0].cutStartS, 0.0)

    def test_worse_later_take_gets_earlier_candidate_verdict(self) -> None:
        # Quality signals favoring the earlier take label the proposal
        # earlier-candidate + needsOperator — but never flip the winner (R21).
        utts = [_mk_utt(0, 0.0, "I built this whole thing in a single weekend."),
                _mk_utt(1, 6.0, "I built built this whole thing in like a "
                                "single weekend you know.")]
        retakes = rs.build_retakes(utts, rs.find_losers(utts, 10))
        self.assertEqual(len(retakes), 1)
        self.assertEqual(retakes[0].keepStartS, 6.0)      # still the later take
        self.assertEqual(retakes[0].verdict, "earlier-candidate")
        self.assertTrue(retakes[0].needsOperator)

    def test_adjacent_independent_retakes_split(self) -> None:
        # Two separate retakes RETAKE_WINDOW apart must yield TWO proposals —
        # the second loser starts after the first winner (pair-2 u41/u45).
        utts = [_mk_utt(0, 0.0, "The workbook turns one pain into angles."),
                _mk_utt(1, 4.0, "The workbook turns one pain point into angles."),
                _mk_utt(2, 9.0, "Personal aside about my dog barking loudly."),
                _mk_utt(3, 14.0, "Another unrelated remark about the studio."),
                _mk_utt(4, 19.0, "Grab the template from the description."),
                _mk_utt(5, 24.0, "Grab the free template from the description below.")]
        retakes = rs.build_retakes(utts, rs.find_losers(utts, 10))
        self.assertEqual(len(retakes), 2)
        self.assertEqual([r.keepStartS for r in retakes], [4.0, 24.0])
        self.assertEqual([r.cutStartS for r in retakes], [0.0, 19.0])

    def test_content_fragment_cannot_win(self) -> None:
        # A 2-content-word fragment ("we have the") can anchor nothing and can
        # never be the take to keep (pair-2 false winner @749.6).
        utts = [_mk_utt(0, 0.0, "we have the brand plan."),
                _mk_utt(1, 3.0, "we have the")]
        self.assertEqual(rs.find_losers(utts, 10), {})


@unittest.skipUnless(_HAVE_RETAKE, "rapidfuzz not installed")
class SpeechCleanupCliTests(unittest.TestCase):
    """F7: EVERY failure must end in a final {"status":"error"} NDJSON line +
    exit 1 — a malformed transcript must never escape as a raw traceback with
    no status line (that breaks the UI contract)."""

    def test_truncated_transcript_emits_error_status(self) -> None:
        producer_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        script = os.path.join(producer_root, "edit", "speech_cleanup.py")
        with tempfile.TemporaryDirectory() as d:
            transcript = os.path.join(d, "t.json")
            with open(transcript, "w") as f:
                f.write('{"transcript": [')            # truncated mid-write
            manifest = os.path.join(d, "manifest.json")
            with open(manifest, "w") as f:
                json.dump({"sources": [{"id": "raw-1", "duration": 30.0,
                                        "transcriptPath": transcript}]}, f)
            proc = subprocess.run([sys.executable, script, manifest],
                                  capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        last = proc.stdout.strip().splitlines()[-1]
        payload = json.loads(last)                     # the UI parses this line
        self.assertEqual(payload.get("status"), "error")
        self.assertTrue(payload.get("error"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
