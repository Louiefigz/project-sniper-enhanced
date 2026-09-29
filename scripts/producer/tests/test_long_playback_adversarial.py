"""Long playback coverage, adversarial (X61; adopted from the L-F review probes): the whole-span speed bound, record
hardening, capture guards and the listed plan name. Synthetic only: no server starts, nothing is decoded, no request
is made. ``test_documented_limit_*`` pin the two limits the review accepted (NOTES.md), so a change to them shows.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  first: private budget/pool roots; live state refused

import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from datetime import timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from cut_preview_io import bound_json, write_new
from studio import native_playback_coverage as playback
from test_long_playback_coverage import CLOCK, READER, ROUTE, SERVER, SHA, START, played, report

PLAYER, URL = 'studio.native_handoff_checks.player_row', 'http://127.0.0.1:8123/'


def browser(rate: float, duration: float) -> list[dict]:
    """A page at ``rate``: ``timeupdate`` every 0.25 s of wall time, reported once 2 s of element time passed."""
    rows, last, wall = [report('A', 'playing', 0, 0)], 0.0, 0.0
    while True:
        wall += 0.25
        element = min(duration, rate * wall)
        if element - last >= 2:
            rows.append(report('A', 'timeupdate', element, wall))
            last = element
        if element >= duration:
            break
    return rows + [report('A', 'pause', duration, wall), report('A', 'ended', duration, wall)]


class WholeSpanBoundTests(unittest.TestCase):
    """MAJOR-1 (X61): a span as a whole keeps Δelement <= 1.05·Δserver + 0.5 from its chain's first report."""

    def test_one_x_and_one_point_oh_five_x_are_normal_speed(self) -> None:
        """An honest 1x or 1.05x watch of an 830 s program (C0679's length) covers all of it."""
        for rate in (1.0, 1.05):
            with self.subTest(rate=rate):
                result = playback.coverage(browser(rate, 830.0), ROUTE, 830.0)
                self.assertEqual((result['normalSpeed'], result['coveredSeconds']), (True, 830.0))

    def test_one_point_one_x_and_one_point_three_five_x_are_not(self) -> None:
        """Every 2 s pair of a 1.1x or 1.35x watch fits the pair bound; the span as a whole does not."""
        for rate in (1.1, 1.35):
            with self.subTest(rate=rate):
                self.assertFalse(playback.coverage(browser(rate, 830.0), ROUTE, 830.0)['normalSpeed'])

    def test_each_pair_in_bound_but_not_the_span(self) -> None:
        """1.25x in 2 s steps: 2.5 <= 2.6 per pair, but 5.0 > 4.7 over two; that pair starts no span."""
        rows = [report('A', 'playing', 0, 0)] + [report('A', 'timeupdate', 2.5 * n, 2 * n) for n in (1, 2, 3)]
        self.assertEqual(playback.covered_spans(rows, ROUTE), [(0.0, 2.5), (5.0, 7.5)])

    def test_one_microsecond_burst_is_not_normal_speed(self) -> None:
        """1661 reports 1 µs apart, each 0.5 s further on: no chain passes its first 0.5 s (Δserver 0 is allowed)."""
        rows = [report('A', 'timeupdate', 0.5 * step, 0.000001 * step) for step in range(1661)]
        result = playback.coverage(rows, ROUTE, 830.0)
        self.assertEqual((result['normalSpeed'], result['spans'][0], result['coveredSeconds']),
                         (False, [0.0, 0.5], 415.0))


