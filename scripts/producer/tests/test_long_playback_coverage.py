"""Long playback coverage (P4-20; M-140 prefab): span math, the whole-program rule, check refusals, capture identity.

All inputs are synthetic (reports built here, records in a private temporary folder, a bare ``delivery.json``
whose reader is replaced only where a test says so). No server starts, nothing is decoded, no request is made.
Capture against a TEST review player and ``test_short_confirm_unchanged`` are M-140's.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  first: private budget/pool roots; live state refused

import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from operator import itemgetter
from pathlib import Path
from unittest.mock import patch

from cut_preview_io import bound_json, file_hash, write_new
from studio import native_playback_coverage as playback

ROUTE, OTHER, SHA = '/media/long.mp4', '/media/other.mp4', 'a' * 64
START = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
SERVER = {'pid': 4242, 'port': 8123, 'startedAt': START.isoformat(timespec='microseconds')}
READER, CLOCK = 'studio.native_review_contract.checked_delivery', 'studio.review_player_inventory.duration_seconds'


def report(token: str, event: str, element: float, server: float) -> dict:
    """One admitted page report as the review player logs it; element and server times in seconds."""
    return {'time': (START + timedelta(seconds=server)).isoformat(timespec='microseconds'), 'token': token,
            'event': event, 'route': ROUTE, 'currentTime': float(element), 'userAgent': 'TEST browser'}


def played(token: str, start: float, end: float, at: float) -> list[dict]:
    """``playing`` at ``start``, then ``timeupdate`` every 2 s of element time to ``end``, at 1x from server ``at``."""
    times = sorted({start + 2 * step for step in range(int((end - start) // 2) + 1)} | {end})
    return [report(token, 'playing', start, at)] + [report(token, 'timeupdate', t, at + t - start) for t in times]


def rounded(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Spans rounded to microseconds for comparison."""
    return [(round(start, 6), round(end, 6)) for start, end in spans]


