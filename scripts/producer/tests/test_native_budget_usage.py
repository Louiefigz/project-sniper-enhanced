"""AI reservations and usage linked by run, task and host id; replays once, unknown never zero."""
from __future__ import annotations

import json
import unittest

import agent_usage
from _budget_fixture import host_turn
from _status_fixture import batch_record, enroll, record_usage, run_task, temporary_directory, usage
from studio.native_budget_usage import ai_usage
from studio.native_budget_schema import validate_record

WINDOW_END = 10_000.0
CLAUDE = {'type': 'host', 'host': 'claude-code', 'thread': 'TEST-session', 'turn': None}


class Case(unittest.TestCase):
    """clip A author (Codex turn), clip B author, an enrolled director."""

    def setUp(self) -> None:
        self.record = batch_record()
        enroll(self.record)
        self.author_a = run_task(self.record, ('author-A', 'author', {}), host_turn('A'), (10.0, 400.0))
        self.author_b = run_task(self.record, ('author-B', 'author', {'clip_id': 'B'}), host_turn('B'), (10.0, None))

    def usage(self, clip: str | None, transcripts: dict | None = None) -> dict:
        validate_record(self.record)
        return ai_usage(self.record, clip, transcripts)


class AuthorityUsageTests(Case):
    """Per-task cumulative reports: replays never add, missing is unknown, cached is part of input."""

    def test_missing_usage_is_unknown_not_zero(self) -> None:
        record_usage(self.record, 'author-A', usage(1000, 800, 50), 400.0)
        run = self.usage(None)['usage']
        self.assertFalse(run['coverage']['complete'])
        self.assertIsNone(run['authority']['totals']['inputTokens'])
        self.assertEqual(run['authority']['knownPartial']['inputTokens'], 1000)
        self.assertEqual(run['authority']['unknownExecutions']['inputTokens'], 2)  # director and author-B

    def test_a_replayed_or_lower_report_never_adds_and_cached_is_not_added_to_input(self) -> None:
        for value in (usage(1000, 800, 50), usage(1000, 800, 50), usage(900, 700, 40)):
            record_usage(self.record, 'author-A', value, 400.0)
        clip = self.usage('A')['usage']['authority']
        self.assertEqual(clip['totals'], {'inputTokens': 1000, 'cachedInputTokens': 800, 'outputTokens': 50,
                                          'reasoningTokens': 0})

    def test_tasks_naming_the_same_host_turn_are_one_execution(self) -> None:
        self.record['production']['tasks']['author-B']['handle'] = dict(self.author_a['handle'])
        record_usage(self.record, 'author-A', usage(1000, 800, 50), 400.0)
        record_usage(self.record, 'author-B', usage(1200, 900, 60), 400.0)
        tasks = [row for row in self.record['production']['tasks'].values() if row['id'] != 'director']
        from studio.native_budget_usage import authority_usage
        found = authority_usage(tasks)
        self.assertEqual((found['executions'], found['tasksSharingAnExecution']), (1, 1))
        self.assertEqual(found['totals']['inputTokens'], 1200)

    def test_ai_work_admitted_without_a_task_makes_the_totals_unknown(self) -> None:
        record_usage(self.record, 'author-A', usage(1000, 800, 50), 400.0)
        clip = self.usage('A')['usage']
        self.assertEqual(clip['authority']['totals']['inputTokens'], 1000)
        self.record['clips']['A']['dispatches'].append({'kind': 'review', 'label': 'TEST admit', 'elapsed': 500.0})
        clip = self.usage('A')['usage']
        self.assertEqual((clip['coverage']['untrackedDispatches'], clip['coverage']['complete']), (1, False))
        self.assertIsNone(clip['authority']['totals']['inputTokens'])
        self.assertEqual(clip['authority']['knownPartial']['inputTokens'], 1000)

    def test_tasks_on_one_thread_without_a_turn_are_separate_executions(self) -> None:
        """probe_turnless: a handle without a turn identifies no turn, so nothing is merged by thread."""
        for task_id in ('author-A', 'author-B'):
            self.record['production']['tasks'][task_id]['handle'] = dict(CLAUDE)
        record_usage(self.record, 'author-A', usage(1000, 800, 100), 400.0)
        record_usage(self.record, 'author-B', usage(600, 500, 50), 400.0)
        tasks = [row for row in self.record['production']['tasks'].values() if row['id'] != 'director']
        from studio.native_budget_usage import authority_usage
        found = authority_usage(tasks)
        self.assertEqual((found['executions'], found['tasksSharingAnExecution'], found['totals']['inputTokens']),
                         (2, 0, 1600))

    def test_reservations_per_output_and_per_run(self) -> None:
        clip = self.usage('A')['reservations']
        self.assertEqual((clip['dispatchCounters']['author'], clip['chargedTasks'], clip['holdingSlots']),
                         ('1/3', 1, 0))
        run = self.usage(None)['reservations']
        self.assertEqual((run['charged'], run['activeSlots']), (3, 2))  # director + two authors; A completed


