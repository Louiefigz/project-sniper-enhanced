"""Full production windows must expose gaps without double-counting parallel work."""
import unittest

from stage_timing_report import summarize_timings, workflow_coverage


def span(name: str, start: float, end: float) -> dict:
    """Build explicit telemetry only; these are not execution receipts."""
    return {'stage': name, 'ts': start, 'endTs': end, 'elapsedMs': (end - start) * 1000}


class CoverageTests(unittest.TestCase):
    """Unknown clocks and incomplete totals never become a time target pass."""

    def test_parallel_and_nested_spans_are_unioned(self) -> None:
        """Count overlapping production substages once without implying quality approval."""
        rows = [span('production_total', 0, 100), span('editorial', 10, 40),
                span('search', 20, 50), span('encode', 60, 90), span('audio', 65, 70)]
        result = workflow_coverage(rows)
        self.assertEqual(result['recordedSubstageSeconds'], 70)
        self.assertEqual(result['outsideRecordedSubstagesSeconds'], 30)
        self.assertFalse(result['qualityApproved'])

    def test_missing_multiple_or_stepped_total_stays_unknown(self) -> None:
        """Keep incomplete or contradictory production clocks unavailable."""
        normal = span('production_total', 0, 100)
        for rows in ([], [normal, normal], [{**normal, 'endTs': 1000}]):
            self.assertEqual(workflow_coverage(rows)['status'], 'unavailable')

    def test_invalid_and_outside_work_do_not_inflate_coverage(self) -> None:
        """Exclude invalid intervals and clip valid work to the production window."""
        rows = [span('production_total', 0, 100), span('before', -10, 20),
                span('after', 90, 110), span('outside', 120, 150),
                {**span('clock-step', 10, 20), 'endTs': 40}]
        result = workflow_coverage(rows)
        self.assertEqual(result['recordedSubstageSeconds'], 30)
        self.assertEqual(result['excludedInvalidIntervals'], 1)

    def test_existing_manual_journal_markers_reach_same_report(self) -> None:
        """Read manual start/end markers without treating telemetry as full workflow proof."""
        rows = [{'stage': 'production_total', 'event': 'start', 'mono': 1, 'ts': 100},
                {'stage': 'story', 'event': 'start', 'mono': 2, 'ts': 101},
                {'stage': 'story', 'event': 'end', 'mono': 4, 'ts': 103},
                {'stage': 'production_total', 'event': 'end', 'mono': 6, 'ts': 105}]
        report = summarize_timings(rows)
        self.assertEqual(report['recordedWindow']['elapsedSeconds'], 5)
        self.assertEqual(report['recordedWindow']['outsideRecordedSubstagesSeconds'], 3)
        self.assertEqual(report['workflowCoverage'], 'not-established-by-telemetry-alone')


def run_span(name: str, start: float, end: float, run: str, **fields: object) -> dict:
    """A paired v2 span of one run; parentSpanId links it into that run's lineage."""
    return {**span(name, start, end), 'runId': run, 'spanId': fields.pop('spanId', name), **fields}


class RunScopedCoverageTests(unittest.TestCase):
    """Only the chosen run's descendant work fills its window; everything else stays apart."""

    def test_unrelated_run_never_fills_the_authorized_window(self) -> None:
        """The verifier's exact counterexample: expected zero coverage, not 100 s."""
        spans = [{'stage': 'production_total', 'ts': 1000, 'endTs': 1100, 'elapsedMs': 100000,
                  'runId': 'authorized-run'},
                 {'stage': 'other-work', 'ts': 1000, 'endTs': 1100, 'elapsedMs': 100000,
                  'runId': 'unrelated-run'}]
        result = workflow_coverage(spans)
        self.assertEqual((result['recordedSubstageSeconds'], result['outsideRecordedSubstagesSeconds']), (0, 100))
        self.assertEqual((result['foreignRunSeconds'], result['foreignRunSpans']), (100, 1))

    def test_parallel_runs_need_an_explicit_choice_and_stay_separate(self) -> None:
        spans = [run_span('production_total', 0, 100, 'A', spanId='wa'),
                 run_span('production_total', 0, 100, 'B', spanId='wb'),
                 run_span('a-edit', 10, 40, 'A', parentSpanId='wa'),
                 run_span('b-edit', 20, 90, 'B', parentSpanId='wb')]
        self.assertEqual(workflow_coverage(spans)['productionRuns'], ['A', 'B'])
        a, b = workflow_coverage(spans, 'A'), workflow_coverage(spans, 'B')
        # The other run's own window is foreign work too: 100 s, two spans, counted nowhere here.
        self.assertEqual((a['recordedSubstageSeconds'], a['foreignRunSeconds'], a['foreignRunSpans']), (30, 100, 2))
        self.assertEqual((b['recordedSubstageSeconds'], b['foreignRunSeconds'], b['foreignRunSpans']), (70, 100, 2))
        report = summarize_timings([], 'A')
        self.assertEqual(report['attribution']['runScope'], 'A')

    def test_restart_attempts_count_only_through_recorded_ancestry(self) -> None:
        spans = [run_span('production_total', 0, 100, 'R', spanId='w', attemptId='a1'),
                 run_span('owner', 10, 30, 'R', parentSpanId='w', attemptId='a1'),
                 run_span('worker', 12, 28, 'R', parentSpanId='owner', attemptId='a1'),
                 run_span('resumed', 50, 70, 'R', parentSpanId='w', attemptId='a2'),
                 run_span('resumed-unlinked', 75, 95, 'R', parentSpanId='lost-parent', attemptId='a2')]
        result = workflow_coverage(spans, 'R')
        self.assertEqual(result['lineageScope'], 'run-descendants')
        self.assertEqual(result['recordedSubstageSeconds'], 40)
        self.assertEqual((result['unparentedSameRunSeconds'], result['unparentedSameRunSpans']), (20, 1))

    def test_unparented_and_open_ancestors_are_reported_not_counted(self) -> None:
        spans = [run_span('production_total', 0, 100, 'R', spanId='w'),
                 run_span('loose', 0, 50, 'R'),
                 run_span('under-open', 60, 80, 'R', parentSpanId='still-open')]
        open_parent = {'stage': 'open', 'spanId': 'still-open', 'parentSpanId': 'w', 'runId': 'R'}
        self.assertEqual(workflow_coverage(spans, 'R')['recordedSubstageSeconds'], 0)
        linked = workflow_coverage(spans, 'R', (open_parent,))
        self.assertEqual((linked['recordedSubstageSeconds'], linked['unparentedSameRunSeconds']), (20, 50))


