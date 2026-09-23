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


if __name__ == '__main__':
    unittest.main()