class TranscriptLinkTests(Case):
    """Transcripts link to tasks by host, thread and turn; unlinked or missing records keep totals unknown."""

    def transcripts(self, rows: dict) -> dict:
        directory = temporary_directory(self)
        files = []
        for name, lines in rows.items():
            files.append(directory / name)
            files[-1].write_text(''.join(json.dumps(line) + '\n' for line in lines))
        return agent_usage.collect_files(files, (self.record['startEpoch'], self.record['startEpoch'] + WINDOW_END))

    def codex(self, turn: str, response: str, fields: tuple[int, int, int]) -> dict:
        stamp = self.record['startEpoch'] + 100
        return {'timestamp': str(stamp), 'type': 'token_usage_record', 'payload': {
            'thread_id': f'TEST-thread-{turn}', 'turn_id': f'TEST-turn-{turn}', 'response_id': response,
            'usage': {'input_tokens': fields[0], 'cached_input_tokens': fields[1], 'cache_write_input_tokens': 0,
                      'output_tokens': fields[2], 'reasoning_output_tokens': 0}}}

    def claude(self, message: str, output: int) -> dict:
        return {'type': 'assistant', 'timestamp': str(self.record['startEpoch'] + 200), 'sessionId': 'TEST-session',
                'message': {'id': message, 'usage': {'input_tokens': 1, 'cache_creation_input_tokens': 2,
                                                     'cache_read_input_tokens': 3, 'output_tokens': output}}}

    def test_turn_level_links_and_replays_count_once(self) -> None:
        found = self.transcripts({'a.jsonl': [self.codex('A', 'r1', (100, 60, 5))],
                                  'b.jsonl': [self.codex('A', 'r1', (100, 60, 5)), self.codex('B', 'r2', (50, 0, 2))]})
        clip = self.usage('A', found)['usage']['transcripts']
        self.assertEqual((clip['links'][0]['level'], clip['links'][0]['records']), ('turn', 1))
        self.assertEqual(clip['totals'], {'inputTokens': 100, 'cachedInputTokens': 60, 'outputTokens': 5,
                                          'reasoningTokens': 0})
        run = self.usage(None, found)['usage']['transcripts']
        self.assertEqual((run['repeatsDropped'], run['unlinked']['records']), (1, 0))
        self.assertIsNone(run['totals']['inputTokens'])  # the director's turn has no transcript record
        self.assertEqual(run['unknownBecause'], ['1 host task(s) have no transcript record'])
        self.assertEqual(run['knownPartial']['inputTokens'], 150)

    def test_run_totals_include_unlinked_records_and_stay_unknown_while_any_exist(self) -> None:
        found = self.transcripts({'a.jsonl': [self.codex('A', 'r1', (100, 60, 5)), self.codex('B', 'r2', (50, 0, 2)),
                                              self.codex('director', 'r3', (7, 0, 1)),
                                              self.codex('Z', 'r9', (10, 0, 1))]})
        run = self.usage(None, found)['usage']['transcripts']
        self.assertEqual((run['unlinked']['records'], run['unlinked']['inputTokens']), (1, 10))
        self.assertEqual((run['linked']['inputTokens'], run['knownPartial']['inputTokens']), (157, 167))
        self.assertIsNone(run['totals']['inputTokens'])
        self.assertIn('1 record(s) name no task of this run', run['unknownBecause'])

    def test_a_thread_shared_by_two_outputs_is_reported_only_for_the_run(self) -> None:
        for task_id in ('author-A', 'author-B'):
            self.record['production']['tasks'][task_id]['handle'] = dict(CLAUDE)
        found = self.transcripts({'s.jsonl': [self.claude('m1', 4), self.claude('m2', 6)]})
        clip = self.usage('A', found)['usage']['transcripts']
        self.assertEqual((clip['links'], len(clip['sharedAcrossOutputsExcluded'])), ([], 1))
        self.assertIsNone(clip['totals']['outputTokens'])
        run = self.usage(None, found)['usage']['transcripts']
        shared = [row for row in run['links'] if row['level'] == 'thread']
        self.assertEqual((shared[0]['records'], shared[0]['usage']['outputTokens']), (2, 10))
        self.assertEqual(shared[0]['usage']['inputTokens'], 12)  # 1 + 2 + 3 per message: cache parts once

    def test_nothing_observed_is_unknown_never_zero(self) -> None:
        empty = self.transcripts({'empty.jsonl': []})
        run = self.usage(None, empty)['usage']['transcripts']
        self.assertEqual(run['totals'], dict.fromkeys(('inputTokens', 'cachedInputTokens', 'outputTokens',
                                                       'reasoningTokens')))
        self.assertIn('no transcript record was observed', run['unknownBecause'])
        self.assertEqual(self.usage('A')['usage']['transcripts']['status'], 'not-supplied')
        bare = batch_record()
        authority = ai_usage(bare, None, None)['usage']['authority']
        self.assertEqual((authority['executions'], authority['totals']['inputTokens']), (0, None))
        self.assertIn('no execution was observed', authority['unknownBecause'])

    def test_an_unreadable_transcript_is_named_and_keeps_totals_unknown(self) -> None:
        directory = temporary_directory(self)
        good, broken = directory / 'a.jsonl', directory / 'broken.jsonl'
        good.write_text(json.dumps(self.codex('A', 'r1', (100, 60, 5))) + '\n')
        broken.write_text('{"x"\n')
        window = (self.record['startEpoch'], self.record['startEpoch'] + WINDOW_END)
        clip = self.usage('A', agent_usage.collect_files([good, broken], window))['usage']['transcripts']
        self.assertIn('1 transcript(s) were unreadable', clip['unknownBecause'])
        self.assertEqual((clip['totals']['inputTokens'], clip['knownPartial']['inputTokens']), (None, 100))


if __name__ == '__main__':
    unittest.main()
