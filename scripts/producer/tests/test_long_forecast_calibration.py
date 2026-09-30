"""M-123 (P4-03): the v2 Long rates, their evidence text, and no x1.21 Short pool factor on an exclusive Long.

v2 prices a plain final at 2.817 s per output second plus 63.8 s (picture 2.364 + early gates 0.18 + QC 0.273), with
the safety factor 1.25 unchanged; v1 keeps its numbers for the rows that froze it. The table rows are P4-LONG section
4.0's table T1 (C0679 at 660 s and at 834.3 s, one heavy slot): the hand-off reserve R, the final forecast and the
latest final start Dp. Its preview rows need the per-owner term (M-123's forecast half) and its latest preview start
the motion-review gap (M-125), so they are asserted where those land. Pure arithmetic over the policy data; no record,
authority or child process.
"""
from __future__ import annotations

import json
import unittest
from functools import partial
from pathlib import Path

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused
from studio.native_budget_forecast import route_seconds
from studio.production import formats, long_policy
from studio.production.long_policy import LONG_POLICY_V1, LONG_POLICY_V2, V2_RATE_SOURCE, duration_evidence

C0679_TEXT = 'C0679 real 4K H.264 footage, 1920x1080 at 24000/1001'
FIXTURE_TEXT = 'technical fixture only (NATIVE_LONG_RELIABILITY_2026-09-16 stress-v4'
NONE_TEXT = ['no measurement at this duration']
WINDOW = 288 * 1001 / 24000   # the default preview packet: 3 windows of 96 frames at 24000/1001, 12.012 s
# (program seconds, measured guarded render seconds): C0679 B, B revision (CRF 6) and A (section 2.4).
C0679_RENDERS = ((657.365, 1430.103), (657.365, 1349.236), (683.766, 1541.357))


def numbers(value: object) -> list[float]:
    """Every number in a nested policy value (bools excluded)."""
    if type(value) is dict:
        return [number for item in value.values() for number in numbers(item)]
    if type(value) is list:
        return [number for item in value for number in numbers(item)]
    return [value] if type(value) in (int, float) else []


class RouteNumberTests(unittest.TestCase):
    """The final and verify routes at the P4-03 numbers; v1 unchanged."""

    def test_v2_is_p4_03s_exact_value(self) -> None:
        """Every v2 number is P4-03's, with the same JSON types; its evidence text is ``V2_RATE_SOURCE``."""
        rates = {'source': V2_RATE_SOURCE, 'safetyFactor': 1.25,
                 'routes': {'preview': {'perOutputSecond': 0.18, 'perWindowSecond': 2.364, 'fixedSeconds': 63.8,
                                        'perOwnerSeconds': 13.3},
                            'final': {'perOutputSecond': 2.817, 'fixedSeconds': 63.8},
                            'verify': {'perOutputSecond': 2.817, 'fixedSeconds': 63.8}},
                 'work': {'picturePerOutputSecond': 2.364, 'earlyGatesPerOutputSecond': 0.18,
                          'qcPerOutputSecond': 0.273, 'masterPerProgramSecond': 0.0686, 'ownerStartSeconds': 13.3,
                          'launchFixedSeconds': 63.8}}
        expected = {'version': 2, 'deliverySeconds': 10800, 'maxOutputSeconds': 900,
                    'handoffReserve': {'playbackPerOutputSecond': 1.0, 'reviewNotesSeconds': 600,
                                       'openConfirmSeconds': 300, 'marginSeconds': 120},
                    'cleanupReserveSeconds': 45, 'routes': ['preview', 'final', 'resume'],
                    'limits': {'repairCycle': 2, 'author': 3, 'review': 8, 'planReview': 2, 'previewLaunch': 2,
                               'exportAttempt': 2, 'pictureGeneration': 2, 'aacCandidate': 6, 'aacPerAudio': 3,
                               'transientRetry': 1},
                    'motionReviewSeconds': 720, 'rates': rates}
        canonical = partial(json.dumps, sort_keys=True, separators=(',', ':'))
        self.assertEqual(canonical(LONG_POLICY_V2), canonical(expected))

    def test_v2_plain_final_number(self) -> None:
        """route_seconds(v2, 'final', 660) = (2.817 x 660 + 63.8) x 1.25 = 2403.775; verify (a resume) is the same."""
        rates = LONG_POLICY_V2['rates']
        self.assertAlmostEqual(route_seconds(rates, 'final', 660.0), 2403.775, delta=1e-6)
        self.assertAlmostEqual(route_seconds(rates, 'resume', 660.0), 2403.775, delta=1e-6)

    def test_v1_numbers_unchanged(self) -> None:
        """v1: final 2492.5 s at 660 s; the packet preview (12.012 s of windows) 325.04 s."""
        rates = LONG_POLICY_V1['rates']
        self.assertEqual(route_seconds(rates, 'final', 660.0), 2492.5)
        self.assertAlmostEqual(route_seconds(rates, 'preview', 660.0, WINDOW), 325.04, delta=0.005)
        self.assertNotIn('perOwnerSeconds', rates['routes']['preview'])

    def test_no_pool_factor_in_v2(self) -> None:
        """No v2 number is a v1 number or a measured term times 1.21; the source says why."""
        rates = LONG_POLICY_V2['rates']
        self.assertIn('not applied to a Long', V2_RATE_SOURCE)
        self.assertIn('no rate was changed to make any output fit', V2_RATE_SOURCE)
        self.assertEqual((rates['routes']['final']['perOutputSecond'], rates['safetyFactor']), (2.817, 1.25))
        scaled = [2.364 * 1.21, 0.18 * 1.21, 0.273 * 1.21, 63.8 * 1.21, 13.3 * 1.21, 2.9, 0.22, 80.0]
        for number in numbers(rates):
            with self.subTest(number=number):
                self.assertFalse(any(abs(number - value) < 0.005 for value in scaled))
        work = rates['work']
        self.assertAlmostEqual(work['picturePerOutputSecond'] + work['earlyGatesPerOutputSecond']
                               + work['qcPerOutputSecond'], rates['routes']['final']['perOutputSecond'], delta=1e-9)

    def test_render_term_never_below_c0679_records(self) -> None:
        """The raw v2 render term (2.364 P + 63.8, before the safety factor) is above every C0679 render."""
        work = LONG_POLICY_V2['rates']['work']
        self.assertEqual((work['picturePerOutputSecond'], work['launchFixedSeconds']), (2.364, 63.8))
        for seconds, measured in C0679_RENDERS:
            with self.subTest(seconds=seconds, measured=measured):
                self.assertGreaterEqual(work['picturePerOutputSecond'] * seconds + work['launchFixedSeconds'], measured)


