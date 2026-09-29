"""Elapsed-time breakdown: parallel intervals count once, waits are separated, absent evidence is unknown."""
from __future__ import annotations

import unittest

from _budget_fixture import CHILD, host_turn, task_spec
from _status_fixture import BATCH, START, attempt, batch_record, enroll, run_task, temporary_directory
from stage_timing_report import summarize_timings
from studio.native_budget_breakdown import breakdown, merged, subtract
from studio.production import claims, tasks
from test_stage_timing_v2 import SHA_A, _row


def span(name: str, window: tuple[float, float], activity: str, **fields: object) -> list[dict]:
    """One exact v2 span of the batch's run on the wall clock (batch elapsed + START)."""
    start, end = window
    common = {'stage': name, 'metadata': {'activity': activity}, 'runId': BATCH, **fields}
    return [_row(name, 'start', start, ts=START + start, **common),
            _row(name, 'end', end, ts=START + end, elapsedMs=(end - start) * 1000, **common)]


def handoff(phase: str, at: float, event: str, **fields: object) -> dict:
    """One handoff event of the batch's run."""
    return {**_row('', 'handoff', at, stage='clip_author', ts=START + at, runId=BATCH), 'handoffPhase': phase,
            'eventId': event, 'taskId': 'author-A', 'claimEpoch': 1, 'artifactSha256': SHA_A, **fields}


class IntervalTests(unittest.TestCase):
    """The interval helpers never count an instant twice."""

    def test_merge_and_subtract(self) -> None:
        self.assertEqual(merged([(5, 9), (0, 3), (2, 4)]), [(0, 4), (5, 9)])
        self.assertEqual(subtract([(0, 10)], [(2, 3), (2.5, 4), (9, 12)]), [(0, 2), (4, 9)])