class SpanMathTests(unittest.TestCase):
    """covered_spans and coverage follow the P4-20 span rule exactly."""

    def test_normal_playback_covers_the_whole_program(self) -> None:
        """Load, play at 1x to the end, ended: one span [0, duration] and normal speed."""
        rows = [report('A', 'loadeddata', 0, 0), *played('A', 0, 100.3, 0), report('A', 'ended', 100.3, 100.4)]
        self.assertEqual(playback.covered_spans(rows, ROUTE), [(0.0, 100.3)])
        result = playback.coverage(rows, ROUTE, 100.3)
        self.assertEqual((result['coveredSeconds'], result['spans'], result['normalSpeed']),
                         (100.3, [[0.0, 100.3]], True))
        self.assertEqual((result['first'], result['last']), (rows[0]['time'], rows[-1]['time']))

    def test_paused_interval_never_counts_even_inside_the_speed_bound(self) -> None:
        """Pause at 41 s, 60 s idle, then 95 s: 54 <= 1.05·60 + 0.5, yet the pause broke the span."""
        rows = [*played('A', 0, 40, 0), report('A', 'pause', 41, 41)]
        self.assertEqual(playback.covered_spans(rows + [report('A', 'timeupdate', 95, 101)], ROUTE), [(0.0, 41.0)])
        resumed = rows + played('A', 41, 80, 101)
        self.assertEqual(playback.covered_spans(resumed, ROUTE), [(0.0, 41.0), (41.0, 80.0)])
        self.assertEqual(playback.coverage(resumed, ROUTE, 80.4)['spans'], [[0.0, 80.0]])

    def test_seek_never_counts_and_play_after_it_does(self) -> None:
        """A 1 s seek inside the speed bound still breaks the span; a far seek leaves a gap."""
        rows = [*played('A', 0, 20, 0), report('A', 'seeked', 21, 20.5), *played('A', 21, 30, 21)]
        self.assertEqual(playback.covered_spans(rows, ROUTE), [(0.0, 20.0), (21.0, 30.0)])
        far = rows + [report('A', 'seeked', 300, 31), *played('A', 300, 310, 31)]
        self.assertEqual(playback.covered_spans(far, ROUTE)[-1], (300.0, 310.0))
        self.assertFalse(playback.coverage(far, ROUTE, 310.0)['normalSpeed'])

    def test_fast_forward_breaks_the_span(self) -> None:
        """A 20 s server step admits at most 1.05·20 + 0.5 = 21.5 s of element time; 2x never counts."""
        self.assertEqual(playback.covered_spans([report('A', 'playing', 0, 0), report('A', 'timeupdate', 21.5, 20)],
                                                ROUTE), [(0.0, 21.5)])
        self.assertEqual(playback.covered_spans([report('A', 'playing', 0, 0), report('A', 'timeupdate', 21.6, 20)],
                                                ROUTE), [])
        doubled = [report('A', 'timeupdate', 2.0 * step, float(step)) for step in range(20)]
        self.assertEqual(playback.covered_spans(doubled, ROUTE), [])

    def test_backward_jump_breaks_the_span(self) -> None:
        """Element time going back with no seek report is never counted as played."""
        rows = [*played('A', 0, 50, 0), report('A', 'timeupdate', 30, 52), *played('A', 30, 40, 53)[1:]]
        self.assertEqual(playback.covered_spans(rows, ROUTE), [(0.0, 50.0), (30.0, 40.0)])
        self.assertEqual(playback.coverage(rows, ROUTE, 50.0)['coveredSeconds'], 50.0)

    def test_two_tokens_union_without_pairing_across_pages(self) -> None:
        """Two tabs interleaved in one log: each page chains only with its own reports (E-PLAY-1)."""
        first, second = played('A', 0, 60, 0), played('B', 60, 120.4, 10)
        log = sorted(first + second, key=itemgetter('time'))
        self.assertEqual(playback.covered_spans(log, ROUTE), [(0.0, 60.0), (60.0, 120.4)])
        self.assertTrue(playback.coverage(log, ROUTE, 120.4)['normalSpeed'])
        other = [dict(row, route=OTHER) for row in second]
        self.assertEqual(playback.covered_spans(first + other, ROUTE), [(0.0, 60.0)])

    def test_clock_step_back_breaks_the_span(self) -> None:
        """A negative server step breaks the span even when the speed bound alone would admit it (E-CLK-1)."""
        stepped = [report('A', 'timeupdate', 30.1 + 2 * step, 29.8 + 2 * step) for step in range(16)]
        rows = played('A', 0, 30, 0) + stepped
        self.assertEqual(rounded(playback.covered_spans(rows, ROUTE)), [(0.0, 30.0), (30.1, 60.1)])
        self.assertFalse(playback.coverage(rows, ROUTE, 60.4)['normalSpeed'])

    def test_whole_program_rule_is_zero_to_duration_minus_half(self) -> None:
        """normalSpeed iff the union covers [0, duration − 0.5]: a late start, a short end or a gap each fail."""
        self.assertTrue(playback.coverage(played('A', 0, 99.5, 0), ROUTE, 100.0)['normalSpeed'])
        self.assertFalse(playback.coverage(played('A', 0, 99.4, 0), ROUTE, 100.0)['normalSpeed'])
        self.assertFalse(playback.coverage(played('A', 0.5, 100, 0), ROUTE, 100.0)['normalSpeed'])
        result = playback.coverage(played('A', 0, 40, 0) + played('B', 41, 100, 50), ROUTE, 100.0)
        self.assertEqual((result['normalSpeed'], result['coveredSeconds']), (False, 99.0))

    def test_malformed_reports_refuse_and_other_routes_are_left_out(self) -> None:
        """A malformed report on the route refuses the reading; another route's rows are not this media."""
        good = played('A', 0, 10, 0)
        for bad in ({'currentTime': float('nan')}, {'currentTime': True}, {'time': '2026-09-28T12:00:10'},
                    {'token': ''}, {'time': None}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                playback.covered_spans(good + [{**good[-1], **bad}], ROUTE)
        self.assertEqual(playback.covered_spans(good + [{'route': OTHER}], ROUTE), [(0.0, 10.0)])
        with self.assertRaises(ValueError):
            playback.coverage(good, ROUTE, 0.5)


class CheckTests(unittest.TestCase):
    """check cold-reads a bound record and refuses by code (D-F b)."""

    def setUp(self) -> None:
        """A private canonical folder; records are built and written exactly as capture does."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp'))).resolve()
        self.mp4 = {'path': str(self.root / 'attempt/review.mp4'), 'sha256': SHA}

    def record(self, rows: list[dict], duration: float) -> playback.CoverageBinding:
        """Write one new record from ``rows`` and bind its path and exact bytes."""
        cover = playback.coverage(rows, ROUTE, duration)
        row = {'server': SERVER, 'route': ROUTE}
        return self.written(playback.coverage_record(self.root / 'attempt', self.mp4, row, cover), 'coverage.json')

    def written(self, value: dict, name: str) -> playback.CoverageBinding:
        """Publish ``value`` with the engine's O_EXCL writer and bind it."""
        write_new(self.root / name, value)
        return playback.CoverageBinding(self.root / name, file_hash(self.root / name, playback.RECORD_LIMIT))

    def refused(self, binding: playback.CoverageBinding, mp4_sha: str, route: str, seconds: float) -> str:
        """The code check refuses with."""
        with self.assertRaises(playback.CoverageRefused) as caught:
            playback.check(binding, mp4_sha, route, seconds)
        return caught.exception.code

    def test_complete_record_verifies_and_never_claims_a_person_watched(self) -> None:
        """A whole-program 1x record passes; its meaning is page-reported playback, never human review."""
        binding = self.record(played('A', 0, 100.3, 0), 100.3)
        result = playback.check(binding, SHA, ROUTE, 100.3)
        self.assertEqual((result['status'], result['coveredSeconds'], result['record']['sha256']),
                         ('coverage-verified', 100.3, binding.sha256))
        stored = bound_json(binding.path, binding.sha256)
        self.assertEqual(set(stored), playback.RECORD_KEYS)
        self.assertEqual(stored['server'], {'pid': 4242, 'port': 8123, 'started': SERVER['startedAt']})
        self.assertEqual(stored['meaning'], 'page-reported playback on the review player clock; '
                                            'not proof a person watched or listened')

    def test_other_route_or_other_mp4_is_route_mismatch(self) -> None:
        """A record of another route or another MP4's bytes is not evidence for this one."""
        binding = self.record(played('A', 0, 100.3, 0), 100.3)
        self.assertEqual(self.refused(binding, SHA, OTHER, 100.3), 'COVERAGE_ROUTE_MISMATCH')
        self.assertEqual(self.refused(binding, 'b' * 64, ROUTE, 100.3), 'COVERAGE_ROUTE_MISMATCH')

    def test_seek_gap_is_not_normal_speed(self) -> None:
        """Skipping 40–60 s by a seek leaves the program not played at normal speed (E-PLAY-2)."""
        rows = played('A', 0, 40, 0) + [report('A', 'seeked', 60, 41)] + played('A', 60, 100.3, 42)
        self.assertEqual(self.refused(self.record(rows, 100.3), SHA, ROUTE, 100.3), 'COVERAGE_NOT_NORMAL_SPEED')

    def test_coverage_shorter_than_the_program_is_incomplete(self) -> None:
        """Covered [0, 60]: P = 60.5 needs [0, 60] and passes; P = 60.6 or 120 is incomplete."""
        binding = self.record(played('A', 0, 60, 0), 60.0)
        self.assertEqual(playback.check(binding, SHA, ROUTE, 60.5)['coveredSeconds'], 60.0)
        for seconds in (60.6, 120.0):
            self.assertEqual(self.refused(binding, SHA, ROUTE, seconds), 'COVERAGE_INCOMPLETE')

    def test_changed_missing_or_malformed_record_is_record_changed(self) -> None:
        """Other bytes, a wrong binding, no file, or a bound file that is not a coverage record as written."""
        binding = self.record(played('A', 0, 100.3, 0), 100.3)
        value = bound_json(binding.path, binding.sha256)
        forged = [{**value, 'meaning': 'a person watched and listened to the whole program'},
                  {**value, 'kind': 'native-visible-handoff'},
                  {**value, 'coverage': {**value['coverage'], 'coveredSeconds': 500.0}},
                  {**value, 'coverage': {**value['coverage'], 'spans': [[0, 60], [50, 100.3]]}}]
        for index, change in enumerate(forged):
            self.assertEqual(self.refused(self.written(change, f'forged-{index}.json'), SHA, ROUTE, 100.3),
                             'COVERAGE_RECORD_CHANGED')
        self.assertEqual(self.refused(playback.CoverageBinding(binding.path, 'c' * 64), SHA, ROUTE, 100.3),
                         'COVERAGE_RECORD_CHANGED')
        binding.path.write_bytes(binding.path.read_bytes() + b' ')
        self.assertEqual(self.refused(binding, SHA, ROUTE, 100.3), 'COVERAGE_RECORD_CHANGED')
        binding.path.unlink()
        self.assertEqual(self.refused(binding, SHA, ROUTE, 100.3), 'COVERAGE_RECORD_CHANGED')

    def test_invalid_inputs_are_errors_not_refusals(self) -> None:
        """A relative path, a malformed digest or a non-finite P is a usage error, never a coverage verdict."""
        binding = self.record(played('A', 0, 10, 0), 10.0)
        calls = [(playback.CoverageBinding(Path('coverage.json'), binding.sha256), SHA, 10.0),
                 (playback.CoverageBinding(binding.path, 'XYZ'), SHA, 10.0), (binding, SHA.upper(), 10.0),
                 (binding, SHA, float('nan'))]
        for bound, mp4_sha, seconds in calls:
            with self.subTest(bound=bound, mp4_sha=mp4_sha), self.assertRaises(ValueError) as caught:
                playback.check(bound, mp4_sha, ROUTE, seconds)
            self.assertNotIsInstance(caught.exception, playback.CoverageRefused)
        with self.assertRaises(ValueError):
            playback.CoverageRefused('COVERAGE_WATCHED', 'no such code')

    def test_cli_prints_one_json_line_with_its_exit_code(self) -> None:
        """check exits 0 when it holds, 1 with the code on a refusal, 2 on a usage error."""
        binding = self.record(played('A', 0, 100.3, 0), 100.3)
        base = ['check', str(binding.path), '--record-sha256', binding.sha256, '--mp4-sha', SHA]
        for tail, code, status in ((['--route', ROUTE, '--seconds', '100.3'], 0, 'coverage-verified'),
                                   (['--route', OTHER, '--seconds', '100.3'], 1, 'refused'),
                                   (['--route', ROUTE, '--seconds', 'nan'], 2, 'error')):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(playback.main(base + tail), code)
            lines = output.getvalue().splitlines()
            self.assertEqual((len(lines), json.loads(lines[0])['status']), (1, status))


class CaptureIdentityTests(unittest.TestCase):
    """capture reads the MP4 identity from the attempt's delivery.json through checked_delivery (D-F a)."""

    def setUp(self) -> None:
        """A bare synthetic attempt: TEST bytes named review.mp4 and a delivery.json naming them."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp'))).resolve()
        self.attempt, self.calls = self.root / 'attempt', []
        self.attempt.mkdir()
        self.video = self.attempt / 'review.mp4'
        self.video.write_bytes(b'TEST bytes, not a real MP4 ' * 40)
        self.sha = hashlib.sha256(self.video.read_bytes()).hexdigest()
        write_new(self.attempt / 'delivery.json', {'status': 'native-long-checked-for-review', 'sha256': self.sha,
                                                   'output': str(self.video), 'fullAudioVideoDecodePassed': True})
        self.identity = {'path': str(self.video), 'sha256': self.sha, 'bytes': 27 * 40}

    def reader(self, export: Path) -> tuple[dict, dict, dict]:
        """Stand-in for checked_delivery: records the call and returns the fixture's delivery as written."""
        self.calls.append(export)
        return bound_json(export / 'delivery.json'), {'adapter': 'native-long'}, {}

    def test_identity_is_the_delivery_output_its_sha_and_stat_bytes(self) -> None:
        """path = delivery.output, sha256 = delivery.sha256, bytes from lstat; seconds from the player's plan clock."""
        with patch(READER, self.reader), patch(CLOCK, return_value=100.3) as clock:
            mp4, seconds = playback.delivery_mp4(self.attempt)
        self.assertEqual((mp4, seconds, self.calls), (self.identity, 100.3, [self.attempt]))
        self.assertEqual(clock.call_args.args, ({'adapter': 'native-long'}, None))

    def test_refused_or_unreadable_delivery_is_named(self) -> None:
        """The real reader refuses a bare delivery.json; a stand-in refusal and a non-file output are named too."""
        with self.assertRaises(playback.CoverageRefused) as caught:
            playback.delivery_mp4(self.attempt)
        self.assertEqual(caught.exception.code, 'COVERAGE_DELIVERY_REFUSED')
        with patch(READER, side_effect=ValueError('unchecked review delivery')), \
                self.assertRaisesRegex(playback.CoverageRefused, 'COVERAGE_DELIVERY_REFUSED.*unchecked'):
            playback.delivery_mp4(self.attempt)
        with patch(READER, self.reader), self.assertRaisesRegex(playback.CoverageRefused, 'DELIVERY_REFUSED.*KeyError'):
            playback.delivery_mp4(self.attempt)  # the stand-in request names no project, so no plan clock
        self.video.unlink()
        self.video.mkdir()
        with patch(READER, self.reader), patch(CLOCK, return_value=100.3), \
                self.assertRaisesRegex(playback.CoverageRefused, 'not a regular MP4'):
            playback.delivery_mp4(self.attempt)

    def test_capture_writes_one_new_record_from_the_verified_player_log(self) -> None:
        """The identity goes to player_row; the CLI writes one record (O_EXCL) and prints the SHA-256 check binds."""
        row = {'verified': True, 'reason': None, 'server': SERVER, 'route': ROUTE,
               'activity': {'playback': played('A', 0, 100.3, 0), 'mediaRequests': []}}
        output, url, printed = self.root / 'coverage.json', 'http://127.0.0.1:8123/', io.StringIO()
        argv = ['capture', str(self.attempt), '--player', url, '--output', str(output)]
        with patch(READER, self.reader), patch(CLOCK, return_value=100.3), \
                patch('studio.native_handoff_checks.player_row', return_value=row) as rows:
            with contextlib.redirect_stdout(printed):
                self.assertEqual(playback.main(argv), 0)
            with self.assertRaises(FileExistsError):
                playback.capture(self.attempt, url, output)
        reported = json.loads(printed.getvalue())
        record = bound_json(output, reported['record']['sha256'])
        self.assertEqual(rows.call_args.args[:3], (url, self.attempt, self.identity))
        self.assertEqual((reported['status'], record['mp4'], record['meaning']),
                         ('captured', {'path': str(self.video), 'sha256': self.sha}, playback.MEANING))
        binding = playback.CoverageBinding(output, reported['record']['sha256'])
        self.assertEqual(playback.check(binding, self.sha, ROUTE, 100.3)['status'], 'coverage-verified')

    def test_unverified_player_writes_nothing(self) -> None:
        """A URL the verified-server path refuses (not loopback) stops capture before any write or request."""
        output = self.root / 'coverage.json'
        with patch(READER, self.reader), patch(CLOCK, return_value=100.3), \
                self.assertRaises(playback.CoverageRefused) as caught:
            playback.capture(self.attempt, 'http://example.com/', output)
        self.assertEqual((caught.exception.code, output.exists()), ('COVERAGE_PLAYER_NOT_VERIFIED', False))


if __name__ == '__main__':
    unittest.main()