class WindowIntegrityTests(unittest.TestCase):
    """A crashed window, lineage-less spans and cross-run parents never distort coverage."""

    def test_a_crashed_earlier_window_is_never_hidden_by_a_later_one(self) -> None:
        crashed = {'stage': 'production_total', 'spanId': 'w1', 'runId': 'R', 'ts': 1000}
        spans = [run_span('production_total', 1050, 1100, 'R', spanId='w2'),
                 run_span('before-crash', 1010, 1040, 'R', parentSpanId='w1')]
        result = workflow_coverage(spans, 'R', (crashed,))
        self.assertEqual((result['startedAtEpoch'], result['elapsedSeconds'], result['openWindows']), (1000, 100, 1))
        self.assertEqual(result['closedWindowStartedAtEpoch'], 1050)
        self.assertEqual(result['recordedSubstageSeconds'], 30, 'work under the crashed window still counts')
        for bad in ({**crashed, 'ts': 1200}, {**crashed, 'ts': 'unknown'}):
            self.assertEqual(workflow_coverage(spans, 'R', (bad,))['status'], 'unavailable')

    def test_the_crash_case_through_the_journal_reader(self) -> None:
        def row(event: str, ts: float, span: str) -> dict:
            return {'schemaVersion': 2, 'stage': 'production_total', 'event': event, 'ts': ts, 'mono': ts,
                    'runId': 'R', 'attemptId': 'a', 'attemptNo': 1, 'writerId': 'manual-marker',
                    'clock': 'wall-epoch', 'spanId': span, 'status': 'completed', 'elapsedMs': 50000}
        report = summarize_timings([row('start', 1000, 'w1'), row('start', 1050, 'w2'), row('end', 1100, 'w2')], 'R')
        self.assertEqual((report['recordedWindow']['startedAtEpoch'], report['recordedWindow']['elapsedSeconds']),
                         (1000, 100))

    def test_lineage_less_spans_are_unknown_lineage_never_foreign(self) -> None:
        legacy_span = span('render', 10, 30)
        versioned = [run_span('production_total', 0, 100, 'R', spanId='w'), legacy_span]
        result = workflow_coverage(versioned, 'R')
        self.assertEqual((result['unknownLineageSeconds'], result['foreignRunSeconds']), (20, 0))
        legacy = [span('production_total', 0, 100), legacy_span, run_span('owner', 40, 60, 'R', parentSpanId='x')]
        result = workflow_coverage(legacy)
        self.assertEqual(result['lineageScope'], 'legacy-run-less-spans-only')
        self.assertEqual((result['recordedSubstageSeconds'], result['unknownLineageSeconds'],
                          result['foreignRunSeconds']), (20, 20, 0))

    def test_ancestry_never_crosses_into_another_run(self) -> None:
        spans = [run_span('production_total', 0, 100, 'R', spanId='w'),
                 run_span('bridge', 0, 100, 'Q', spanId='x', parentSpanId='w'),
                 run_span('child', 10, 40, 'R', parentSpanId='x')]
        result = workflow_coverage(spans, 'R')
        self.assertEqual((result['recordedSubstageSeconds'], result['unparentedSameRunSeconds']), (0, 30))


if __name__ == '__main__':
    unittest.main()