class BreakdownTests(unittest.TestCase):
    """A batch with three overlapping launches, tasks and a journal."""

    def setUp(self) -> None:
        self.record = batch_record(('A', 'B'))
        self.record['production']['authorization']['setupElapsed'] = 30.0
        clips = self.record['clips']
        clips['A']['attempts'] += [attempt('preview', 100.0, completed=500.0), attempt('draft', 550.0, completed=700.0)]
        clips['B']['attempts'].append(attempt('draft', 200.0, completed=600.0))

    def test_parallel_launches_count_once_and_nothing_is_summed_into_elapsed(self) -> None:
        result = breakdown(self.record, 1000.0, None)
        media = result['categories']['mediaExecution']
        self.assertEqual((media['status'], media['unionSeconds'], media['launches']), ('measured', 600.0, 3))
        self.assertEqual(result['categories']['sharedPreparation']['unionSeconds'], 30.0)
        self.assertEqual((result['categorizedUnionSeconds'], result['unattributedSeconds']), (630.0, 370.0))

    def test_without_a_journal_timing_categories_are_unknown_not_zero(self) -> None:
        categories = breakdown(self.record, 1000.0, None)['categories']
        for name in ('model', 'tool', 'mediaQueuePressure', 'publishedNotAccepted'):
            self.assertEqual((categories[name]['status'], categories[name]['unionSeconds']), ('unknown', None))
            self.assertIn('no timing journal', categories[name]['reason'])
        self.assertEqual(categories['repair']['status'], 'unknown')

    def test_queue_waits_leave_media_execution_and_overlaps_are_reported(self) -> None:
        rows = [*span('queue-A', (100.0, 180.0), 'native-queue-wait'),
                *span('pressure-B', (150.0, 260.0), 'pressure-wait'),
                *span('model-1', (40.0, 300.0), 'model'), *span('tool-1', (250.0, 350.0), 'tool'),
                *span('other-run', (0.0, 900.0), 'model', runId='another-run')]
        result = breakdown(self.record, 1000.0, summarize_timings(rows, BATCH))
        categories = result['categories']
        self.assertEqual(categories['mediaQueuePressure']['unionSeconds'], 160.0)
        self.assertEqual(categories['mediaExecution']['unionSeconds'], 440.0)
        self.assertEqual((categories['model']['unionSeconds'], categories['tool']['unionSeconds']), (260.0, 100.0))
        self.assertGreater(result['concurrentOverlapSeconds'], 0)
        self.assertAlmostEqual(result['categorySumSeconds'] - result['concurrentOverlapSeconds'],
                               result['categorizedUnionSeconds'], places=3)

    def test_publications_wait_until_accepted_or_until_now(self) -> None:
        rows = [handoff('artifact-published', 500.0, 'p1'), handoff('consumer-accepted', 560.0, 'c1', consumerId='x'),
                handoff('artifact-published', 900.0, 'p2', artifactSha256='b' * 64)]
        category = breakdown(self.record, 1000.0, summarize_timings(rows, BATCH))['categories']['publishedNotAccepted']
        self.assertEqual((category['unionSeconds'], category['intervals']), (160.0, 2))

    def test_ready_but_no_agent_runs_from_the_last_prerequisite_to_the_claim(self) -> None:
        enroll(self.record)
        run_task(self.record, ('author-A', 'author', {}), host_turn('A'), (10.0, 400.0))
        run_task(self.record, ('check-A', 'check', {'clip_id': 'A'}), CHILD, (10.0, 20.0))
        tasks.enqueue(self.record, (task_spec('repair-A', 'repairCycle', parent='director',
                                              prerequisites=('author-A',)),), 300.0)
        claims.claim(self.record, 'repair-A', {'type': 'process', 'pid': 9, 'pgid': 9, 'started': 'TEST'}, 450.0)
        result = breakdown(self.record, 1000.0, None, ('A', ()))
        self.assertEqual(result['categories']['readyWithoutAgent']['unionSeconds'], 50.0)  # check-A is code
        self.assertEqual(result['categories']['repair']['unionSeconds'], 550.0)

    def test_a_reclaimed_task_keeps_no_wait_time_and_says_so(self) -> None:
        enroll(self.record)
        task = run_task(self.record, ('author-A', 'author', {}), host_turn('A'), (10.0, None))
        task['epochs'] = 2
        task['claim']['epoch'] = 2
        result = breakdown(self.record, 1000.0, None, ('A', ()))
        self.assertEqual(result['untimedReadyWaits'], 1)

    def test_a_released_claim_is_timed_from_the_trail_or_named_untimed(self) -> None:
        """probe_breakdown.ReleasedClaim: ready 10 -> claimed 100 -> released 300 -> still waiting at 1000."""
        enroll(self.record)
        tasks.enqueue(self.record, (task_spec('author-A', 'author', parent='director'),), 10.0)
        outcome = claims.claim(self.record, 'author-A', CHILD, 100.0)
        claims.release(self.record, claims.ClaimRef('author-A', 1, outcome.detail['token']), 300.0)
        trail = ({'event': 'task-claimed', 'taskId': 'author-A', 'epoch': 1, 'elapsed': 100.0},
                 {'event': 'task-released', 'taskId': 'author-A', 'epoch': 1, 'elapsed': 300.0})
        timed = breakdown(self.record, 1000.0, None, ('A', trail))
        self.assertEqual((timed['untimedReadyWaits'], timed['categories']['readyWithoutAgent']['unionSeconds']),
                         (0, 90.0 + 700.0))
        untimed = breakdown(self.record, 1000.0, None, ('A', trail[1:]))
        self.assertEqual((untimed['untimedReadyWaits'], untimed['categories']['readyWithoutAgent']['status']),
                         (1, 'unknown'))

    def test_a_launchs_own_pool_wait_is_attributed_to_its_output(self) -> None:
        """probe_breakdown.PoolWaitAttribution: a pool wait with no task id, journaled in the attempt directory."""
        directory = temporary_directory(self)
        self.record['clips']['A']['attempts'][1]['output'] = str(directory)
        rows = [{**row, 'journalDir': str(directory)} for row in span('pool-wait', (560.0, 640.0), 'native-queue-wait',
                                                                       runId='exporter-run')]
        timing = {**summarize_timings(rows, BATCH), 'journalDirs': [str(directory)]}
        run, clip = breakdown(self.record, 1000.0, timing), breakdown(self.record, 1000.0, timing, ('A', ()))
        for result, execution in ((run, 600.0 - 80.0), (clip, 550.0 - 80.0)):
            categories = result['categories']
            self.assertEqual(categories['mediaQueuePressure']['unionSeconds'], 80.0)
            self.assertEqual(categories['mediaExecution']['unionSeconds'], execution)
        self.assertEqual(clip['categories']['mediaExecution']['includesUnattributedQueueTime'], True)
        self.assertIn('1 launch(es) have no supplied attempt journal', clip['categories']['mediaExecution']
                      ['unattributedQueueTime'])
        other = breakdown(self.record, 1000.0, timing, ('B', ()))['categories']
        self.assertEqual(other['mediaQueuePressure']['status'], 'unknown')

    def test_an_unknown_queue_names_unattributed_waits_instead_of_saying_none_was_recorded(self) -> None:
        """probe_v2.PoolWait: A's launch has no supplied attempt journal, so its queue time is not attributed."""
        record = batch_record(('A', 'B'))
        record['clips']['A']['attempts'].append(attempt('draft', 550.0, completed=700.0))
        timing = summarize_timings(span('pool-wait-A', (560.0, 640.0), 'native-queue-wait'), BATCH)
        queue = breakdown(record, 1000.0, timing, ('A', ()))['categories']['mediaQueuePressure']
        self.assertEqual(queue['status'], 'unknown')
        self.assertNotIn('no interval of this kind was recorded', queue['reason'])
        self.assertIn('queue time may exist but is not attributed: 1 launch(es)', queue['reason'])

    def test_shared_preparation_is_setup_plus_run_scoped_preparation_tasks_not_reviews(self) -> None:
        enroll(self.record)
        run_task(self.record, ('plan-shared', 'planning', {}), host_turn('plan'), (30.0, 120.0))
        run_task(self.record, ('review-shared', 'review', {}), host_turn('review'), (200.0, 300.0))
        for clip in (None, 'B'):
            shared = breakdown(self.record, 1000.0, None, (clip, ()))['categories']['sharedPreparation']
            self.assertEqual(shared['unionSeconds'], 120.0)

    def test_one_outputs_breakdown_excludes_the_others_launches(self) -> None:
        clip = breakdown(self.record, 1000.0, None, ('B', ()))
        self.assertEqual(clip['categories']['mediaExecution']['unionSeconds'], 400.0)
        self.assertEqual(clip['categories']['sharedPreparation']['unionSeconds'], 30.0)
        self.assertEqual(clip['scope'], 'B')


if __name__ == '__main__':
    unittest.main()