class SpanRuleProbes(unittest.TestCase):
    """Defences the review probed, pinned here."""

    def test_zero_server_step_is_allowed(self) -> None:
        """Two reports in one microsecond, 0.4 s apart in element time, count."""
        rows = [report('A', 'playing', 3, 7), report('A', 'timeupdate', 3.4, 7)]
        self.assertEqual(playback.covered_spans(rows, ROUTE), [(3.0, 3.4)])

    def test_small_gap_with_full_length_is_not_normal_speed(self) -> None:
        """[0, 50] + [50.3, 100] covers 99.7 >= 99.5 s, but the 0.3 s gap fails the whole-program rule."""
        rows = played('A', 0, 50, 0) + [report('A', 'seeked', 50.3, 51)] + played('A', 50.3, 100, 51)
        self.assertFalse(playback.coverage(rows, ROUTE, 100.0)['normalSpeed'])

    def test_lost_seeked_alone_never_counts_the_paused_pair(self) -> None:
        """Pause reported, seeked lost, 60 s later play from 95 s: the pair after the pause never counts."""
        rows = played('A', 0, 40, 0) + [report('A', 'pause', 41, 41)] + played('A', 95, 100, 101)
        self.assertEqual(playback.covered_spans(rows, ROUTE), [(0.0, 41.0), (95.0, 100.0)])

    def test_forward_seek_while_playing_breaks_by_speed_with_seeked_lost(self) -> None:
        """A destination report 0.3 s after the last one breaks the span by speed."""
        rows = played('A', 0, 40, 0) + [report('A', 'timeupdate', 95, 40.3)] + played('A', 95, 100, 40.3)[1:]
        self.assertEqual(playback.covered_spans(rows, ROUTE), [(0.0, 40.0), (95.0, 100.0)])

    def test_overlapping_tokens_are_not_double_counted(self) -> None:
        """Three pages playing the whole program cover the program length once."""
        rows = played('A', 0, 100, 0) + played('B', 0, 100, 5) + played('C', 0, 100, 9)
        self.assertEqual(playback.coverage(rows, ROUTE, 100.0)['coveredSeconds'], 100.0)

    def test_duplicates_out_of_order_and_mixed_offsets(self) -> None:
        """Duplicated rows change nothing; reversed rows count nothing; +00:00 and -05:00 stamps are one clock."""
        rows = played('A', 0, 20, 0)
        self.assertEqual(playback.covered_spans([row for row in rows for _ in (1, 2)], ROUTE), [(0.0, 20.0)])
        self.assertEqual(playback.covered_spans(rows[::-1], ROUTE), [])
        eastern = timezone(timedelta(hours=-5))
        shifted = [dict(row, time=(START + timedelta(seconds=2 * index)).astimezone(eastern).isoformat())
                   for index, row in enumerate(rows[1:])]
        self.assertEqual(playback.covered_spans(shifted, ROUTE), [(0.0, 20.0)])

    def test_documented_limit_lost_pause_and_seeked_count_the_skipped_range(self) -> None:
        """Both reports lost, 61 s paused, a scrub 41 -> 95 s: still counted (accepted, as hard as E-FORGE-3)."""
        self.assertIn((0.0, 100.0), playback.covered_spans(played('A', 0, 40, 0) + played('A', 95, 100, 101), ROUTE))

    def test_documented_limit_forward_wall_step_admits_an_unreported_jump(self) -> None:
        """A +120 s wall step between two reports admits a 100 s element jump with no seek report (accepted)."""
        rows = [report('A', 'timeupdate', 40, 40), report('A', 'timeupdate', 140, 160)]
        self.assertEqual(playback.covered_spans(rows, ROUTE), [(40.0, 140.0)])