class DurationEvidenceTests(unittest.TestCase):
    """Per-duration evidence rows, both range ends included."""

    def test_duration_evidence_rows(self) -> None:
        """C0679's range, the 900 s fixture's range, and the honest gap between them (834.3 s)."""
        for seconds in (600, 657.365, 683.766, 700):
            with self.subTest(seconds=seconds):
                self.assertEqual(len(duration_evidence(seconds)), 1)
                self.assertTrue(duration_evidence(seconds)[0].startswith(C0679_TEXT))
        for seconds in (880, 900):
            with self.subTest(seconds=seconds):
                self.assertTrue(duration_evidence(seconds)[0].startswith(FIXTURE_TEXT))
        for seconds in (599.999, 700.001, 834.3, 879.999, 145.933):
            with self.subTest(seconds=seconds):
                self.assertEqual(duration_evidence(seconds), NONE_TEXT)
        self.assertEqual(formats.long_demand(657.365)['evidence'], duration_evidence(657.365))
        self.assertEqual(formats.long_demand(834.3)['evidence'], NONE_TEXT)

    def test_the_false_ten_minute_text_is_gone(self) -> None:
        """The pre-P4 claim that no 10-minute Long export was recorded appears in neither module."""
        for module in (long_policy, formats):
            with self.subTest(module=module.__name__):
                text = Path(module.__file__).read_text(encoding='utf-8')
                self.assertNotIn('no 10-minute Long export has been recorded', text)


class C0679TableTests(unittest.TestCase):
    """Table T1's reserve, final forecast and latest final start, through ``formats`` (+-0.1 s)."""

    def check(self, seconds: float, policy: dict, expected: tuple[float, float, float]) -> None:
        """R, the final forecast and Dp of a Long of ``seconds`` authorized at 0 under ``policy``."""
        preparation, delivery = formats.expected_deadlines('long', 0.0, seconds, policy)
        reserve = formats.long_handoff_seconds(seconds, policy)
        final = delivery - reserve - preparation
        for got, want in zip((reserve, final, preparation), expected):
            self.assertAlmostEqual(got, want, delta=0.1)
        self.assertEqual(delivery, 10800.0)

    def test_p660(self) -> None:
        """P = 660 s: v1 R 1680.0, final 2492.5, Dp 6627.5; v2 R 1680.0, final 2403.8, Dp 6716.2."""
        self.check(660.0, LONG_POLICY_V1, (1680.0, 2492.5, 6627.5))
        self.check(660.0, LONG_POLICY_V2, (1680.0, 2403.8, 6716.2))

    def test_p834(self) -> None:
        """P = 834.3 s: v1 R 1854.3, final 3124.3, Dp 5821.4; v2 R 1854.3, final 3017.5, Dp 5928.2."""
        self.check(834.3, LONG_POLICY_V1, (1854.3, 3124.3, 5821.4))
        self.check(834.3, LONG_POLICY_V2, (1854.3, 3017.5, 5928.2))


if __name__ == '__main__':
    unittest.main()