class RecordProbes(unittest.TestCase):
    """check against hand-made bound bytes (MINOR-1 c, d and f; MINOR-2; MINOR-3)."""

    def setUp(self) -> None:
        """A private canonical folder and a genuine record value."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp'))).resolve()
        cover = playback.coverage(played('A', 0, 100.3, 0), ROUTE, 100.3)
        self.value = playback.coverage_record(self.root, {'path': str(self.root / 'review.mp4'), 'sha256': SHA},
                                              {'server': SERVER, 'route': ROUTE}, cover)

    def bind(self, value: dict, name: str) -> playback.CoverageBinding:
        """Write ``value`` as plain JSON and bind its exact bytes."""
        raw = json.dumps(value).encode()
        (self.root / name).write_bytes(raw)
        return playback.CoverageBinding(self.root / name, hashlib.sha256(raw).hexdigest())

    def code(self, binding: playback.CoverageBinding, seconds: float) -> str | None:
        """The refusal code check raises, or None when it verifies."""
        try:
            playback.check(binding, SHA, ROUTE, seconds)
        except playback.CoverageRefused as error:
            return error.code
        return None

    def test_bound_non_canonical_bytes_verify(self) -> None:
        """The sha binding pins the exact bytes, so pretty-printed JSON is accepted (HANDOVER choice 3)."""
        raw = json.dumps(self.value, indent=2).encode()
        (self.root / 'pretty.json').write_bytes(raw)
        binding = playback.CoverageBinding(self.root / 'pretty.json', hashlib.sha256(raw).hexdigest())
        self.assertIsNone(self.code(binding, 100.3))

    def test_mp4_path_and_server_fields_are_type_checked(self) -> None:
        """A non-string mp4 path or a mistyped pid, port or start time is not a record as capture writes it."""
        server = self.value['server']
        for index, change in enumerate(({'mp4': {'path': 7, 'sha256': SHA}}, {'server': {**server, 'pid': 'x'}},
                                        {'server': {**server, 'port': None}}, {'server': {**server, 'started': []}},
                                        {'server': {**server, 'pid': True}}, {'schemaVersion': True})):
            with self.subTest(change=change):
                binding = self.bind({**self.value, **change}, f'typed-{index}.json')
                self.assertEqual(self.code(binding, 100.3), 'COVERAGE_RECORD_CHANGED')

    def test_huge_integers_are_named_refusals_with_one_json_line(self) -> None:
        """A 400-digit span end is RECORD_CHANGED on one JSON line with exit 1, never an OverflowError."""
        self.assertEqual((playback.is_seconds(2 ** 53), playback.is_seconds(2 ** 53 + 1)), (True, False))
        cover = {**self.value['coverage'], 'spans': [[0, 10 ** 400]], 'coveredSeconds': 10 ** 400}
        binding = self.bind({**self.value, 'coverage': cover}, 'huge.json')
        argv = ['check', str(binding.path), '--record-sha256', binding.sha256, '--mp4-sha', SHA, '--route', ROUTE,
                '--seconds', '100.3']
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            self.assertEqual(playback.main(argv), 1)
        self.assertEqual(json.loads(printed.getvalue())['code'], 'COVERAGE_RECORD_CHANGED')

    def test_check_rederives_reach_when_p_exceeds_capture_duration(self) -> None:
        """Captured at D = 60 (normal speed), spans [0, 59.6] + [59.8, 70]: P = 70 is INCOMPLETE, not trusted."""
        rows = played('A', 0, 59.6, 0) + [report('A', 'seeked', 59.8, 60)] + played('A', 59.8, 70, 60)
        cover = playback.coverage(rows, ROUTE, 60.0)
        self.assertTrue(cover['normalSpeed'] and cover['coveredSeconds'] >= 69.5)
        self.assertEqual(self.code(self.bind({**self.value, 'coverage': cover}, 'late.json'), 70.0),
                         'COVERAGE_INCOMPLETE')

    def test_overlapping_spans_with_matching_sum_are_refused(self) -> None:
        """Spans [0, 60] + [50, 90.3] sum to the recorded 100.3 s but are not a disjoint union."""
        cover = {**self.value['coverage'], 'spans': [[0, 60], [50, 90.3]]}
        binding = self.bind({**self.value, 'coverage': cover}, 'overlap.json')
        self.assertEqual(self.code(binding, 100.3), 'COVERAGE_RECORD_CHANGED')

    def test_zero_length_span_in_a_record_is_refused(self) -> None:
        """A [200, 200] span changes neither the sum nor disjointness, yet capture never writes one."""
        cover = {**self.value['coverage'], 'spans': [[0, 100.3], [200, 200]]}
        binding = self.bind({**self.value, 'coverage': cover}, 'zero.json')
        self.assertEqual(self.code(binding, 100.3), 'COVERAGE_RECORD_CHANGED')


class CaptureProbes(unittest.TestCase):
    """capture with a stubbed player row (MINOR-1 a and b; MINOR-2; the listed plan name)."""

    def setUp(self) -> None:
        """A bare attempt whose delivery reader is replaced, as in the main suite."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp'))).resolve()
        self.attempt, self.output = self.root / 'attempt', self.root / 'coverage.json'
        self.attempt.mkdir()
        video = self.attempt / 'review.mp4'
        video.write_bytes(b'TEST bytes ' * 50)
        write_new(self.attempt / 'delivery.json', {'sha256': hashlib.sha256(video.read_bytes()).hexdigest(),
                                                   'output': str(video)})

    def reader(self, export: Path) -> tuple[dict, dict, dict]:
        """Stand-in for checked_delivery: the fixture's delivery as written."""
        return bound_json(export / 'delivery.json'), {'adapter': 'native-long'}, {}

    def row(self, **changes: object) -> dict:
        """A verified player row with a whole-program log, changed as asked."""
        return {'verified': True, 'reason': None, 'server': SERVER, 'route': ROUTE,
                'activity': {'playback': played('A', 0, 100.3, 0)}, **changes}

    def capture(self, row: dict) -> tuple[str | None, bool]:
        """Run capture with ``row`` as the player's answer: (refusal code or None, record written)."""
        with patch(READER, self.reader), patch(CLOCK, return_value=100.3), patch(PLAYER, return_value=row):
            try:
                playback.capture(self.attempt, URL, self.output, None)
            except playback.CoverageRefused as error:
                return error.code, self.output.exists()
        return None, self.output.exists()

    def test_unverified_row_that_still_carries_identity_and_log_is_refused(self) -> None:
        """player_row fills server, route and log before its sha check; verified False must still refuse."""
        row = self.row(verified=False, reason='ViewCheckError: the review player does not serve this exact MP4')
        self.assertEqual(self.capture(row), ('COVERAGE_PLAYER_NOT_VERIFIED', False))

    def test_server_port_other_than_the_url_is_refused(self) -> None:
        """An inventory naming another port is not the server the URL reached."""
        other_port = self.row(server={**SERVER, 'port': 9999})
        self.assertEqual(self.capture(other_port), ('COVERAGE_PLAYER_NOT_VERIFIED', False))

    def test_huge_integer_in_the_player_log_is_a_named_refusal(self) -> None:
        """A 400-digit currentTime is a malformed log (PLAYER_NOT_VERIFIED), never an OverflowError."""
        rows = played('A', 0, 10, 0) + [dict(report('A', 'timeupdate', 11, 11), currentTime=10 ** 400)]
        self.assertEqual(self.capture(self.row(activity={'playback': rows})), ('COVERAGE_PLAYER_NOT_VERIFIED', False))

    def test_never_played_attempt_is_refused_not_recorded(self) -> None:
        """No playback log for the attempt: refused, and nothing is written."""
        self.assertEqual(self.capture(self.row(activity={})), ('COVERAGE_PLAYER_NOT_VERIFIED', False))

    def test_the_listed_plan_name_reaches_the_player_clock(self) -> None:
        """``--plan`` is read with the player's own row rules and passed to its clock; a name it refuses is refused."""
        argv = ['capture', str(self.attempt), '--player', URL, '--output', str(self.output),
                '--plan', 'LONG-PROJECT.json']
        with patch(READER, self.reader), patch(CLOCK, return_value=100.3) as clock, \
                patch(PLAYER, return_value=self.row()), contextlib.redirect_stdout(io.StringIO()) as printed:
            self.assertEqual(playback.main(argv), 0)
        self.assertEqual(clock.call_args.args, ({'adapter': 'native-long'}, 'LONG-PROJECT.json'))
        self.assertEqual(json.loads(printed.getvalue())['record']['path'], str(self.output))
        for plan in ('long.json', '../X.json', 'X.txt'):
            with self.subTest(plan=plan), patch(READER, self.reader), \
                    self.assertRaisesRegex(playback.CoverageRefused, 'COVERAGE_DELIVERY_REFUSED.*plan'):
                playback.delivery_mp4(self.attempt, plan)


if __name__ == '__main__':
    unittest.main()
